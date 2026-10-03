import ctypes
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.download_manager import DownloadCancelled, DownloadManager
from app.logger import get_logger
from app.settings import SettingsManager
from app.temporary_files import TemporaryFilesManager
from app.translator import set_language, translate as _


LOGGER = get_logger(__name__)
WINDOW_WIDTH = 720
WINDOW_HEIGHT = 690
MINIMUM_WINDOW_WIDTH = 650
MINIMUM_WINDOW_HEIGHT = 650
MINIMUM_VISIBLE_WIDTH = 80
MINIMUM_VISIBLE_HEIGHT = 50


# ==========================================================
# GUI
# ==========================================================

class DownloadApp:
    def __init__(self, root):
        self.root = root

        self.root.minsize(
            MINIMUM_WINDOW_WIDTH,
            MINIMUM_WINDOW_HEIGHT
        )

        self.downloading = False
        self.cancel_requested = False
        self.cancel_event = None
        self.download_manager = None
        self.closing = False

        self.settings_manager = SettingsManager()
        saved_settings = self.settings_manager.load()
        self.__set_initial_window_position(
            saved_settings
        )
        self.__settings_save_job = None
        self.__temp_size_job = None
        self.__temp_size_scan_running = False
        self.__temp_clear_running = False
        self.__temp_size_bytes = None
        self.temp_files_manager = TemporaryFilesManager()

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

        self.temp_size_var = tk.StringVar(
            value=_("Temporary files: calculating...")
        )

        self.activity_messages = []

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
        self.root.bind(
            "<Configure>",
            self.__window_configured,
            add="+"
        )
        self.__schedule_temp_size_refresh(
            delay=0
        )

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
        name_row = ttk.Frame(
            main
        )

        name_row.pack(
            fill="x",
            pady=(0, 15)
        )

        name_row.columnconfigure(
            0,
            weight=1
        )

        ttk.Label(
            name_row,
            text=_("File name:")
        ).grid(
            row=0,
            column=0,
            sticky="w"
        )

        self.name_entry = ttk.Entry(
            name_row,
            textvariable=self.file_name_var
        )

        self.name_entry.grid(
            row=1,
            column=0,
            sticky="nsew",
            pady=(5, 0),
            ipady=5
        )

        temp_controls = ttk.Frame(
            name_row
        )

        temp_controls.grid(
            row=0,
            column=1,
            rowspan=2,
            sticky="nsew",
            padx=(10, 0)
        )

        temp_controls.rowconfigure(
            1,
            weight=1
        )

        temp_controls.columnconfigure(
            0,
            weight=1,
            uniform="temp_buttons"
        )

        temp_controls.columnconfigure(
            1,
            weight=1,
            uniform="temp_buttons"
        )

        ttk.Label(
            temp_controls,
            textvariable=self.temp_size_var,
            anchor="w"
        ).grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 5)
        )

        self.open_temp_button = ttk.Button(
            temp_controls,
            text=_("OPEN"),
            command=self.__open_temporary_directory
        )

        self.open_temp_button.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=(0, 5),
            ipady=3
        )

        self.clear_temp_button = ttk.Button(
            temp_controls,
            text=_("CLEAR"),
            command=self.__clear_temporary_files
        )

        self.clear_temp_button.grid(
            row=1,
            column=1,
            sticky="nsew",
            ipady=3
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
            text=_("BROWSE"),
            command=self.__choose_output_directory
        ).pack(
            side="right",
            padx=(10, 0),
            ipady=5
        )

        # Przyciski
        actions = ttk.Frame(
            main
        )

        actions.pack(
            fill="x",
            pady=(0, 25)
        )

        actions.columnconfigure(
            0,
            weight=3
        )

        actions.columnconfigure(
            1,
            weight=1
        )

        self.download_button = ttk.Button(
            actions,
            text=_("DOWNLOAD"),
            command=self.start_download
        )

        self.download_button.grid(
            row=0,
            column=0,
            sticky="ew",
            ipady=8,
            padx=(0, 5)
        )

        self.cancel_button = ttk.Button(
            actions,
            text=_("CANCEL"),
            command=self.__cancel_download
        )

        self.cancel_button.grid(
            row=0,
            column=1,
            sticky="ew",
            ipady=8,
            padx=(5, 0)
        )

        self.__update_download_controls()

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

        self.activity_frame = tk.Frame(
            main,
            relief="solid",
            borderwidth=1,
            background="white",
            padx=8,
            pady=6
        )

        self.activity_frame.pack(
            fill="x",
            pady=(15, 0)
        )

        self.activity_labels = []

        for row_index in range(5):
            label = tk.Label(
                self.activity_frame,
                text="",
                anchor="w",
                justify="left",
                background="white",
                font=(
                    "Segoe UI",
                    10
                )
            )

            label.pack(
                fill="x",
                anchor="w",
                pady=2
            )

            self.activity_labels.append(
                label
            )

        self.activity_frame.bind(
            "<Configure>",
            self.__resize_activity_labels
        )

        self.__refresh_activity()

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

        self.activity_messages.clear()

        self.temp_size_var.set(
            _("Temporary files: calculating...")
        )

        for widget in self.root.winfo_children():
            widget.destroy()

        self.__create_ui()
        self.__schedule_temp_size_refresh(
            delay=0
        )

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

    def __set_initial_window_position(self, saved_settings):
        saved_position = self.__read_saved_window_position(
            saved_settings
        )

        if (
            saved_position is not None
            and self.__window_position_is_visible(
                *saved_position
            )
        ):
            window_x, window_y = saved_position

        else:
            window_x = max(
                (self.root.winfo_screenwidth() - WINDOW_WIDTH) // 2,
                0
            )
            window_y = max(
                (self.root.winfo_screenheight() - WINDOW_HEIGHT) // 2,
                0
            )

        self.__window_x = window_x
        self.__window_y = window_y

        self.root.geometry(
            f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}"
            f"{window_x:+d}{window_y:+d}"
        )

    @staticmethod
    def __read_saved_window_position(saved_settings):
        try:
            window_x = int(
                saved_settings.get("window_x", "")
            )
            window_y = int(
                saved_settings.get("window_y", "")
            )

        except (TypeError, ValueError):
            return None

        return window_x, window_y

    def __window_position_is_visible(self, window_x, window_y):
        (
            screen_x,
            screen_y,
            screen_width,
            screen_height
        ) = self.__virtual_screen_bounds()

        visible_width = max(
            0,
            min(
                window_x + WINDOW_WIDTH,
                screen_x + screen_width
            ) - max(window_x, screen_x)
        )
        visible_height = max(
            0,
            min(
                window_y + WINDOW_HEIGHT,
                screen_y + screen_height
            ) - max(window_y, screen_y)
        )

        return (
            visible_width >= MINIMUM_VISIBLE_WIDTH
            and visible_height >= MINIMUM_VISIBLE_HEIGHT
        )

    def __virtual_screen_bounds(self):
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32

                return (
                    user32.GetSystemMetrics(76),
                    user32.GetSystemMetrics(77),
                    user32.GetSystemMetrics(78),
                    user32.GetSystemMetrics(79)
                )

            except (AttributeError, OSError):
                pass

        return (
            self.root.winfo_vrootx(),
            self.root.winfo_vrooty(),
            self.root.winfo_vrootwidth(),
            self.root.winfo_vrootheight()
        )

    def __window_configured(self, event):
        if (
            self.closing
            or event.widget is not self.root
            or self.root.state() != "normal"
        ):
            return

        window_x = self.root.winfo_x()
        window_y = self.root.winfo_y()

        if not self.__window_position_is_visible(
            window_x,
            window_y
        ):
            return

        self.__window_x = window_x
        self.__window_y = window_y
        self.__schedule_settings_save()

    def __open_temporary_directory(self):
        try:
            self.temp_files_manager.open()

        except (OSError, RuntimeError) as error:
            LOGGER.error(
                "Failed to open the temporary directory (%s).",
                type(error).__name__
            )

            messagebox.showerror(
                _("Error"),
                _(
                    "Could not open the temporary directory: {error}"
                ).format(
                    error=error
                )
            )

    def __clear_temporary_files(self):
        if self.downloading or self.__temp_clear_running:
            return

        confirmed = messagebox.askyesno(
            _("Clear temporary files"),
            _(
                "Delete all temporary download files?\n\n"
                "Saved progress for unfinished downloads will be lost."
            ),
            parent=self.root
        )

        if not confirmed:
            return

        self.__temp_clear_running = True
        self.temp_size_var.set(
            _("Temporary files: clearing...")
        )
        self.__update_download_controls()

        thread = threading.Thread(
            target=self.__clear_temporary_files_worker,
            daemon=True
        )
        thread.start()

    def __clear_temporary_files_worker(self):
        try:
            self.temp_files_manager.clear()

        except (OSError, RuntimeError) as error:
            LOGGER.error(
                "Failed to clear temporary files (%s).",
                type(error).__name__
            )

            self.__schedule_ui(
                self.__temporary_files_clear_failed,
                str(error)
            )

        else:
            self.__schedule_ui(
                self.__temporary_files_cleared
            )

    def __temporary_files_cleared(self):
        self.__temp_clear_running = False
        self.__temp_size_bytes = 0
        self.temp_size_var.set(
            _("Temporary files: {size}").format(
                size=self.__format_file_size(0)
            )
        )
        self.__update_download_controls()
        self.__schedule_temp_size_refresh(
            delay=0
        )

        messagebox.showinfo(
            _("Clear temporary files"),
            _("Temporary files were deleted."),
            parent=self.root
        )

    def __temporary_files_clear_failed(self, error):
        self.__temp_clear_running = False
        self.__update_download_controls()
        self.__schedule_temp_size_refresh(
            delay=0
        )

        messagebox.showerror(
            _("Error"),
            _(
                "Could not clear temporary files: {error}"
            ).format(
                error=error
            ),
            parent=self.root
        )

    def __schedule_temp_size_refresh(self, delay=3000):
        if self.closing:
            return

        if self.__temp_size_job is not None:
            try:
                self.root.after_cancel(
                    self.__temp_size_job
                )

            except tk.TclError:
                pass

        self.__temp_size_job = self.root.after(
            delay,
            self.__refresh_temp_size
        )

    def __refresh_temp_size(self):
        self.__temp_size_job = None

        if (
            not self.__temp_size_scan_running
            and not self.__temp_clear_running
        ):
            self.__temp_size_scan_running = True

            thread = threading.Thread(
                target=self.__temp_size_worker,
                daemon=True
            )
            thread.start()

        self.__schedule_temp_size_refresh()

    def __temp_size_worker(self):
        try:
            size = self.temp_files_manager.calculate_size()

        except (OSError, RuntimeError) as error:
            LOGGER.error(
                "Failed to calculate temporary file size (%s).",
                type(error).__name__
            )
            size = None

        self.__schedule_ui(
            self.__apply_temp_size,
            size
        )

    def __apply_temp_size(self, size):
        self.__temp_size_scan_running = False

        if self.__temp_clear_running:
            return

        self.__temp_size_bytes = size

        if size is None:
            text = _("Temporary files: unavailable")

        else:
            text = _("Temporary files: {size}").format(
                size=self.__format_file_size(size)
            )

        self.temp_size_var.set(
            text
        )

    @staticmethod
    def __format_file_size(size):
        units = ("B", "KB", "MB", "GB", "TB")
        value = float(size)

        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"

                return f"{value:.1f} {unit}"

            value /= 1024

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
        settings["window_x"] = str(
            self.__window_x
        )
        settings["window_y"] = str(
            self.__window_y
        )

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
        self.closing = True

        if self.cancel_event is not None:
            self.cancel_event.set()

        if self.download_manager is not None:
            self.download_manager.cancel()

        if self.__settings_save_job is not None:
            self.root.after_cancel(
                self.__settings_save_job
            )

        if self.__temp_size_job is not None:
            self.root.after_cancel(
                self.__temp_size_job
            )

        self.__save_settings()

        LOGGER.info(
            "Application window closed."
        )

        self.root.destroy()

    def start_download(self):
        if self.downloading or self.__temp_clear_running:
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
        self.cancel_requested = False
        self.cancel_event = threading.Event()
        self.download_manager = None

        self.__update_download_controls()

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

        self.__clear_activity()

        self.__add_activity(
            _("Waiting for the server response...")
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

    def __cancel_download(self):
        if (
            not self.downloading
            or self.cancel_requested
        ):
            return

        self.cancel_requested = True

        if self.cancel_event is not None:
            self.cancel_event.set()

        if self.download_manager is not None:
            self.download_manager.cancel()

        self.__add_activity(
            _("Cancelling download...")
        )

        self.__update_download_controls()

        LOGGER.info(
            "Download cancellation requested."
        )

    def __update_download_controls(self):
        if not hasattr(self, "download_button"):
            return

        self.download_button.config(
            state=(
                "disabled"
                if self.downloading or self.__temp_clear_running
                else "normal"
            )
        )

        self.cancel_button.config(
            state=(
                "normal"
                if self.downloading and not self.cancel_requested
                else "disabled"
            )
        )

        self.language_selector.config(
            state=(
                "disabled"
                if self.downloading
                else "readonly"
            )
        )

        self.clear_temp_button.config(
            state=(
                "disabled"
                if self.downloading or self.__temp_clear_running
                else "normal"
            )
        )

        self.open_temp_button.config(
            state=(
                "disabled"
                if self.__temp_clear_running
                else "normal"
            )
        )

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
                ),
                activity_callback=(
                    self.__activity_callback
                ),
                cancel_event=self.cancel_event
            )

            self.download_manager = manager

            final_path = manager.run(
                path=output_directory,
                segment_size_kb=segment_size,
                thread_count=thread_count,
                file_name=file_name,
                file_extension=extension,
                url=url
            )

            self.__schedule_ui(
                self.__download_finished,
                final_path
            )

        except DownloadCancelled:
            LOGGER.info(
                "Download cancelled by the user."
            )

            self.__schedule_ui(
                self.__download_cancelled
            )

        except Exception as error:
            LOGGER.error(
                "Download failed: file=%s%s, error_type=%s.",
                file_name,
                extension,
                type(error).__name__
            )

            self.__schedule_ui(
                self.__download_error,
                str(error)
            )

    def __schedule_ui(self, callback, *args):
        if self.closing:
            return

        try:
            self.root.after(
                0,
                callback,
                *args
            )

        except (RuntimeError, tk.TclError):
            pass

    def __progress_callback(
        self,
        current,
        total,
        percent
    ):
        self.__schedule_ui(
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
        self.__schedule_ui(
            self.status_var.set,
            text
        )

    def __activity_callback(
        self,
        text
    ):
        self.__schedule_ui(
            self.__add_activity,
            text
        )

    def __finish_download(self):
        self.downloading = False
        self.cancel_requested = False
        self.cancel_event = None
        self.download_manager = None
        self.__update_download_controls()
        self.__schedule_temp_size_refresh(
            delay=0
        )

    def __clear_activity(self):
        self.activity_messages.clear()
        self.__refresh_activity()

    def __add_activity(self, text):
        self.activity_messages.append(text)
        del self.activity_messages[:-5]
        self.__refresh_activity()

    def __refresh_activity(self):
        if not hasattr(self, "activity_labels"):
            return

        for index, label in enumerate(
            self.activity_labels
        ):
            if index < len(self.activity_messages):
                text = (
                    f"\u2022 {self.activity_messages[index]}"
                )

            else:
                text = ""

            label.config(
                text=text
            )

    def __resize_activity_labels(self, event):
        wrap_length = max(
            event.width - 20,
            100
        )

        for label in self.activity_labels:
            label.config(
                wraplength=wrap_length
            )

    def __download_finished(
        self,
        final_path
    ):
        self.__finish_download()

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
        self.__finish_download()

        self.status_var.set(
            _("Download error")
        )

        self.__add_activity(
            _("Download stopped: {error}").format(
                error=error
            )
        )

        messagebox.showerror(
            _("Error"),
            error
        )

    def __download_cancelled(self):
        self.__finish_download()

        self.status_var.set(
            _("Download cancelled")
        )

        self.__add_activity(
            _(
                "Download cancelled. Reusable segments were preserved."
            )
        )
