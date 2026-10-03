import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from logger import get_logger
from settings import get_app_directory, get_temporary_directory


LOGGER = get_logger(__name__)


class TemporaryFilesManager:
    def __init__(
        self,
        app_directory=None,
        temporary_directory=None
    ):
        self.app_directory = Path(
            app_directory or get_app_directory()
        ).expanduser()

        self.path = Path(
            temporary_directory or get_temporary_directory()
        ).expanduser()

        self.__operation_lock = threading.RLock()

    def ensure(self):
        with self.__operation_lock:
            path = self.__validated_path()

            if path.exists() and not path.is_dir():
                raise RuntimeError(
                    "The temporary directory path is invalid."
                )

            path.mkdir(
                parents=True,
                exist_ok=True
            )

            return path

    def calculate_size(self):
        with self.__operation_lock:
            path = self.__validated_path()

            if not path.exists():
                return 0

            if not path.is_dir():
                raise RuntimeError(
                    "The temporary directory path is invalid."
                )

            total_size = 0
            directories = [path]

            while directories:
                current_directory = directories.pop()

                try:
                    with os.scandir(current_directory) as entries:
                        for entry in entries:
                            if entry.is_dir(follow_symlinks=False):
                                directories.append(
                                    Path(entry.path)
                                )

                            elif entry.is_file(follow_symlinks=False):
                                try:
                                    total_size += entry.stat(
                                        follow_symlinks=False
                                    ).st_size

                                except FileNotFoundError:
                                    pass

                except FileNotFoundError:
                    pass

            return total_size

    def clear(self):
        with self.__operation_lock:
            path = self.__validated_path()

            if path.exists():
                if not path.is_dir():
                    raise RuntimeError(
                        "The temporary directory path is invalid."
                    )

                shutil.rmtree(
                    path
                )

            path.mkdir(
                parents=True,
                exist_ok=True
            )

        LOGGER.info(
            "Temporary download files cleared: %s.",
            path
        )

        return path

    def open(self):
        path = self.ensure()

        if sys.platform == "win32":
            os.startfile(str(path))

        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        else:
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )

        LOGGER.info(
            "Temporary download directory opened: %s.",
            path
        )

        return path

    def __validated_path(self):
        resolved_app_directory = (
            self.app_directory
            .resolve()
        )

        expected_path = (
            resolved_app_directory
            / "tmp"
        )

        if self.path.is_symlink():
            raise RuntimeError(
                "The temporary directory path is invalid."
            )

        resolved_path = self.path.resolve()

        if resolved_path != expected_path:
            raise RuntimeError(
                "The temporary directory path is invalid."
            )

        return self.path
