import sys
import tkinter as tk
from pathlib import Path


if __package__ in {None, ""}:
    sys.path.insert(
        0,
        str(Path(__file__).resolve().parent.parent)
    )

from app.download_manager import DownloadManager
from app.logger import configure_logging, get_logger
from app.ui import DownloadApp


__all__ = ["DownloadApp", "DownloadManager", "main"]
LOGGER = get_logger(__name__)


def main():
    configure_logging()
    LOGGER.info("Application started.")

    try:
        root = tk.Tk()
        DownloadApp(root)
        root.mainloop()

    except Exception as error:
        LOGGER.error(
            "Unhandled application error (%s).",
            type(error).__name__
        )

        raise

    finally:
        LOGGER.info("Application stopped.")


if __name__ == "__main__":
    main()
