@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title Instalador del Decisor
echo ============================================================
echo   INSTALADOR DEL DECISOR RAPIDO DE NOTICIAS
echo   Puede tardar unos minutos. No cierres esta ventana.
echo ============================================================
echo.

call :buscar_python
if defined PY goto :tengo_python

echo No tienes Python instalado. Lo instalo ahora...
where winget >nul 2>nul
if errorlevel 1 goto :sin_winget
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :buscar_python
if defined PY goto :tengo_python
echo.
echo Python se ha instalado. CIERRA esta ventana y vuelve a hacer doble clic en INSTALAR.bat
pause
exit /b 0

:sin_winget
echo.
echo No puedo instalar Python automaticamente en este ordenador.
echo Se abrira la pagina de descarga. Descarga Python, ejecutalo y
echo MARCA LA CASILLA "Add python.exe to PATH" antes de pulsar Install.
echo Despues vuelve a hacer doble clic en INSTALAR.bat
start https://www.python.org/downloads/windows/
pause
exit /b 1

:tengo_python
echo Python encontrado.
if not exist ".venv\Scripts\python.exe" (
    echo Preparando el entorno...
    %PY% -m venv .venv
)
if not exist ".venv\Scripts\python.exe" goto :error
echo Descargando los componentes necesarios...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q --disable-pip-version-check
".venv\Scripts\python.exe" -m pip install -r requirements.txt -q --disable-pip-version-check
if errorlevel 1 goto :error
echo Componentes instalados.
".venv\Scripts\python.exe" -m decisor.configurar
echo.
pause
exit /b 0

:error
echo.
echo Algo ha fallado. Haz una captura de esta ventana y ensenasela a Claude.
pause
exit /b 1

:buscar_python
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
    exit /b 0
)
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
    exit /b 0
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
exit /b 0
