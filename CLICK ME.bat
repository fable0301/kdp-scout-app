@echo off
setlocal EnableDelayedExpansion
title KDP Scout App - Automatic Installation
color 0A

echo.
echo  ========================================================
echo       KDP SCOUT - AUTOMATIC BUILD
echo       Just double-click and wait, that's it!
echo  ========================================================
echo.

:: --- Check Python ---
echo [1/5] Checking for Python...
python --version >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo.
    echo  [ERROR] Python is not installed on this PC.
    echo.
    echo  Downloading Python 3.12 automatically...
    echo.

    powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe' -OutFile '%TEMP%\python_installer.exe'"

    if not exist "%TEMP%\python_installer.exe" (
        echo  [ERROR] Download failed.
        echo  Check your internet connection.
        echo  Or install Python manually: https://www.python.org/downloads/
        pause
        goto :end
    )

    echo  Installing Python 3.12...
    echo  This may take 2-3 minutes...
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_launcher=1

    if !ERRORLEVEL! NEQ 0 (
        echo  [ERROR] Automatic installation failed.
        echo  Run manually: %TEMP%\python_installer.exe
        echo  IMPORTANT: Check "Add Python to PATH"
        pause
        goto :end
    )

    set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    set "PATH=C:\Program Files\Python312;C:\Program Files\Python312\Scripts;%PATH%"

    echo  [OK] Python 3.12 installed successfully!
    echo.
) else (
    echo  [OK] Python detected
)

echo.

:: --- Install dependencies ---
echo [2/5] Installing dependencies...
echo  This may take a few minutes...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install PyQt6 matplotlib pyinstaller >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo  [ERROR] Failed to install dependencies.
    echo  Check your internet connection.
    pause
    goto :end
)

python -m pip install -e . >nul 2>&1
if !ERRORLEVEL! NEQ 0 (
    echo  Installing project in fallback mode...
    python -m pip install -r requirements.txt >nul 2>&1
)
echo  [OK] Dependencies installed
echo.

:: --- Verify imports ---
echo [3/5] Verifying imports...
python -c "from kdp_scout.gui.app import main; print('  [OK] Imports valid')" 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo  [WARNING] Import verification failed, continuing...
)
echo.

:: --- Verify icon ---
if not exist "kdp_scout\gui\resources\kdpsy.ico" (
    echo  [WARNING] kdpsy.ico not found! The exe will use the default Python icon.
    echo  Place kdpsy.ico in kdp_scout\gui\resources\
)

:: --- Build exe ---
echo [4/5] Compiling .exe (2-5 minutes)...
echo  Grab a coffee, compiling...
echo.

if exist "kdp_scout_gui.spec" (
    python -m PyInstaller kdp_scout_gui.spec --noconfirm 2>build_log.txt
) else (
    python -m PyInstaller --onefile --windowed --name="KDP Scout App" kdp_scout_gui.py --noconfirm 2>build_log.txt
)

if !ERRORLEVEL! NEQ 0 (
    echo  [ERROR] Compilation failed.
    echo  Details in build_log.txt:
    echo.
    type build_log.txt
    echo.
    pause
    goto :end
)
echo  [OK] Compilation complete!
echo.

:: --- Create desktop shortcut ---
echo [5/5] Creating desktop shortcut...

set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "!DESKTOP!" set "DESKTOP=%USERPROFILE%\Bureau"
if not exist "!DESKTOP!" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if not exist "!DESKTOP!" set "DESKTOP=%USERPROFILE%\OneDrive\Bureau"

set "EXE_PATH="
if exist "dist\KDP Scout App.exe" (
    set "EXE_PATH=%CD%\dist\KDP Scout App.exe"
) else if exist "dist\KDP Scout App\KDP Scout App.exe" (
    set "EXE_PATH=%CD%\dist\KDP Scout App\KDP Scout App.exe"
)

if defined EXE_PATH (
    :: Remove old exe copy on Desktop (legacy method)
    if exist "!DESKTOP!\KDP Scout App.exe" del /Q "!DESKTOP!\KDP Scout App.exe" >nul 2>&1
    if exist "!DESKTOP!\KDP Scout App" rmdir /S /Q "!DESKTOP!\KDP Scout App" >nul 2>&1
    powershell -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('!DESKTOP!\KDP Scout App.lnk'); $sc.TargetPath = '!EXE_PATH!'; $sc.WorkingDirectory = '%CD%'; $sc.IconLocation = '!EXE_PATH!,0'; $sc.Save()" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        echo  [OK] Shortcut "KDP Scout App" created on your Desktop!
        echo  Pointing to: !EXE_PATH!
    ) else (
        echo  [INFO] Could not create shortcut.
        echo  Your .exe is here: !EXE_PATH!
    )
) else (
    echo  [WARNING] Exe not found at expected location.
    echo  Contents of dist folder:
    dir /s /b dist\*.exe 2>nul
)

echo.
echo  ========================================================
echo.
echo   BUILD SUCCESSFUL!
echo.
echo   Your .exe is in the dist\ folder.
echo   A shortcut has been created on your Desktop.
echo.
echo  ========================================================
echo.

:: --- Auto-launch ---
if defined EXE_PATH (
    echo  Launching KDP Scout App...
    start "" "!EXE_PATH!"
    echo  [OK] KDP Scout App is now running!
    echo.
)

if defined EXE_PATH (
    echo  Closing this window in 3 seconds...
    timeout /t 3 /nobreak >nul
    exit /b 0
)
goto :done

:end
echo.
echo  Build did not complete successfully.
echo.

:done
echo  Press any key to close this window...
pause >nul
