import tkinter as tk

from downloadManager import DownloadManager
from logger import configure_logging, get_logger
from ui import DownloadApp


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
