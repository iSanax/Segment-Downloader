import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from settings import get_app_directory


LOGGER_NAME = "SegmentDownloader"
LOG_DIRECTORY_NAME = "logs"
LOG_FILE_NAME = "application.log"
MAX_LOG_FILE_SIZE = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3


def get_log_file_path():
    return (
        get_app_directory()
        / LOG_DIRECTORY_NAME
        / LOG_FILE_NAME
    )


def configure_logging(log_directory=None):
    application_logger = logging.getLogger(
        LOGGER_NAME
    )

    if getattr(
        application_logger,
        "_threaded_download_configured",
        False
    ):
        return application_logger

    application_logger.setLevel(
        logging.INFO
    )

    application_logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    )

    try:
        if log_directory is None:
            log_file_path = get_log_file_path()

        else:
            log_file_path = (
                Path(log_directory)
                / LOG_FILE_NAME
            )

        log_file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        handler = RotatingFileHandler(
            log_file_path,
            maxBytes=MAX_LOG_FILE_SIZE,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=True
        )

    except OSError:
        handler = logging.StreamHandler()

    handler.setLevel(
        logging.INFO
    )

    handler.setFormatter(
        formatter
    )

    application_logger.addHandler(
        handler
    )

    application_logger._threaded_download_configured = True

    return application_logger


def get_logger(module_name):
    short_name = module_name.rsplit(
        ".",
        1
    )[-1]

    return logging.getLogger(
        f"{LOGGER_NAME}.{short_name}"
    )
