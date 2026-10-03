import json
import locale
import logging
import os
import sys
from pathlib import Path


APP_NAME = "Segment Downloader"
SETTINGS_FILE_NAME = "settings.json"
_LEGACY_SETTINGS_PATH = Path(__file__).with_name(
    SETTINGS_FILE_NAME
)
LOGGER = logging.getLogger(
    "SegmentDownloader.settings"
)


def get_app_directory():
    if sys.platform == "win32":
        base_path = os.environ.get(
            "APPDATA"
        )

        if base_path:
            config_directory = Path(base_path)

        else:
            config_directory = (
                Path.home()
                / "AppData"
                / "Roaming"
            )

    elif sys.platform == "darwin":
        config_directory = (
            Path.home()
            / "Library"
            / "Application Support"
        )

    else:
        base_path = os.environ.get(
            "XDG_CONFIG_HOME"
        )

        if base_path:
            config_directory = Path(base_path)

        else:
            config_directory = (
                Path.home()
                / ".config"
            )

    return (
        config_directory
        / APP_NAME
    )


def get_default_settings_path():
    return (
        get_app_directory()
        / SETTINGS_FILE_NAME
    )


def get_temporary_directory():
    return (
        get_app_directory()
        / "tmp"
    )


def get_default_output_directory():
    home_directory = Path.home()
    downloads_directory = (
        home_directory
        / "Downloads"
    )

    if downloads_directory.is_dir():
        return downloads_directory

    return home_directory


def get_default_language():
    try:
        locale_name = locale.getlocale()[0] or ""

    except ValueError:
        locale_name = ""

    normalized_locale = locale_name.lower()

    if (
        normalized_locale.startswith("pl")
        or normalized_locale.startswith("polish")
    ):
        return "pl"

    return "en"


DEFAULT_SETTINGS = {
    "url": (
        "https://edge1-vienna-sprintcdn.owphbf24.com/download/05/11945/"
        "p75mb60tn5t6_x/BLACK_TORCH_S01E07_Lektor_PL_mkv.mp4?"
        "t=jrdlTmN-b9ZgVixIShAkyRv4g5_SSNmPwNtKSpEDgbo&"
        "s=1790977439&e=10800&f=59727226&srv=1065&asn=5617&sp=4000"
    ),
    "file_name": "Test s01e01",
    "extension": ".mp4",
    "thread_count": "128",
    "segment_size_kb": "1024",
    "language": get_default_language(),
    "output_directory": str(
        get_default_output_directory()
    ),
    "window_x": "",
    "window_y": ""
}


class SettingsManager:
    def __init__(self, path=None):
        self.uses_default_path = path is None

        if path is None:
            path = get_default_settings_path()

        self.path = Path(path)

    def load(self):
        settings = DEFAULT_SETTINGS.copy()
        source_path = self.path

        if (
            self.uses_default_path
            and not source_path.exists()
            and _LEGACY_SETTINGS_PATH.exists()
        ):
            source_path = _LEGACY_SETTINGS_PATH

        try:
            with source_path.open(
                "r",
                encoding="utf-8"
            ) as file:
                saved_settings = json.load(file)

        except FileNotFoundError:
            LOGGER.info(
                "Settings file not found. Creating defaults at %s.",
                self.path
            )

            try:
                self.save(settings)

            except OSError as error:
                LOGGER.error(
                    "Failed to create the settings file (%s).",
                    type(error).__name__
                )

            return settings

        except json.JSONDecodeError:
            LOGGER.warning(
                "The settings file is invalid. "
                "Default values will be used: %s",
                source_path
            )

            return settings

        except OSError as error:
            LOGGER.error(
                "Failed to read settings from %s (%s).",
                source_path,
                type(error).__name__
            )

            return settings

        if not isinstance(saved_settings, dict):
            LOGGER.warning(
                "The settings file does not contain a JSON object. "
                "Default values will be used: %s",
                source_path
            )

            return settings

        for key, default_value in DEFAULT_SETTINGS.items():
            value = saved_settings.get(
                key,
                default_value
            )

            if value is None:
                value = default_value

            settings[key] = str(value)

        if source_path != self.path:
            LOGGER.info(
                "Migrating settings from %s to %s.",
                source_path,
                self.path
            )

            try:
                self.save(settings)

            except OSError as error:
                LOGGER.error(
                    "Failed to migrate settings (%s).",
                    type(error).__name__
                )

        return settings

    def save(self, settings):
        data = {}

        for key, default_value in DEFAULT_SETTINGS.items():
            value = settings.get(
                key,
                default_value
            )

            if value is None:
                value = default_value

            data[key] = str(value)

        temporary_path = self.path.with_name(
            self.path.name + ".tmp"
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with temporary_path.open(
            "w",
            encoding="utf-8",
            newline="\n"
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2
            )

            file.write("\n")

        temporary_path.replace(
            self.path
        )

        LOGGER.debug(
            "Settings saved to %s.",
            self.path
        )
