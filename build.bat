@echo off
setlocal

echo.
echo  Building RamBo...
echo.

:: Clean previous build
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

:: Invoked as "python -m PyInstaller", not bare "pyinstaller": this machine has
:: both 3.10 and 3.14 on PATH and the bare shim resolves to 3.10, which would
:: silently produce a build against the wrong interpreter.
python -m PyInstaller ^
  --onedir ^
  --windowed ^
  --name RamBo ^
  --icon icon.ico ^
  --add-data "icon.ico;." ^
  --add-data "logo.png;." ^
  --add-data "CHANGELOG.md;." ^
  --add-data "assets\sfx;assets\sfx" ^
  --collect-all psutil ^
  --hidden-import psutil._pswindows ^
  --hidden-import psutil._psutil_windows ^
  main.pyw

if errorlevel 1 (
  echo.
  echo  BUILD FAILED - skipping release.
  pause
  exit /b 1
)

echo.
echo  Built dist\RamBo\RamBo.exe

:: Wrap the one-dir bundle in a real installer. This is what people download:
:: a zip lets Explorer launch RamBo.exe from inside the archive, where
:: _internal\ was never extracted and loading python3xx.dll fails.
echo.
echo  Building installer...
python build_installer.py
if errorlevel 1 (
  echo.
  echo  INSTALLER BUILD FAILED - skipping release.
  pause
  exit /b 1
)

:: Pass --no-upload to build without cutting a release.
if /i "%~1"=="--no-upload" (
  echo  Release skipped ^(--no-upload^).
  goto :done
)

echo.
echo  Publishing GitHub release...
python publish_github.py
if errorlevel 1 echo  Publish failed - the build in dist\ is still good.

:done
echo.
pause
