# Segment Downloader [1.0.1]

Segment Downloader is a desktop application for downloading files through
multiple HTTP range requests. It resumes interrupted downloads, retries
temporary server errors, prevents existing files from being overwritten, and
remembers the application settings. The interface is available in English and
Polish.

## Downloads

Ready-to-use builds are available on the GitHub Releases page:

- `Segment-Downloader-windows.exe`
- `Segment-Downloader-linux.tar.gz`
- `Segment-Downloader-macos.zip`

## Run from source

Python 3 and the `requests` package are required.

Windows:

```cmd
py -3 -m pip install requests
py -3 -m app.main
```

Linux and macOS:

```bash
python3 -m pip install requests
python3 -m app.main
```

You can also run `app/main.py` directly from an IDE such as Visual Studio Code.

## Compile translations

On Windows, run `compile_translations.cmd`. On any supported system, use:

```bash
python3 tools/compile_translations.py
```

## Build on Windows

Run:

```cmd
build.cmd
```

The script compiles the translations, installs missing build dependencies after
confirmation, and creates:

```text
.output\Segment-Downloader.exe
```

## Automated releases

Publishing a GitHub Release runs `.github/workflows/release.yml`. The workflow
tests the project, builds it on Windows, Linux, and macOS, and adds all three
packages to the Release assets.
