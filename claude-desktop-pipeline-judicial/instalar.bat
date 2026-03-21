@echo off
chcp 65001 >nul
title Instalación Pipeline Judicial - ASERGES
echo ============================================================
echo   INSTALACIÓN DE DEPENDENCIAS
echo   Pipeline Judicial Diario - ASERGES
echo ============================================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado.
    echo Descargue e instale Python 3.11+ desde https://www.python.org/downloads/
    echo IMPORTANTE: Marque "Add Python to PATH" durante la instalación.
    pause
    exit /b 1
)

echo Python encontrado:
python --version
echo.

echo Instalando dependencias...
pip install pdfplumber
echo.

echo ============================================================
echo   INSTALACIÓN COMPLETADA
echo ============================================================
echo.
echo Para ejecutar el pipeline:
echo   - Doble clic en ejecutar_pipeline.bat (procesa correos de hoy)
echo   - O desde CMD: ejecutar_pipeline.bat --desde 2026-03-16
echo.
pause
