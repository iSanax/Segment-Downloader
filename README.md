# Segment Downloader [1.1.0]

Segment Downloader is a desktop application for downloading files through
multiple HTTP range requests. It can resume interrupted downloads, retries
temporary server errors, prevents existing files from being overwritten, and
remembers the application settings. The interface is available in English and
Polish.

## Run from source

Python 3 and the `requests` package are required.

```cmd
py -3 -m pip install requests
py -3 -m app.main
```

You can also run `app\main.py` directly from an IDE such as Visual Studio Code.

## Compile translations

Run `compile_translations.cmd`, or use:

```cmd
py -3 tools\compile_translations.py
```

## Build a single executable

Run:

```cmd
build.cmd
```

The script compiles the translations, installs missing build dependencies after
confirmation, and creates:

```text
.output\Segment-Downloader.exe
```
