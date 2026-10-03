import hashlib
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import downloadManager
import requests
from downloadManager import (
    DownloadCancelled,
    DownloadManager,
    RemoteFileInfo
)


TEST_DATA = bytes(range(256)) * 32


class DownloadRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    data = TEST_DATA
    supports_ranges = True
    transient_failures = 0
    transient_status = 503
    etag = '"test-v1"'
    last_modified = "Wed, 01 Jan 2025 00:00:00 GMT"

    def handle(self):
        try:
            super().handle()

        except (ConnectionResetError, BrokenPipeError):
            pass

    def do_HEAD(self):
        self.send_response(200)
        self.__send_common_headers(
            len(self.data)
        )
        self.end_headers()

    def do_GET(self):
        range_header = self.headers.get("Range")

        if (
            range_header
            and range_header != "bytes=0-0"
            and type(self).transient_failures > 0
        ):
            type(self).transient_failures -= 1
            self.send_response(
                self.transient_status
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if range_header and self.supports_ranges:
            start_text, end_text = (
                range_header.removeprefix("bytes=").split("-", 1)
            )
            start = int(start_text)
            end = min(int(end_text), len(self.data) - 1)
            body = self.data[start:end + 1]

            self.send_response(206)
            self.__send_common_headers(
                len(body)
            )
            self.send_header(
                "Content-Range",
                f"bytes {start}-{end}/{len(self.data)}"
            )
            self.end_headers()
            self.__write_body(body)
            return

        self.send_response(200)
        self.__send_common_headers(
            len(self.data)
        )
        self.end_headers()
        self.__write_body(self.data)

    def __send_common_headers(self, content_length):
        self.send_header(
            "Content-Length",
            str(content_length)
        )
        self.send_header("ETag", self.etag)
        self.send_header("Last-Modified", self.last_modified)
        self.send_header(
            "Accept-Ranges",
            "bytes" if self.supports_ranges else "none"
        )

    def __write_body(self, body):
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, format, *args):
        pass


