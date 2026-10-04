@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set "VENV=%LOCALAPPDATA%\DecisorNoticias\venv"
title Actualizar el Decisor
echo ============================================================
echo   ACTUALIZANDO EL DECISOR
echo   Tus claves y tu configuracion se conservan.
echo   Si la app esta en marcha, cierra antes su ventana.
echo ============================================================
set "ZIP=%TEMP%\decisor_actualizacion.zip"
set "TMPDIR=%TEMP%\decisor_actualizacion"
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
echo Descargando la ultima version...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/eljanx/decisorrapidodenoticiasmacro/archive/refs/heads/claude/serene-heisenberg-rzaez7.zip' -OutFile $env:ZIP; Expand-Archive -Force -Path $env:ZIP -DestinationPath $env:TMPDIR"
if errorlevel 1 goto :error
for /d %%D in ("%TMPDIR%\*") do set "NUEVA=%%D"
if not defined NUEVA goto :error
echo Copiando archivos...
robocopy "%NUEVA%" "%~dp0." /E /NFL /NDL /NJH /NJS /NP /XF .env config.yaml *.db >nul
if errorlevel 8 goto :error
if not exist "%VENV%\Scripts\python.exe" goto :sin_instalar
echo Actualizando componentes...
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 goto :error
rmdir /s /q "%TMPDIR%" >nul 2>nul
del "%ZIP%" >nul 2>nul
echo.
echo ============================================================
echo   ACTUALIZADO. Ahora haz doble clic en ARRANCAR.bat
echo ============================================================
pause
exit /b 0

:sin_instalar
echo Archivos actualizados. Ahora haz doble clic en INSTALAR.bat
pause
exit /b 0

:error
echo.
echo Algo ha fallado. Haz una captura de esta ventana y ensenasela a Claude.
pause
exit /b 1
