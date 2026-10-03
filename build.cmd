@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "APP_NAME=Segment-Downloader"
set "ENTRY_POINT=main.py"
set "OUTPUT_DIRECTORY=Output"
set "WORK_DIRECTORY=build"
set "PYTHON_EXE="
set "PYTHON_ARGS="

echo [1/4] Detecting Python...

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
    py -3 --version >nul 2>nul

    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    ) else (
        python --version >nul 2>nul

        if not errorlevel 1 (
            set "PYTHON_EXE=python"
        )
    )
)

if not defined PYTHON_EXE (
    echo ERROR: Python 3 was not found.
    echo Install Python 3 and run this file again.
    goto :failure
)

"%PYTHON_EXE%" %PYTHON_ARGS% --version

if errorlevel 1 (
    echo ERROR: Python 3 could not be started.
    goto :failure
)

echo.
echo Checking build dependencies...

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import PyInstaller, requests" >nul 2>nul

if errorlevel 1 (
    echo PyInstaller or requests is not installed.
    choice /C YN /N /M "Install the required packages now? [Y/N]: "

    if errorlevel 2 goto :failure

    "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --upgrade pyinstaller requests

    if errorlevel 1 (
        echo ERROR: Failed to install build dependencies.
        goto :failure
    )
)

echo.
echo [2/4] Compiling translations...

"%PYTHON_EXE%" %PYTHON_ARGS% compile_translations.py

if errorlevel 1 (
    echo ERROR: Translation compilation failed.
    goto :failure
)

if not exist "lang\bin\en.mo" (
    echo ERROR: lang\bin\en.mo was not generated.
    goto :failure
)

if not exist "lang\bin\pl.mo" (
    echo ERROR: lang\bin\pl.mo was not generated.
    goto :failure
)

echo.
echo [3/4] Building a single executable...

"%PYTHON_EXE%" %PYTHON_ARGS% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "%APP_NAME%" ^
    --distpath "%OUTPUT_DIRECTORY%" ^
    --workpath "%WORK_DIRECTORY%" ^
    --specpath "%WORK_DIRECTORY%" ^
    --add-data "%CD%\lang\bin;lang\bin" ^
    "%ENTRY_POINT%"

if errorlevel 1 (
    echo ERROR: Application build failed.
    goto :failure
)

if not exist "%OUTPUT_DIRECTORY%\%APP_NAME%.exe" (
    echo ERROR: The executable was not created.
    goto :failure
)

echo.
echo [4/4] Build completed successfully.
echo Output: %CD%\%OUTPUT_DIRECTORY%\%APP_NAME%.exe
echo.
pause
exit /b 0

:failure
echo.
echo Build failed.
echo.
pause
exit /b 1
