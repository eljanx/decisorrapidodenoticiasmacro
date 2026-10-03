@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
title Decisor - NO CIERRES ESTA VENTANA
if not exist ".venv\Scripts\python.exe" goto :sin_instalar
if not exist ".env" goto :sin_instalar
echo ============================================================
echo   DECISOR EN MARCHA
echo   - Deja esta ventana abierta (puedes minimizarla).
echo   - Todo se maneja desde Telegram en el movil.
echo   - Para pararlo, cierra esta ventana.
echo ============================================================
:bucle
".venv\Scripts\python.exe" -m decisor
echo.
echo La app se ha detenido. Se reinicia sola en 15 segundos...
timeout /t 15 >nul
goto :bucle

:sin_instalar
echo Primero haz doble clic en INSTALAR.bat
pause
