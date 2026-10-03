@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="

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
    goto :failure
)

echo Compiling translations...
echo.

"%PYTHON_EXE%" %PYTHON_ARGS% "%CD%\tools\compile_translations.py"

if errorlevel 1 (
    goto :failure
)

echo.
echo Translations compiled successfully.
echo.
pause
exit /b 0

:failure
echo.
echo Translation compilation failed.
echo.
pause
exit /b 1
