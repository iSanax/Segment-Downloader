import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from downloadManager import DownloadManager
from logger import get_logger
from settings import SettingsManager
from translator import set_language, translate as _


LOGGER = get_logger(__name__)


# ==========================================================
# GUI
# ==========================================================

class DownloadApp:
    def __init__(self, root):
        self.root = root

        self.root.geometry(
            "720x590"
        )

        self.root.minsize(
            650,
            560
        )

        self.downloading = False

        self.settings_manager = SettingsManager()
        saved_settings = self.settings_manager.load()
        self.__settings_save_job = None

        selected_language = set_language(
            saved_settings["language"]
        )

        LOGGER.info(
            "Settings loaded from %s.",
            self.settings_manager.path
        )

        self.url_var = tk.StringVar(
            value=saved_settings["url"]
        )

        self.file_name_var = tk.StringVar(
            value=saved_settings["file_name"]
        )

        self.extension_var = tk.StringVar(
            value=saved_settings["extension"]
        )

        self.thread_var = tk.StringVar(
            value=saved_settings["thread_count"]
        )

        self.segment_var = tk.StringVar(
            value=saved_settings["segment_size_kb"]
        )

        self.output_directory_var = tk.StringVar(
            value=saved_settings["output_directory"]
        )

        self.language_var = tk.StringVar(
            value=selected_language
        )

        self.status_var = tk.StringVar(
            value=_("Ready")
        )

        self.progress_text_var = tk.StringVar(
            value="0 MB / 0 MB"
        )

        self.percent_var = tk.StringVar(
            value="0.00%"
        )

        self.__input_variables = {
            "url": self.url_var,
            "file_name": self.file_name_var,
            "extension": self.extension_var,
            "thread_count": self.thread_var,
            "segment_size_kb": self.segment_var,
            "language": self.language_var,
            "output_directory": self.output_directory_var
        }

        self.__create_ui()
        self.__watch_settings()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.__close
        )

    def __create_ui(self):
        self.root.title(
            _("Segment Downloader")
        )

        main = ttk.Frame(
            self.root,
            padding=25
        )

        main.pack(
            fill="both",
            expand=True
        )

        header = ttk.Frame(
            main
        )

        header.pack(
            fill="x",
            pady=(0, 20)
        )

        title = ttk.Label(
            header,
            text=_("Segment Downloader"),
            font=(
                "Segoe UI",
                20,
                "bold"
            )
        )

        title.pack(
            side="left"
        )

        self.language_selector = ttk.Combobox(
            header,
            textvariable=self.language_var,
            values=("en", "pl"),
            state=(
                "disabled"
                if self.downloading
                else "readonly"
            ),
            width=5
        )

        self.language_selector.pack(
            side="right"
        )

        self.language_selector.bind(
            "<<ComboboxSelected>>",
            self.__change_language
        )

        ttk.Label(
            header,
            text=_("Language:")
        ).pack(
            side="right",
            padx=(0, 8)
        )

        # URL
        ttk.Label(
            main,
            text=_("File URL:")
        ).pack(
            anchor="w"
        )

        self.url_entry = ttk.Entry(
            main,
            textvariable=self.url_var
        )

        self.url_entry.pack(
            fill="x",
            pady=(5, 15),
            ipady=5
        )

        # Nazwa
        ttk.Label(
            main,
            text=_("File name:")
        ).pack(
            anchor="w"
        )

        self.name_entry = ttk.Entry(
            main,
            textvariable=self.file_name_var
        )

        self.name_entry.pack(
            fill="x",
            pady=(5, 15),
            ipady=5
        )

        # Opcje
        options = ttk.Frame(
            main
        )

        options.pack(
            fill="x",
            pady=(0, 20)
        )

        options.columnconfigure(
            0,
            weight=1
        )

        options.columnconfigure(
            1,
            weight=1
        )

        options.columnconfigure(
            2,
            weight=1
        )

        # Rozszerzenie
        extension_frame = ttk.Frame(
            options
        )

        extension_frame.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 10)
        )

        ttk.Label(
            extension_frame,
            text=_("Extension:")
        ).pack(
            anchor="w"
        )

        ttk.Entry(
            extension_frame,
            textvariable=self.extension_var
        ).pack(
            fill="x",
            pady=(5, 0),
            ipady=4
        )

        # Wątki
        thread_frame = ttk.Frame(
            options
        )

        thread_frame.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=10
        )

        ttk.Label(
            thread_frame,
            text=_("Thread count:")
        ).pack(
            anchor="w"
        )

        ttk.Entry(
            thread_frame,
            textvariable=self.thread_var
        ).pack(
            fill="x",
            pady=(5, 0),
            ipady=4
        )

        # Segment
        segment_frame = ttk.Frame(
            options
        )

        segment_frame.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(10, 0)
        )

        ttk.Label(
            segment_frame,
            text=_("Segment size (KB):")
        ).pack(
            anchor="w"
        )

        ttk.Entry(
            segment_frame,
            textvariable=self.segment_var
        ).pack(
            fill="x",
            pady=(5, 0),
            ipady=4
        )

        # Folder docelowy
        ttk.Label(
            main,
            text=_("Output directory:")
        ).pack(
            anchor="w"
        )

        output_frame = ttk.Frame(
            main
        )

        output_frame.pack(
            fill="x",
            pady=(5, 15)
        )

        ttk.Entry(
            output_frame,
            textvariable=self.output_directory_var,
            state="readonly"
        ).pack(
            side="left",
            fill="x",
            expand=True,
            ipady=5
        )

        ttk.Button(
            output_frame,
            text=_("BROWSE..."),
            command=self.__choose_output_directory
        ).pack(
            side="right",
            padx=(10, 0),
            ipady=5
        )

        # Przycisk
        self.download_button = ttk.Button(
            main,
            text=_("DOWNLOAD"),
            command=self.start_download
        )

        self.download_button.pack(
            fill="x",
            ipady=8,
            pady=(0, 25)
        )

        # Status
        ttk.Label(
            main,
            text=_("Status:")
        ).pack(
            anchor="w"
        )

        ttk.Label(
            main,
            textvariable=self.status_var,
            font=(
                "Segoe UI",
                10,
                "bold"
            )
        ).pack(
            anchor="w",
            pady=(5, 15)
        )

        # Pasek
        self.progress = ttk.Progressbar(
            main,
            orient="horizontal",
            mode="determinate",
            maximum=100
        )

        self.progress.pack(
            fill="x",
            ipady=4
        )

        progress_info = ttk.Frame(
            main
        )

        progress_info.pack(
            fill="x",
            pady=(8, 0)
        )

        ttk.Label(
            progress_info,
            textvariable=self.progress_text_var
        ).pack(
            side="left"
        )

        ttk.Label(
            progress_info,
            textvariable=self.percent_var,
            font=(
                "Segoe UI",
                10,
                "bold"
            )
        ).pack(
            side="right"
        )

    def __change_language(self, event=None):
        selected_language = set_language(
            self.language_var.get()
        )

        if self.language_var.get() != selected_language:
            self.language_var.set(
                selected_language
            )

        if not self.downloading:
            self.status_var.set(
                _("Ready")
            )

        for widget in self.root.winfo_children():
            widget.destroy()

        self.__create_ui()

        LOGGER.info(
            "Interface language changed to %s.",
            selected_language
        )

    def __choose_output_directory(self):
        selected_directory = filedialog.askdirectory(
            parent=self.root,
            title=_("Select output directory"),
            initialdir=self.output_directory_var.get()
        )

        if selected_directory:
            self.output_directory_var.set(
                selected_directory
            )

            LOGGER.info(
                "Output directory selected: %s.",
                selected_directory
            )

    def __watch_settings(self):
        for variable in self.__input_variables.values():
            variable.trace_add(
                "write",
                self.__schedule_settings_save
            )

    def __schedule_settings_save(self, *args):
        if self.__settings_save_job is not None:
            self.root.after_cancel(
                self.__settings_save_job
            )

        self.__settings_save_job = self.root.after(
            400,
            self.__save_settings
        )

    def __save_settings(self):
        self.__settings_save_job = None

        settings = {
            key: variable.get()
            for key, variable
            in self.__input_variables.items()
        }

        try:
            self.settings_manager.save(
                settings
            )

        except OSError as error:
            LOGGER.error(
                "Failed to save settings (%s).",
                type(error).__name__
            )

    def __close(self):
        if self.__settings_save_job is not None:
            self.root.after_cancel(
                self.__settings_save_job
            )

        self.__save_settings()

        LOGGER.info(
            "Application window closed."
        )

        self.root.destroy()

    def start_download(self):
        if self.downloading:
            return

        url = self.url_var.get().strip()

        file_name = (
            self.file_name_var
            .get()
            .strip()
        )

        extension = (
            self.extension_var
            .get()
            .strip()
        )

        output_directory = (
            self.output_directory_var
            .get()
            .strip()
        )

        if not url:
            messagebox.showerror(
                _("Error"),
                _("Enter the file URL.")
            )

            return

        if not file_name:
            messagebox.showerror(
                _("Error"),
                _("Enter the file name.")
            )

            return

        if not extension:
            messagebox.showerror(
                _("Error"),
                _("Enter the file extension.")
            )

            return

        if not output_directory:
            messagebox.showerror(
                _("Error"),
                _("Select an output directory.")
            )

            return

        if (
            file_name in {".", ".."}
            or "/" in file_name + extension
            or "\\" in file_name + extension
        ):
            messagebox.showerror(
                _("Error"),
                _(
                    "The file name and extension cannot contain "
                    "path separators."
                )
            )

            return

        if not extension.startswith("."):
            extension = "." + extension

            self.extension_var.set(
                extension
            )

        try:
            thread_count = int(
                self.thread_var.get()
            )

            if thread_count <= 0:
                raise ValueError

        except ValueError:
            messagebox.showerror(
                _("Error"),
                _(
                    "The thread count must be an integer "
                    "greater than 0."
                )
            )

            return

        try:
            segment_size = int(
                self.segment_var.get()
            )

            if segment_size <= 0:
                raise ValueError

        except ValueError:
            messagebox.showerror(
                _("Error"),
                _(
                    "The segment size must be an integer "
                    "greater than 0."
                )
            )

            return

        self.downloading = True

        self.download_button.config(
            state="disabled"
        )

        self.language_selector.config(
            state="disabled"
        )

        self.progress["value"] = 0

        self.percent_var.set(
            "0.00%"
        )

        self.progress_text_var.set(
            "0 MB / 0 MB"
        )

        self.status_var.set(
            _("Starting...")
        )

        LOGGER.info(
            "Download queued: file=%s%s, threads=%d, "
            "segment_size_kb=%d, output=%s.",
            file_name,
            extension,
            thread_count,
            segment_size,
            output_directory
        )

        thread = threading.Thread(
            target=self.__download_worker,
            args=(
                url,
                file_name,
                extension,
                thread_count,
                segment_size,
                output_directory
            ),
            daemon=True
        )

        thread.start()

    def __download_worker(
        self,
        url,
        file_name,
        extension,
        thread_count,
        segment_size,
        output_directory
    ):
        try:
            manager = DownloadManager(
                progress_callback=(
                    self.__progress_callback
                ),
                status_callback=(
                    self.__status_callback
                )
            )

            final_path = manager.run(
                path=output_directory,
                segment_size_kb=segment_size,
                thread_count=thread_count,
                file_name=file_name,
                file_extension=extension,
                url=url
            )

            self.root.after(
                0,
                self.__download_finished,
                final_path
            )

        except Exception as error:
            LOGGER.error(
                "Download failed: file=%s%s, error_type=%s.",
                file_name,
                extension,
                type(error).__name__
            )

            self.root.after(
                0,
                self.__download_error,
                str(error)
            )

    def __progress_callback(
        self,
        current,
        total,
        percent
    ):
        self.root.after(
            0,
            self.__update_progress,
            current,
            total,
            percent
        )

    def __update_progress(
        self,
        current,
        total,
        percent
    ):
        percent_value = (
            percent * 100
        )

        self.progress["value"] = (
            percent_value
        )

        self.percent_var.set(
            f"{percent_value:.2f}%"
        )

        current_mb = (
            current / 1024 / 1024
        )

        total_mb = (
            total / 1024 / 1024
        )

        if total_mb >= 1024:
            current_gb = (
                current_mb / 1024
            )

            total_gb = (
                total_mb / 1024
            )

            text = (
                f"{current_gb:.2f} GB "
                f"/ {total_gb:.2f} GB"
            )

        else:
            text = (
                f"{current_mb:.1f} MB "
                f"/ {total_mb:.1f} MB"
            )

        self.progress_text_var.set(
            text
        )

    def __status_callback(
        self,
        text
    ):
        self.root.after(
            0,
            self.status_var.set,
            text
        )

    def __download_finished(
        self,
        final_path
    ):
        self.downloading = False

        self.download_button.config(
            state="normal"
        )

        self.language_selector.config(
            state="readonly"
        )

        self.progress["value"] = 100

        self.percent_var.set(
            "100.00%"
        )

        self.status_var.set(
            _("Done")
        )

        LOGGER.info(
            "Download result presented to the user: %s.",
            final_path
        )

        messagebox.showinfo(
            _("Done"),
            _("The file was downloaded:\n\n{path}").format(
                path=final_path
            )
        )

    def __download_error(
        self,
        error
    ):
        self.downloading = False

        self.download_button.config(
            state="normal"
        )

        self.language_selector.config(
            state="readonly"
        )

        self.status_var.set(
            _("Download error")
        )

        messagebox.showerror(
            _("Error"),
            error
        )