@contextmanager
def download_server(
    supports_ranges=True,
    transient_failures=0,
    transient_status=503
):
    class Handler(DownloadRequestHandler):
        pass

    Handler.supports_ranges = supports_ranges
    Handler.transient_failures = transient_failures
    Handler.transient_status = transient_status

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        Handler
    )
    server.daemon_threads = True

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True
    )
    thread.start()

    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/file.bin"

    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class DownloadManagerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(
            self.temporary_directory.cleanup
        )

        self.root = Path(
            self.temporary_directory.name
        )
        self.app_directory = self.root / "app"
        self.output_directory = self.root / "output"

        self.path_patches = (
            patch(
                "downloadManager.get_app_directory",
                return_value=self.app_directory
            ),
            patch(
                "downloadManager.get_temporary_directory",
                return_value=self.app_directory / "tmp"
            )
        )

        for path_patch in self.path_patches:
            path_patch.start()
            self.addCleanup(
                path_patch.stop
            )

    def test_cancelled_download_resumes_and_keeps_existing_output(self):
        output_path = self.output_directory / "result.bin"
        self.output_directory.mkdir(
            parents=True
        )
        output_path.write_bytes(
            b"existing file"
        )

        first_activities = []
        manager = None

        def activity_callback(message):
            first_activities.append(message)

            if message.startswith("Segment 1/8 downloaded"):
                manager.cancel()

        manager = DownloadManager(
            activity_callback=activity_callback
        )

        with download_server() as url:
            with self.assertRaises(DownloadCancelled):
                manager.run(
                    path=self.output_directory,
                    segment_size_kb=1,
                    thread_count=1,
                    file_name="result",
                    file_extension=".bin",
                    url=url
                )

            self.assertEqual(
                output_path.read_bytes(),
                b"existing file"
            )

            second_activities = []
            resumed_manager = DownloadManager(
                activity_callback=second_activities.append
            )

            final_path = resumed_manager.run(
                path=self.output_directory,
                segment_size_kb=1,
                thread_count=2,
                file_name="result",
                file_extension=".bin",
                url=url
            )

        self.assertEqual(
            Path(final_path).read_bytes(),
            TEST_DATA
        )
        self.assertEqual(
            Path(final_path).name,
            "result (1).bin"
        )
        self.assertEqual(
            output_path.read_bytes(),
            b"existing file"
        )
        self.assertIn(
            "Found previous partial download. Resuming...",
            second_activities
        )
        self.assertTrue(
            any(
                "was already downloaded" in message
                for message in second_activities
            )
        )

    def test_existing_output_gets_next_available_windows_style_name(self):
        self.output_directory.mkdir(
            parents=True
        )
        (self.output_directory / "duplicate.bin").write_bytes(
            b"existing"
        )
        (self.output_directory / "duplicate (1).bin").write_bytes(
            b"existing copy"
        )
        activities = []
        manager = DownloadManager(
            activity_callback=activities.append
        )

        with download_server() as url:
            final_path = manager.run(
                path=self.output_directory,
                segment_size_kb=8,
                thread_count=1,
                file_name="duplicate",
                file_extension=".bin",
                url=url
            )

        self.assertEqual(
            Path(final_path).name,
            "duplicate (2).bin"
        )
        self.assertEqual(
            Path(final_path).read_bytes(),
            TEST_DATA
        )
        self.assertTrue(
            any(
                "Saving as duplicate (2).bin" in message
                for message in activities
            )
        )

    def test_different_urls_use_different_workspace_folders(self):
        manager = DownloadManager()
        temporary_directory = self.app_directory / "tmp"
        temporary_directory.mkdir(
            parents=True
        )
        final_path = self.output_directory / "same-name.bin"
        remote_info = RemoteFileInfo(
            size=1024,
            supports_ranges=True
        )
        prepare_workspace = getattr(
            manager,
            "_DownloadManager__prepare_download_workspace"
        )

        first_workspace = prepare_workspace(
            temporary_directory=temporary_directory,
            final_path=final_path,
            full_file_name="same-name.bin",
            segment_size_bytes=1024,
            mode="segmented",
            url="https://edge.example/download/episode-07.mp4?t=first",
            remote_info=remote_info
        )

        second_workspace = prepare_workspace(
            temporary_directory=temporary_directory,
            final_path=final_path,
            full_file_name="same-name.bin",
            segment_size_bytes=1024,
            mode="segmented",
            url="https://edge.example/download/episode-08.mp4?t=second",
            remote_info=remote_info
        )

        refreshed_first_workspace = prepare_workspace(
            temporary_directory=temporary_directory,
            final_path=final_path,
            full_file_name="same-name.bin",
            segment_size_bytes=1024,
            mode="segmented",
            url="https://edge.example/download/episode-07.mp4?t=refreshed",
            remote_info=remote_info
        )

        self.assertNotEqual(
            first_workspace,
            second_workspace
        )
        self.assertEqual(
            first_workspace,
            refreshed_first_workspace
        )

    def test_legacy_workspace_is_migrated_without_losing_parts(self):
        manager = DownloadManager()
        temporary_directory = self.app_directory / "tmp"
        temporary_directory.mkdir(
            parents=True
        )
        final_path = self.output_directory / "legacy.bin"
        url = "https://edge.example/download/legacy.bin?t=old"
        legacy_name = hashlib.sha256(
            str(final_path).casefold().encode("utf-8")
        ).hexdigest()[:24]
        legacy_workspace = temporary_directory / legacy_name
        legacy_workspace.mkdir()
        legacy_manifest = {
            "version": 1,
            "url": url,
            "final_path": str(final_path),
            "file_name": "legacy.bin",
            "file_size": 1024,
            "segment_size": 1024,
            "mode": "segmented",
            "etag": "",
            "last_modified": ""
        }
        (legacy_workspace / "download.json").write_text(
            json.dumps(legacy_manifest),
            encoding="utf-8"
        )
        (legacy_workspace / "segment-00000000.part").write_bytes(
            b"partial data"
        )
        prepare_workspace = getattr(
            manager,
            "_DownloadManager__prepare_download_workspace"
        )

        migrated_workspace = prepare_workspace(
            temporary_directory=temporary_directory,
            final_path=final_path,
            full_file_name="legacy.bin",
            segment_size_bytes=1024,
            mode="segmented",
            url=url,
            remote_info=RemoteFileInfo(
                size=1024,
                supports_ranges=True
            )
        )

        self.assertNotEqual(
            migrated_workspace,
            legacy_workspace
        )
        self.assertFalse(
            legacy_workspace.exists()
        )
        self.assertEqual(
            (
                migrated_workspace
                / "segment-00000000.part"
            ).read_bytes(),
            b"partial data"
        )

    def test_server_without_ranges_uses_single_connection(self):
        activities = []
        manager = DownloadManager(
            activity_callback=activities.append
        )

        with download_server(supports_ranges=False) as url:
            final_path = manager.run(
                path=self.output_directory,
                segment_size_kb=1,
                thread_count=4,
                file_name="single",
                file_extension=".bin",
                url=url
            )

        self.assertEqual(
            Path(final_path).read_bytes(),
            TEST_DATA
        )
        self.assertTrue(
            any(
                "does not support segmented downloads" in message
                for message in activities
            )
        )

    def test_transient_http_error_is_retried(self):
        activities = []
        manager = DownloadManager(
            activity_callback=activities.append
        )

        with patch.object(
            downloadManager,
            "RETRY_DELAYS",
            (0, 0, 0, 0)
        ):
            with download_server(transient_failures=1) as url:
                final_path = manager.run(
                    path=self.output_directory,
                    segment_size_kb=8,
                    thread_count=1,
                    file_name="retry",
                    file_extension=".bin",
                    url=url
                )

        self.assertEqual(
            Path(final_path).read_bytes(),
            TEST_DATA
        )
        self.assertTrue(
            any(
                "Retrying in 0 s" in message
                for message in activities
            )
        )

    def test_http_403_keeps_retrying_beyond_old_limit(self):
        activities = []
        manager = DownloadManager(
            activity_callback=activities.append
        )

        with patch.object(
            downloadManager,
            "RETRY_DELAYS",
            (0, 0, 0, 0)
        ):
            with download_server(
                transient_failures=7,
                transient_status=403
            ) as url:
                final_path = manager.run(
                    path=self.output_directory,
                    segment_size_kb=8,
                    thread_count=1,
                    file_name="forbidden-retry",
                    file_extension=".bin",
                    url=url
                )

        self.assertEqual(
            Path(final_path).read_bytes(),
            TEST_DATA
        )
        self.assertTrue(
            any(
                "HTTP 403" in message
                for message in activities
            )
        )
        self.assertGreaterEqual(
            sum(
                "HTTP 403" in message
                for message in activities
            ),
            7
        )

    def test_connection_error_is_retried(self):
        activities = []
        manager = DownloadManager(
            activity_callback=activities.append
        )
        method_name = "_DownloadManager__download_segment_attempt"
        original_attempt = getattr(
            manager,
            method_name
        )
        attempt_count = 0

        def flaky_attempt(**kwargs):
            nonlocal attempt_count
            attempt_count += 1

            if attempt_count == 1:
                raise requests.ConnectionError(
                    "simulated disconnect"
                )

            return original_attempt(**kwargs)

        with patch.object(
            downloadManager,
            "RETRY_DELAYS",
            (0, 0, 0, 0)
        ):
            with patch.object(
                manager,
                method_name,
                side_effect=flaky_attempt
            ):
                with download_server() as url:
                    final_path = manager.run(
                        path=self.output_directory,
                        segment_size_kb=8,
                        thread_count=1,
                        file_name="connection-retry",
                        file_extension=".bin",
                        url=url
                    )

        self.assertEqual(
            Path(final_path).read_bytes(),
            TEST_DATA
        )
        self.assertGreaterEqual(
            attempt_count,
            2
        )
        self.assertTrue(
            any(
                "ConnectionError" in message
                for message in activities
            )
        )


if __name__ == "__main__":
    unittest.main()
