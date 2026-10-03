import hashlib
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter

from logger import get_logger
from settings import get_app_directory, get_temporary_directory
from translator import translate as _


LOGGER = get_logger(__name__)

CHUNK_SIZE = 256 * 1024
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 20
RETRY_DELAYS = (1, 2, 4, 8, 16, 30)
TRANSIENT_HTTP_STATUSES = {
    403,
    408,
    425,
    429,
    500,
    502,
    503,
    504
}
MANIFEST_VERSION = 1


class DownloadCancelled(Exception):
    pass


class RetryableDownloadError(Exception):
    pass


class RemoteFileChangedError(Exception):
    pass


@dataclass(frozen=True)
class RemoteFileInfo:
    size: int
    supports_ranges: bool
    etag: str = ""
    last_modified: str = ""

    @property
    def validator(self):
        if self.etag and not self.etag.startswith("W/"):
            return self.etag

        return self.last_modified


class DownloadManager:
    def __init__(
        self,
        progress_callback=None,
        status_callback=None,
        activity_callback=None,
        cancel_event=None
    ):
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept-Encoding": "identity"
        }

        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.activity_callback = activity_callback
        self.cancel_event = cancel_event or threading.Event()

        self.__stop_event = threading.Event()
        self.__thread_local = threading.local()
        self.__sessions = []
        self.__sessions_lock = threading.Lock()

    def cancel(self):
        self.cancel_event.set()

    def __set_status(self, text):
        if self.status_callback:
            self.status_callback(text)

    def __set_activity(self, text):
        if self.activity_callback:
            self.activity_callback(text)

    def __set_progress(self, current, total):
        if total <= 0:
            return

        percent = min(
            max(current / total, 0),
            1.0
        )

        if self.progress_callback:
            self.progress_callback(
                current,
                total,
                percent
            )

    def __check_cancelled(self):
        if (
            self.cancel_event.is_set()
            or self.__stop_event.is_set()
        ):
            raise DownloadCancelled(
                _("Download cancelled.")
            )

    def __get_session(self):
        session = getattr(
            self.__thread_local,
            "session",
            None
        )

        if session is not None:
            return session

        session = requests.Session()
        session.headers.update(
            self.headers
        )

        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=1,
            max_retries=0
        )

        session.mount(
            "http://",
            adapter
        )

        session.mount(
            "https://",
            adapter
        )

        self.__thread_local.session = session

        with self.__sessions_lock:
            self.__sessions.append(
                session
            )

        return session

    def __close_sessions(self):
        with self.__sessions_lock:
            sessions = self.__sessions
            self.__sessions = []

        for session in sessions:
            session.close()

    def run(
        self,
        path,
        segment_size_kb,
        thread_count,
        file_name,
        file_extension,
        url
    ):
        self.__stop_event.clear()

        try:
            return self.__run(
                path=path,
                segment_size_kb=segment_size_kb,
                thread_count=thread_count,
                file_name=file_name,
                file_extension=file_extension,
                url=url
            )

        finally:
            self.__close_sessions()

    def __run(
        self,
        path,
        segment_size_kb,
        thread_count,
        file_name,
        file_extension,
        url
    ):
        self.__validate_file_name(
            file_name,
            file_extension
        )

        self.__check_cancelled()

        requested_file_name = file_name + file_extension
        output_directory = Path(path).expanduser().resolve()

        output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        final_path = self.__available_output_path(
            output_directory=output_directory,
            file_name=file_name,
            file_extension=file_extension
        )
        full_file_name = final_path.name

        if full_file_name != requested_file_name:
            self.__set_activity(
                _(
                    "The output file already exists. "
                    "Saving as {file_name}."
                ).format(
                    file_name=full_file_name
                )
            )

            LOGGER.info(
                "Output file already exists; selected available "
                "name: %s.",
                full_file_name
            )

        LOGGER.info(
            "Download started: file=%s, threads=%d, "
            "segment_size_kb=%d, output=%s.",
            full_file_name,
            thread_count,
            segment_size_kb,
            output_directory
        )

        temporary_directory = self.__prepare_temporary_directory(
            output_directory
        )

        self.__set_status(
            _("Checking file...")
        )

        remote_info = self.__probe_remote_file(
            url
        )

        self.__ensure_disk_space(
            output_directory,
            remote_info.size
        )

        segment_size_bytes = segment_size_kb * 1024

        if remote_info.supports_ranges:
            segments = self.__create_segments(
                remote_info.size,
                segment_size_bytes
            )

            mode = "segmented"

        else:
            segments = [
                (0, remote_info.size - 1)
            ]

            mode = "single"

            self.__set_activity(
                _(
                    "The server does not support segmented downloads. "
                    "Using one connection."
                )
            )

        workspace = self.__prepare_download_workspace(
            temporary_directory=temporary_directory,
            final_path=final_path,
            full_file_name=full_file_name,
            segment_size_bytes=segment_size_bytes,
            mode=mode,
            url=url,
            remote_info=remote_info
        )

        segment_count = len(segments)

        LOGGER.info(
            "Remote file size is %d bytes; mode=%s; segments=%d.",
            remote_info.size,
            mode,
            segment_count
        )

        self.__set_status(
            _("Downloading - {segment_count} segments").format(
                segment_count=segment_count
            )
        )

        if remote_info.supports_ranges:
            self.__download_all_segments(
                url=url,
                segments=segments,
                workspace=workspace,
                thread_count=thread_count,
                remote_info=remote_info
            )

        else:
            self.__download_single_stream(
                url=url,
                workspace=workspace,
                remote_info=remote_info
            )

        self.__check_cancelled()

        self.__set_activity(
            _("All segments downloaded. Merging file...")
        )

        self.__set_status(
            _("Merging segments...")
        )

        LOGGER.info(
            "Merging %d segments into %s.",
            segment_count,
            final_path
        )

        self.__merge_segments(
            workspace=workspace,
            segments=segments,
            final_path=final_path,
            expected_size=remote_info.size
        )

        self.__set_progress(
            remote_info.size,
            remote_info.size
        )

        self.__set_status(
            _("Download completed")
        )

        self.__set_activity(
            _("File saved successfully.")
        )

        LOGGER.info(
            "Download completed: %s.",
            final_path
        )

        return str(final_path)

    def __validate_file_name(
        self,
        file_name,
        file_extension
    ):
        full_file_name = file_name + file_extension

        if (
            not file_name
            or file_name in {".", ".."}
            or "/" in full_file_name
            or "\\" in full_file_name
        ):
            raise ValueError(
                _(
                    "The file name and extension cannot contain "
                    "path separators."
                )
            )

    def __available_output_path(
        self,
        output_directory,
        file_name,
        file_extension
    ):
        candidate = (
            output_directory
            / f"{file_name}{file_extension}"
        )

        if not candidate.exists() and not candidate.is_symlink():
            return candidate

        for number in count(1):
            candidate = (
                output_directory
                / f"{file_name} ({number}){file_extension}"
            )

            if not candidate.exists() and not candidate.is_symlink():
                return candidate

    def __prepare_temporary_directory(
        self,
        output_directory
    ):
        app_directory = (
            get_app_directory()
            .expanduser()
            .resolve()
        )

        configured_directory = (
            get_temporary_directory()
            .expanduser()
        )

        expected_directory = (
            app_directory
            / "tmp"
        )

        resolved_directory = (
            configured_directory
            .resolve()
        )

        if (
            configured_directory.is_symlink()
            or resolved_directory != expected_directory
        ):
            raise RuntimeError(
                _("The temporary directory path is invalid.")
            )

        if (
            output_directory == resolved_directory
            or resolved_directory in output_directory.parents
        ):
            raise RuntimeError(
                _(
                    "The output directory cannot be located "
                    "inside the temporary directory."
                )
            )

        if configured_directory.exists():
            if not configured_directory.is_dir():
                raise RuntimeError(
                    _("The temporary directory path is invalid.")
                )

        else:
            configured_directory.mkdir(
                parents=True,
                exist_ok=True
            )

        LOGGER.info(
            "Temporary directory is ready: %s.",
            configured_directory
        )

        return configured_directory.resolve()

    def __probe_remote_file(self, url):
        for attempt in count(1):
            self.__check_cancelled()

            try:
                return self.__probe_remote_file_once(
                    url
                )

            except DownloadCancelled:
                raise

            except Exception as error:
                if not self.__is_retryable_error(error):
                    raise

                delay = self.__retry_delay(
                    attempt
                )
                description = self.__describe_error(error)

                self.__set_activity(
                    _(
                        "Server check failed ({error}). "
                        "Retrying in {seconds} s..."
                    ).format(
                        error=description,
                        seconds=delay
                    )
                )

                LOGGER.warning(
                    "Remote file check failed on attempt %d (%s).",
                    attempt,
                    type(error).__name__
                )

                self.__wait_for_retry(
                    delay
                )

    def __probe_remote_file_once(self, url):
        session = self.__get_session()
        metadata = {}

        with session.head(
            url,
            allow_redirects=True,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT
            )
        ) as response:
            if response.status_code in TRANSIENT_HTTP_STATUSES:
                raise RetryableDownloadError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

            if response.ok:
                metadata = self.__response_metadata(
                    response
                )

            elif response.status_code not in {
                403,
                405,
                501
            }:
                raise RuntimeError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

        headers = {
            "Range": "bytes=0-0"
        }

        with session.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT
            )
        ) as response:
            if response.status_code in TRANSIENT_HTTP_STATUSES:
                raise RetryableDownloadError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

            response_metadata = self.__response_metadata(
                response
            )

            for key, value in response_metadata.items():
                if value:
                    metadata[key] = value

            if response.status_code == 206:
                total_size = self.__content_range_total(
                    response.headers.get("Content-Range", "")
                )

                if total_size is None:
                    raise RetryableDownloadError(
                        _(
                            "The server returned HTTP 206 without "
                            "a valid Content-Range header."
                        )
                    )

                return RemoteFileInfo(
                    size=total_size,
                    supports_ranges=True,
                    etag=metadata.get("etag", ""),
                    last_modified=metadata.get(
                        "last_modified",
                        ""
                    )
                )

            if response.status_code == 200:
                content_length = response.headers.get(
                    "Content-Length"
                ) or metadata.get("content_length")

                if content_length is None:
                    raise RuntimeError(
                        _("Could not determine the file size.")
                    )

                return RemoteFileInfo(
                    size=int(content_length),
                    supports_ranges=False,
                    etag=metadata.get("etag", ""),
                    last_modified=metadata.get(
                        "last_modified",
                        ""
                    )
                )

            if (
                response.status_code == 416
                and str(metadata.get("content_length")) == "0"
            ):
                return RemoteFileInfo(
                    size=0,
                    supports_ranges=False,
                    etag=metadata.get("etag", ""),
                    last_modified=metadata.get(
                        "last_modified",
                        ""
                    )
                )

            raise RuntimeError(
                _("Server returned HTTP {status_code}.").format(
                    status_code=response.status_code
                )
            )

    def __response_metadata(self, response):
        return {
            "etag": response.headers.get("ETag", "").strip(),
            "last_modified": response.headers.get(
                "Last-Modified",
                ""
            ).strip(),
            "content_length": response.headers.get(
                "Content-Length"
            )
        }

    def __content_range_total(self, content_range):
        try:
            unit_and_range, total = content_range.rsplit(
                "/",
                1
            )

            if (
                not unit_and_range.startswith("bytes ")
                or total == "*"
            ):
                return None

            return int(total)

        except (TypeError, ValueError):
            return None

    def __prepare_download_workspace(
        self,
        temporary_directory,
        final_path,
        full_file_name,
        segment_size_bytes,
        mode,
        url,
        remote_info
    ):
        source_identity = self.__source_identity(
            url,
            remote_info
        )

        identity_text = (
            f"{str(final_path).casefold()}\0{source_identity}"
        )

        identity = identity_text.encode(
            "utf-8",
            errors="surrogatepass"
        )

        workspace_name = hashlib.sha256(
            identity
        ).hexdigest()[:24]

        workspace = temporary_directory / workspace_name
        manifest_path = workspace / "download.json"

        expected_manifest = {
            "version": MANIFEST_VERSION,
            "url": url,
            "source_identity": source_identity,
            "final_path": str(final_path),
            "file_name": full_file_name,
            "file_size": remote_info.size,
            "segment_size": segment_size_bytes,
            "mode": mode,
            "etag": remote_info.etag,
            "last_modified": remote_info.last_modified
        }

        legacy_identity = str(final_path).casefold().encode(
            "utf-8",
            errors="surrogatepass"
        )

        legacy_name = hashlib.sha256(
            legacy_identity
        ).hexdigest()[:24]

        legacy_workspace = temporary_directory / legacy_name

        if (
            legacy_workspace != workspace
            and not workspace.exists()
            and legacy_workspace.is_dir()
            and not legacy_workspace.is_symlink()
        ):
            legacy_manifest = self.__load_manifest(
                legacy_workspace / "download.json"
            )

            if self.__manifest_is_compatible(
                legacy_manifest,
                expected_manifest
            ):
                legacy_workspace.replace(
                    workspace
                )

                LOGGER.info(
                    "Migrated a compatible legacy download workspace: %s.",
                    workspace
                )

        saved_manifest = self.__load_manifest(
            manifest_path
        )

        can_resume = self.__manifest_is_compatible(
            saved_manifest,
            expected_manifest
        )

        if workspace.exists() and not can_resume:
            if workspace.is_symlink():
                workspace.unlink()

            elif workspace.is_dir():
                shutil.rmtree(
                    workspace
                )

            else:
                workspace.unlink()

            self.__set_activity(
                _(
                    "Previous partial download does not match the "
                    "remote file. Starting over."
                )
            )

        workspace.mkdir(
            parents=True,
            exist_ok=True
        )

        self.__save_manifest(
            manifest_path,
            expected_manifest
        )

        if can_resume:
            self.__set_activity(
                _("Found previous partial download. Resuming...")
            )

            LOGGER.info(
                "Compatible partial download found: %s.",
                workspace
            )

        return workspace

    def __source_identity(
        self,
        url,
        remote_info
    ):
        if remote_info.etag:
            return f"etag:{remote_info.etag}"

        parsed_url = urlsplit(
            url
        )

        stable_url = (
            f"{parsed_url.scheme.lower()}://"
            f"{parsed_url.netloc.lower()}"
            f"{parsed_url.path}"
        )

        return f"url:{stable_url}"

    def __load_manifest(self, manifest_path):
        try:
            with manifest_path.open(
                "r",
                encoding="utf-8"
            ) as file:
                manifest = json.load(file)

            if isinstance(manifest, dict):
                return manifest

        except (
            FileNotFoundError,
            json.JSONDecodeError,
            OSError
        ):
            pass

        return None

    def __save_manifest(self, manifest_path, manifest):
        temporary_path = manifest_path.with_suffix(
            ".json.tmp"
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
            newline="\n"
        ) as file:
            json.dump(
                manifest,
                file,
                ensure_ascii=False,
                indent=2
            )

            file.write("\n")

        temporary_path.replace(
            manifest_path
        )

    def __manifest_is_compatible(
        self,
        saved,
        expected
    ):
        if not isinstance(saved, dict):
            return False

        saved_source_identity = saved.get(
            "source_identity"
        )

        if not saved_source_identity:
            saved_remote_info = RemoteFileInfo(
                size=0,
                supports_ranges=(
                    saved.get("mode") == "segmented"
                ),
                etag=saved.get("etag", ""),
                last_modified=saved.get(
                    "last_modified",
                    ""
                )
            )

            saved_source_identity = self.__source_identity(
                saved.get("url", ""),
                saved_remote_info
            )

        if (
            saved_source_identity
            != expected.get("source_identity")
        ):
            return False

        for key in (
            "version",
            "final_path",
            "file_name",
            "file_size",
            "segment_size",
            "mode"
        ):
            if saved.get(key) != expected.get(key):
                return False

        saved_etag = saved.get("etag", "")
        expected_etag = expected.get("etag", "")

        if (
            saved_etag
            and expected_etag
            and saved_etag != expected_etag
        ):
            return False

        saved_modified = saved.get(
            "last_modified",
            ""
        )

        expected_modified = expected.get(
            "last_modified",
            ""
        )

        if (
            saved_modified
            and expected_modified
            and saved_modified != expected_modified
        ):
            return False

        if saved.get("url") == expected.get("url"):
            return True

        validators_match = bool(
            (
                saved_etag
                and expected_etag
                and saved_etag == expected_etag
            )
            or (
                saved_modified
                and expected_modified
                and saved_modified == expected_modified
            )
        )

        return (
            validators_match
            or saved_source_identity
            == expected.get("source_identity")
        )

    def __ensure_disk_space(
        self,
        output_directory,
        required_bytes
    ):
        available_bytes = shutil.disk_usage(
            output_directory
        ).free

        if available_bytes >= required_bytes:
            return

        raise RuntimeError(
            _(
                "Not enough free disk space. Required: {required}, "
                "available: {available}."
            ).format(
                required=self.__format_size(required_bytes),
                available=self.__format_size(available_bytes)
            )
        )

    def __format_size(self, byte_count):
        value = float(byte_count)

        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"

            value /= 1024

    def __create_segments(
        self,
        total_size,
        segment_size_bytes
    ):
        segments = []

        for start in range(
            0,
            total_size,
            segment_size_bytes
        ):
            end = min(
                start + segment_size_bytes - 1,
                total_size - 1
            )

            segments.append(
                (start, end)
            )

        return segments

    def __part_path(self, workspace, index):
        return workspace / f"segment-{index:08d}.part"

    def __download_segment(
        self,
        index,
        segment_count,
        start,
        end,
        url,
        workspace,
        remote_info,
        progress_callback
    ):
        part_path = self.__part_path(
            workspace,
            index
        )

        expected_size = end - start + 1
        current_size = self.__existing_part_size(
            part_path,
            expected_size
        )

        if current_size:
            progress_callback(
                current_size
            )

        if current_size == expected_size:
            self.__set_activity(
                _(
                    "Segment {index}/{segment_count} "
                    "was already downloaded."
                ).format(
                    index=index + 1,
                    segment_count=segment_count
                )
            )

            return

        for attempt in count(1):
            self.__check_cancelled()

            current_size = (
                part_path.stat().st_size
                if part_path.exists()
                else 0
            )

            resume_start = start + current_size
            headers = {
                "Range": f"bytes={resume_start}-{end}"
            }

            if remote_info.validator:
                headers["If-Range"] = remote_info.validator

            self.__set_activity(
                _(
                    "Segment {index}/{segment_count}: "
                    "request attempt {attempt}..."
                ).format(
                    index=index + 1,
                    segment_count=segment_count,
                    attempt=attempt
                )
            )

            try:
                self.__download_segment_attempt(
                    part_path=part_path,
                    current_size=current_size,
                    expected_size=expected_size,
                    resume_start=resume_start,
                    end=end,
                    url=url,
                    headers=headers,
                    remote_info=remote_info,
                    progress_callback=progress_callback
                )

                self.__set_activity(
                    _(
                        "Segment {index}/{segment_count} downloaded."
                    ).format(
                        index=index + 1,
                        segment_count=segment_count
                    )
                )

                return

            except (
                DownloadCancelled,
                RemoteFileChangedError
            ):
                raise

            except Exception as error:
                if not self.__is_retryable_error(error):
                    raise

                delay = self.__retry_delay(
                    attempt
                )

                self.__set_activity(
                    _(
                        "Segment {index}/{segment_count}: attempt "
                        "{attempt} failed ({error}). "
                        "Retrying in {seconds} s..."
                    ).format(
                        index=index + 1,
                        segment_count=segment_count,
                        attempt=attempt,
                        error=self.__describe_error(error),
                        seconds=delay
                    )
                )

                LOGGER.warning(
                    "Segment %d failed on attempt %d (%s).",
                    index,
                    attempt,
                    type(error).__name__
                )

                self.__wait_for_retry(
                    delay
                )

    def __download_segment_attempt(
        self,
        part_path,
        current_size,
        expected_size,
        resume_start,
        end,
        url,
        headers,
        remote_info,
        progress_callback
    ):
        session = self.__get_session()

        with session.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT
            )
        ) as response:
            if response.status_code in TRANSIENT_HTTP_STATUSES:
                raise RetryableDownloadError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

            if response.status_code == 200:
                raise RemoteFileChangedError(
                    _(
                        "The remote file changed during download. "
                        "Start the download again."
                    )
                )

            if response.status_code != 206:
                raise RuntimeError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

            self.__validate_response_identity(
                response,
                remote_info
            )

            expected_range = (
                f"bytes {resume_start}-{end}/{remote_info.size}"
            )

            received_range = response.headers.get(
                "Content-Range",
                ""
            )

            if received_range != expected_range:
                raise RetryableDownloadError(
                    _(
                        "Invalid Content-Range. Expected: {expected}, "
                        "received: {received}."
                    ).format(
                        expected=expected_range,
                        received=received_range or "-"
                    )
                )

            file_mode = "ab" if current_size else "wb"
            downloaded_size = current_size

            with part_path.open(
                file_mode
            ) as file:
                for chunk in response.iter_content(
                    chunk_size=CHUNK_SIZE
                ):
                    self.__check_cancelled()

                    if not chunk:
                        continue

                    remaining = expected_size - downloaded_size

                    if remaining <= 0:
                        break

                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]

                    file.write(
                        chunk
                    )

                    chunk_size = len(chunk)
                    downloaded_size += chunk_size

                    progress_callback(
                        chunk_size
                    )

        actual_size = part_path.stat().st_size

        if actual_size != expected_size:
            raise RetryableDownloadError(
                _(
                    "Incomplete response. Downloaded "
                    "{actual_size} / {expected_size} bytes."
                ).format(
                    actual_size=actual_size,
                    expected_size=expected_size
                )
            )

    def __existing_part_size(
        self,
        part_path,
        expected_size
    ):
        if not part_path.exists():
            return 0

        current_size = part_path.stat().st_size

        if current_size <= expected_size:
            return current_size

        part_path.unlink()

        return 0

    def __download_all_segments(
        self,
        url,
        segments,
        workspace,
        thread_count,
        remote_info
    ):
        total_size = remote_info.size
        downloaded_bytes = 0
        last_progress_update = 0.0
        segment_count = len(segments)
        progress_lock = threading.Lock()

        def update_progress(byte_count, force=False):
            nonlocal downloaded_bytes
            nonlocal last_progress_update

            with progress_lock:
                downloaded_bytes = max(
                    0,
                    min(
                        downloaded_bytes + byte_count,
                        total_size
                    )
                )

                current_time = time.monotonic()
                should_update = (
                    force
                    or downloaded_bytes == total_size
                    or current_time - last_progress_update >= 0.1
                )

                if not should_update:
                    return

                last_progress_update = current_time
                current_value = downloaded_bytes

            self.__set_progress(
                current_value,
                total_size
            )

        self.__set_progress(
            0,
            total_size
        )

        worker_count = min(
            thread_count,
            segment_count
        )

        executor = ThreadPoolExecutor(
            max_workers=worker_count
        )

        futures = []
        first_error = None

        try:
            for index, (start, end) in enumerate(segments):
                future = executor.submit(
                    self.__download_segment,
                    index,
                    segment_count,
                    start,
                    end,
                    url,
                    workspace,
                    remote_info,
                    update_progress
                )

                futures.append(
                    future
                )

            for future in as_completed(futures):
                try:
                    future.result()

                except Exception as error:
                    first_error = error
                    self.__stop_event.set()

                    for pending_future in futures:
                        pending_future.cancel()

                    break

        finally:
            executor.shutdown(
                wait=True,
                cancel_futures=True
            )

        if first_error is not None:
            raise first_error

        self.__check_cancelled()
        update_progress(
            0,
            force=True
        )

    def __download_single_stream(
        self,
        url,
        workspace,
        remote_info
    ):
        part_path = self.__part_path(
            workspace,
            0
        )

        existing_size = self.__existing_part_size(
            part_path,
            remote_info.size
        )

        if remote_info.size == 0:
            part_path.touch(
                exist_ok=True
            )

            self.__set_activity(
                _("The file was already downloaded. Preparing output...")
            )

            return

        if existing_size == remote_info.size:
            self.__set_progress(
                existing_size,
                remote_info.size
            )

            self.__set_activity(
                _("The file was already downloaded. Preparing output...")
            )

            return

        for attempt in count(1):
            self.__check_cancelled()

            if part_path.exists():
                previous_size = part_path.stat().st_size
                part_path.unlink()

                if previous_size:
                    self.__set_progress(
                        0,
                        remote_info.size
                    )

            self.__set_activity(
                _(
                    "Downloading with one connection: "
                    "attempt {attempt}..."
                ).format(
                    attempt=attempt
                )
            )

            try:
                self.__download_single_attempt(
                    url=url,
                    part_path=part_path,
                    remote_info=remote_info
                )

                return

            except (
                DownloadCancelled,
                RemoteFileChangedError
            ):
                raise

            except Exception as error:
                if not self.__is_retryable_error(error):
                    raise

                delay = self.__retry_delay(
                    attempt
                )

                self.__set_activity(
                    _(
                        "Download attempt {attempt} failed "
                        "({error}). Retrying in {seconds} s..."
                    ).format(
                        attempt=attempt,
                        error=self.__describe_error(error),
                        seconds=delay
                    )
                )

                self.__wait_for_retry(
                    delay
                )

    def __download_single_attempt(
        self,
        url,
        part_path,
        remote_info
    ):
        headers = {}

        if (
            remote_info.etag
            and not remote_info.etag.startswith("W/")
        ):
            headers["If-Match"] = remote_info.etag

        elif remote_info.last_modified:
            headers["If-Unmodified-Since"] = (
                remote_info.last_modified
            )

        session = self.__get_session()
        downloaded_size = 0
        last_progress_update = 0.0

        with session.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT
            )
        ) as response:
            if response.status_code in TRANSIENT_HTTP_STATUSES:
                raise RetryableDownloadError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

            if response.status_code == 412:
                raise RemoteFileChangedError(
                    _(
                        "The remote file changed during download. "
                        "Start the download again."
                    )
                )

            if response.status_code != 200:
                raise RuntimeError(
                    _("Server returned HTTP {status_code}.").format(
                        status_code=response.status_code
                    )
                )

            self.__validate_response_identity(
                response,
                remote_info
            )

            content_length = response.headers.get(
                "Content-Length"
            )

            if (
                content_length is not None
                and int(content_length) != remote_info.size
            ):
                raise RemoteFileChangedError(
                    _(
                        "The remote file changed during download. "
                        "Start the download again."
                    )
                )

            with part_path.open("wb") as file:
                for chunk in response.iter_content(
                    chunk_size=CHUNK_SIZE
                ):
                    self.__check_cancelled()

                    if not chunk:
                        continue

                    remaining = remote_info.size - downloaded_size

                    if remaining <= 0:
                        break

                    if len(chunk) > remaining:
                        chunk = chunk[:remaining]

                    file.write(chunk)
                    downloaded_size += len(chunk)

                    current_time = time.monotonic()

                    if (
                        downloaded_size == remote_info.size
                        or current_time - last_progress_update >= 0.1
                    ):
                        last_progress_update = current_time

                        self.__set_progress(
                            downloaded_size,
                            remote_info.size
                        )

        actual_size = part_path.stat().st_size

        if actual_size != remote_info.size:
            raise RetryableDownloadError(
                _(
                    "Incomplete response. Downloaded "
                    "{actual_size} / {expected_size} bytes."
                ).format(
                    actual_size=actual_size,
                    expected_size=remote_info.size
                )
            )

    def __wait_for_retry(self, seconds):
        if self.cancel_event.wait(seconds):
            raise DownloadCancelled(
                _("Download cancelled.")
            )

        self.__check_cancelled()

    def __retry_delay(self, attempt):
        delay_index = min(
            attempt - 1,
            len(RETRY_DELAYS) - 1
        )

        return RETRY_DELAYS[delay_index]

    def __validate_response_identity(
        self,
        response,
        remote_info
    ):
        response_etag = response.headers.get(
            "ETag",
            ""
        ).strip()

        if (
            remote_info.etag
            and response_etag
            and response_etag != remote_info.etag
        ):
            raise RemoteFileChangedError(
                _(
                    "The remote file changed during download. "
                    "Start the download again."
                )
            )

        response_modified = response.headers.get(
            "Last-Modified",
            ""
        ).strip()

        if (
            remote_info.last_modified
            and response_modified
            and response_modified != remote_info.last_modified
        ):
            raise RemoteFileChangedError(
                _(
                    "The remote file changed during download. "
                    "Start the download again."
                )
            )

    def __is_retryable_error(self, error):
        if isinstance(error, RetryableDownloadError):
            return True

        return isinstance(
            error,
            (
                requests.ConnectionError,
                requests.Timeout,
                requests.exceptions.ChunkedEncodingError
            )
        )

    def __describe_error(self, error):
        if isinstance(error, requests.RequestException):
            return type(error).__name__

        description = str(error).strip()

        if not description:
            return type(error).__name__

        return (
            description
            .replace("\r", " ")
            .replace("\n", " ")
        )

    def __merge_segments(
        self,
        workspace,
        segments,
        final_path,
        expected_size
    ):
        for index, (start, end) in enumerate(segments):
            part_path = self.__part_path(
                workspace,
                index
            )

            part_size = end - start + 1

            if (
                not part_path.is_file()
                or part_path.stat().st_size != part_size
            ):
                raise RuntimeError(
                    _("Missing or incomplete segment: {index}").format(
                        index=index + 1
                    )
                )

        temporary_output = final_path.with_name(
            final_path.name + ".downloading"
        )

        if temporary_output.exists():
            if temporary_output.is_file():
                temporary_output.unlink()

            else:
                raise RuntimeError(
                    _(
                        "The temporary output path is not a file: {path}"
                    ).format(
                        path=temporary_output
                    )
                )

        try:
            with temporary_output.open("wb") as output:
                for index in range(len(segments)):
                    self.__check_cancelled()

                    part_path = self.__part_path(
                        workspace,
                        index
                    )

                    with part_path.open("rb") as part:
                        while True:
                            self.__check_cancelled()

                            chunk = part.read(
                                1024 * 1024
                            )

                            if not chunk:
                                break

                            output.write(
                                chunk
                            )

                output.flush()
                os.fsync(
                    output.fileno()
                )

            final_size = temporary_output.stat().st_size

            if final_size != expected_size:
                raise RuntimeError(
                    _(
                        "Final file size is incorrect: "
                        "{actual_size} != {expected_size}"
                    ).format(
                        actual_size=final_size,
                        expected_size=expected_size
                    )
                )

            os.replace(
                temporary_output,
                final_path
            )

        except Exception:
            if temporary_output.is_file():
                temporary_output.unlink()

            raise

        shutil.rmtree(
            workspace
        )
