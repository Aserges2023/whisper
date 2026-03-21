@echo off
chcp 65001 >nul
title Pipeline Judicial Diario - ASERGES
echo ============================================================
echo   PIPELINE JUDICIAL DIARIO - ASERGES
echo ============================================================
echo.

REM Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python no encontrado. Instale Python 3.11+ desde python.org
    pause
    exit /b 1
)

REM Verificar pdfplumber
python -c "import pdfplumber" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias...
    pip install pdfplumber
)

REM Directorio del script
cd /d "%~dp0"

REM Ejecutar pipeline (sin argumentos = procesa correos de hoy)
echo Ejecutando pipeline para correos de hoy...
python scripts\pipeline_judicial.py %*

echo.
echo Pipeline finalizado.
pause
