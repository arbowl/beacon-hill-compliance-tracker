@echo off
REM Build script for MA Rules project (Windows batch version)
REM Creates a standalone executable using PyInstaller and packages necessary files.

echo Starting MA Rules build process...

REM Check if we're in the right directory
if not exist "app.py" (
    echo Error: app.py not found. Please run this script from the project root directory.
    exit /b 1
)

REM Activate virtual environment
echo Activating virtual environment...
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
    echo Virtual environment activated
) else (
    echo Error: Virtual environment not found. Please run setup first:
    echo    python -m venv venv
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    exit /b 1
)

REM Check if PyInstaller is available
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo Error: PyInstaller not found in virtual environment. Please install it with:
    echo    venv\Scripts\activate
    echo    pip install pyinstaller
    exit /b 1
)

REM Clean up previous builds
echo Cleaning up previous builds...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "release" rmdir /s /q "release"

REM Check if app.spec exists, otherwise use app.py
if exist "app.spec" (
    echo Found app.spec file, using it for PyInstaller
    set PYINSTALLER_CMD=pyinstaller app.spec
) else (
    echo No app.spec found, using app.py directly
    set PYINSTALLER_CMD=pyinstaller app.py -F
)

REM Run PyInstaller
echo Building executable with PyInstaller...
%PYINSTALLER_CMD%
if errorlevel 1 (
    echo PyInstaller failed
    exit /b 1
)
echo PyInstaller completed successfully

REM Verify dist folder was created
if not exist "dist" (
    echo Error: dist folder was not created by PyInstaller
    exit /b 1
)

REM Copy necessary files to dist folder
echo Copying necessary files to dist folder...

if exist "config.yaml" (
    copy "config.yaml" "dist\" >nul
    echo    Copied config.yaml
) else (
    echo    Warning: config.yaml not found, skipping
)

if exist "requirements.txt" (
    copy "requirements.txt" "dist\" >nul
    echo    Copied requirements.txt
) else (
    echo    Warning: requirements.txt not found, skipping
)

if exist "cache.json" (
    copy "cache.json" "dist\" >nul
    echo    Copied cache.json
)

REM Create out directory in dist for output files
if not exist "dist\out" mkdir "dist\out"
echo    Created dist\out\ directory for output files

REM Remove build folder
if exist "build" (
    rmdir /s /q "build"
    echo Removed build/ folder
)

REM Rename dist to release
if exist "release" rmdir /s /q "release"
ren "dist" "release"
echo Renamed dist/ to release/

REM Show final structure
echo.
echo Build completed successfully!
echo.
echo Release folder contents:
dir /b "release"
echo.
echo Your standalone executable is ready in the 'release/' folder!
echo    Run it with: release\app.exe

pause
