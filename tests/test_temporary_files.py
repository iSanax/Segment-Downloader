import tempfile
import unittest
from pathlib import Path

from temporaryFiles import TemporaryFilesManager


class TemporaryFilesManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(
            self.temporary_directory.cleanup
        )

        self.app_directory = (
            Path(self.temporary_directory.name)
            / "Segment Downloader"
        )
        self.temp_path = self.app_directory / "tmp"
        self.manager = TemporaryFilesManager(
            app_directory=self.app_directory,
            temporary_directory=self.temp_path
        )

    def test_size_is_calculated_recursively_and_clear_keeps_folder(self):
        nested_path = self.temp_path / "download-id"
        nested_path.mkdir(
            parents=True
        )
        (self.temp_path / "download.json").write_bytes(
            b"1234"
        )
        (nested_path / "segment.part").write_bytes(
            b"123456"
        )

        self.assertEqual(
            self.manager.calculate_size(),
            10
        )

        result = self.manager.clear()

        self.assertEqual(
            result,
            self.temp_path
        )
        self.assertTrue(
            self.temp_path.is_dir()
        )
        self.assertEqual(
            list(self.temp_path.iterdir()),
            []
        )
        self.assertEqual(
            self.manager.calculate_size(),
            0
        )

    def test_manager_rejects_a_directory_outside_app_tmp(self):
        manager = TemporaryFilesManager(
            app_directory=self.app_directory,
            temporary_directory=(
                Path(self.temporary_directory.name)
                / "other"
            )
        )

        with self.assertRaises(RuntimeError):
            manager.clear()


if __name__ == "__main__":
    unittest.main()
