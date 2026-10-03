import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from logger import get_logger
from settings import get_app_directory, get_temporary_directory
from translator import translate as _


LOGGER = get_logger(__name__)


class DownloadManager:
    def __init__(
        self,
        progress_callback=None,
        status_callback=None,
        activity_callback=None
    ):
        self.headers = {
            "User-Agent": "Mozilla/5.0"
        }

        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.activity_callback = activity_callback

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

    def run(
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

        full_file_name = file_name + file_extension
        output_directory = Path(path).expanduser().resolve()

        LOGGER.info(
            "Download started: file=%s, threads=%d, "
            "segment_size_kb=%d, output=%s.",
            full_file_name,
            thread_count,
            segment_size_kb,
            output_directory
        )

        temp_directory = self.__prepare_temporary_directory(
            output_directory
        )

        os.makedirs(
            output_directory,
            exist_ok=True
        )

        temp_path = os.path.join(
            temp_directory,
            file_name
        )

        os.makedirs(
            temp_path,
            exist_ok=True
        )

        self.__set_status(
            _("Checking file...")
        )

        file_size = self.__get_total_file_size(
            url
        )

        segment_size_bytes = (
            segment_size_kb * 1024
        )

        segments = self.__create_segments(
            file_size,
            segment_size_bytes
        )

        segment_count = len(segments)

        LOGGER.info(
            "Remote file size is %d bytes; %d segments will be used.",
            file_size,
            segment_count
        )

        final_path = os.path.join(
            output_directory,
            full_file_name
        )

        self.__set_status(
            _("Downloading - {segment_count} segments").format(
                segment_count=segment_count
            )
        )

        self.__download_all_segments(
            url=url,
            segments=segments,
            temp_path=temp_path,
            full_file_name=full_file_name,
            thread_count=thread_count
        )

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
            temp_path=temp_path,
            full_file_name=full_file_name,
            segment_count=segment_count,
            final_path=final_path
        )

        final_size = os.path.getsize(
            final_path
        )

        if final_size != file_size:
            raise RuntimeError(
                _(
                    "Final file size is incorrect: "
                    "{actual_size} != {expected_size}"
                ).format(
                    actual_size=final_size,
                    expected_size=file_size
                )
            )

        self.__set_progress(
            file_size,
            file_size
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

        return final_path

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

    def __prepare_temporary_directory(
        self,
        output_directory
    ):
        app_directory = (
            get_app_directory()
            .expanduser()
            .resolve()
        )

        configured_temp_directory = (
            get_temporary_directory()
            .expanduser()
        )

        expected_temp_directory = (
            app_directory
            / "tmp"
        )

        resolved_temp_directory = (
            configured_temp_directory
            .resolve()
        )

        if (
            configured_temp_directory.is_symlink()
            or resolved_temp_directory
            != expected_temp_directory
        ):
            raise RuntimeError(
                _("The temporary directory path is invalid.")
            )

        if (
            output_directory == resolved_temp_directory
            or resolved_temp_directory
            in output_directory.parents
        ):
            raise RuntimeError(
                _(
                    "The output directory cannot be located "
                    "inside the temporary directory."
                )
            )

        self.__set_status(
            _("Clearing temporary files...")
        )

        LOGGER.info(
            "Clearing temporary directory: %s.",
            configured_temp_directory
        )

        if configured_temp_directory.exists():
            if configured_temp_directory.is_dir():
                shutil.rmtree(
                    configured_temp_directory
                )

            else:
                configured_temp_directory.unlink()

        configured_temp_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        LOGGER.info(
            "Temporary directory is ready."
        )

        return str(configured_temp_directory)

    def __get_total_file_size(
        self,
        url
    ):
        try:
            response = requests.head(
                url,
                headers=self.headers,
                allow_redirects=True,
                timeout=20
            )

            if response.ok:
                content_length = (
                    response.headers.get(
                        "Content-Length"
                    )
                )

                if content_length is not None:
                    response.close()

                    return int(
                        content_length
                    )

            response.close()

        except requests.RequestException as error:
            LOGGER.warning(
                "HEAD request failed; using a ranged GET request "
                "as fallback (%s).",
                type(error).__name__
            )

        headers = self.headers.copy()

        headers["Range"] = "bytes=0-0"

        response = requests.get(
            url,
            headers=headers,
            stream=True,
            allow_redirects=True,
            timeout=20
        )

        response.raise_for_status()

        content_range = (
            response.headers.get(
                "Content-Range"
            )
        )

        if content_range:
            total_size = (
                content_range
                .split("/")[-1]
            )

            response.close()

            if total_size != "*":
                return int(total_size)

        content_length = (
            response.headers.get(
                "Content-Length"
            )
        )

        response.close()

        if content_length is not None:
            return int(content_length)

        raise RuntimeError(
            _("Could not determine the file size.")
        )

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
                start
                + segment_size_bytes
                - 1,
                total_size - 1
            )

            segments.append(
                (start, end)
            )

        return segments

    def __download_segment(
        self,
        index,
        segment_count,
        start,
        end,
        url,
        temp_path,
        full_file_name,
        progress_callback,
        retries=5
    ):
        part_path = os.path.join(
            temp_path,
            f"{full_file_name}.part{index}"
        )

        expected_size = end - start + 1

        # =====================================================
        # SPRAWDZENIE ISTNIEJĄCEGO SEGMENTU
        # =====================================================

        if os.path.exists(part_path):
            current_size = os.path.getsize(part_path)

            # Segment jest już kompletny.
            if current_size == expected_size:
                progress_callback(current_size)

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

            # Plik jest większy niż powinien.
            # Nie możemy mu ufać -> pobieramy od początku.
            if current_size > expected_size:
                os.remove(part_path)
                current_size = 0

            # Istniejąca część jest poprawna rozmiarowo.
            else:
                progress_callback(current_size)

        else:
            current_size = 0

        # =====================================================
        # RETRY
        # =====================================================

        for attempt in range(1, retries + 1):
            try:
                if os.path.exists(part_path):
                    current_size = os.path.getsize(part_path)
                else:
                    current_size = 0

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

                if current_size > expected_size:
                    progress_callback(-current_size)

                    os.remove(part_path)

                    current_size = 0


                resume_start = start + current_size

                headers = self.headers.copy()

                headers["Range"] = (
                    f"bytes={resume_start}-{end}"
                )

                self.__set_activity(
                    _(
                        "Segment {index}/{segment_count}: "
                        "request attempt {attempt}/{retries}..."
                    ).format(
                        index=index + 1,
                        segment_count=segment_count,
                        attempt=attempt,
                        retries=retries
                    )
                )

                response = requests.get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=30,
                    allow_redirects=True
                )

                if response.status_code != 206:
                    status_code = response.status_code
                    response.close()

                    raise RuntimeError(
                        _(
                            "The server rejected the range request. "
                            "HTTP {status_code}"
                        ).format(
                            status_code=status_code
                        )
                    )

                content_range = response.headers.get(
                    "Content-Range"
                )

                if content_range is None:
                    response.close()

                    raise RuntimeError(
                        _(
                            "The server returned HTTP 206 without "
                            "a Content-Range header."
                        )
                    )

                expected_content_range = (
                    f"bytes {resume_start}-{end}/"
                )

                if not content_range.startswith(
                    expected_content_range
                ):
                    response.close()

                    raise RuntimeError(
                        _(
                            "Segment {index}: invalid Content-Range. "
                            "Expected {start}-{end}, received: {received}"
                        ).format(
                            index=index,
                            start=resume_start,
                            end=end,
                            received=content_range
                        )
                    )

                file_mode = "ab" if current_size > 0 else "wb"

                with open(part_path, file_mode) as file:

                    for chunk in response.iter_content(
                        chunk_size=256 * 1024
                    ):
                        if not chunk:
                            continue

                        current_file_size = os.path.getsize(
                            part_path
                        )

                        remaining = (
                            expected_size
                            - current_file_size
                        )

                        if remaining <= 0:
                            break

                        if len(chunk) > remaining:
                            chunk = chunk[:remaining]

                        file.write(chunk)

                        chunk_size = len(chunk)

                        progress_callback(chunk_size)

                response.close()

                actual_size = os.path.getsize(
                    part_path
                )

                if actual_size == expected_size:
                    self.__set_activity(
                        _(
                            "Segment {index}/{segment_count} downloaded."
                        ).format(
                            index=index + 1,
                            segment_count=segment_count
                        )
                    )

                    return

                if actual_size > expected_size:
                    raise RuntimeError(
                        _(
                            "Segment {index}: expected {expected_size} "
                            "bytes, received {actual_size}."
                        ).format(
                            index=index,
                            expected_size=expected_size,
                            actual_size=actual_size
                        )
                    )

                raise RuntimeError(
                    _(
                        "Segment {index}: incomplete response. "
                        "Downloaded {actual_size} / {expected_size} bytes."
                    ).format(
                        index=index,
                        actual_size=actual_size,
                        expected_size=expected_size
                    )
                )

            except Exception as error:
                error_description = str(error).strip()

                if (
                    isinstance(error, requests.RequestException)
                    or not error_description
                ):
                    error_description = type(error).__name__

                error_description = (
                    error_description
                    .replace("\r", " ")
                    .replace("\n", " ")
                )

                if attempt == retries:
                    self.__set_activity(
                        _(
                            "Segment {index}/{segment_count} failed after "
                            "{retries} attempts ({error})."
                        ).format(
                            index=index + 1,
                            segment_count=segment_count,
                            retries=retries,
                            error=error_description
                        )
                    )

                    LOGGER.error(
                        "Segment %d failed after %d attempts (%s).",
                        index,
                        retries,
                        type(error).__name__
                    )

                    raise

                self.__set_activity(
                    _(
                        "Segment {index}/{segment_count}: attempt "
                        "{attempt}/{retries} failed ({error}). Retrying..."
                    ).format(
                        index=index + 1,
                        segment_count=segment_count,
                        attempt=attempt,
                        retries=retries,
                        error=error_description
                    )
                )

                LOGGER.warning(
                    "Segment %d failed on attempt %d/%d (%s).",
                    index,
                    attempt,
                    retries,
                    type(error).__name__
                )


    def __download_all_segments(
        self,
        url,
        segments,
        temp_path,
        full_file_name,
        thread_count
    ):
        total_size = sum(
            end - start + 1
            for start, end in segments
        )

        downloaded_bytes = 0
        segment_count = len(segments)

        progress_lock = threading.Lock()

        def update_progress(
            byte_count
        ):
            nonlocal downloaded_bytes

            with progress_lock:
                downloaded_bytes += (
                    byte_count
                )

                downloaded_bytes = max(
                    0,
                    min(
                        downloaded_bytes,
                        total_size
                    )
                )

                self.__set_progress(
                    downloaded_bytes,
                    total_size
                )

        self.__set_progress(
            0,
            total_size
        )

        with ThreadPoolExecutor(
            max_workers=thread_count
        ) as executor:

            futures = []

            for index, (
                start,
                end
            ) in enumerate(segments):

                future = executor.submit(
                    self.__download_segment,
                    index,
                    segment_count,
                    start,
                    end,
                    url,
                    temp_path,
                    full_file_name,
                    update_progress
                )

                futures.append(
                    future
                )

            for future in as_completed(
                futures
            ):
                future.result()

    def __merge_segments(
        self,
        temp_path,
        full_file_name,
        segment_count,
        final_path
    ):
        total_size = 0

        for index in range(
            segment_count
        ):
            part_path = os.path.join(
                temp_path,
                f"{full_file_name}.part{index}"
            )

            if not os.path.exists(
                part_path
            ):
                raise FileNotFoundError(
                    _("Missing segment: {path}").format(
                        path=part_path
                    )
                )

            total_size += os.path.getsize(
                part_path
            )

        with open(
            final_path,
            "wb"
        ) as output:

            for index in range(
                segment_count
            ):
                part_path = os.path.join(
                    temp_path,
                    f"{full_file_name}.part{index}"
                )

                with open(
                    part_path,
                    "rb"
                ) as part:

                    while True:
                        chunk = part.read(
                            1024 * 1024
                        )

                        if not chunk:
                            break

                        output.write(
                            chunk
                        )

        shutil.rmtree(
            temp_path
        )
