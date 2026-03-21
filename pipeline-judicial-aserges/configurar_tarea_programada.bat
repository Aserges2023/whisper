@echo off
chcp 65001 >nul
echo ============================================================
echo   CONFIGURACION DE TAREAS PROGRAMADAS
echo   Pipeline Judicial ASERGES
echo ============================================================
echo.
echo Este script crea dos tareas en el Programador de Tareas de Windows:
echo   - Pipeline Judicial ASERGES (Manana): L-V a las 08:00
echo   - Pipeline Judicial ASERGES (Tarde):  L-V a las 20:00
echo.
echo NOTA: Requiere ejecutar como Administrador.
echo.
pause

set "PIPELINE_PATH=%~dp0ejecutar_pipeline.bat"

echo.
echo [1/2] Creando tarea de manana (08:00 L-V)...
schtasks /create /tn "Pipeline Judicial ASERGES Manana" /tr "\"%PIPELINE_PATH%\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 08:00 /f /rl HIGHEST
if %errorlevel%==0 (
    echo       OK - Tarea de manana creada correctamente.
) else (
    echo       ERROR - No se pudo crear la tarea de manana.
    echo       Asegurese de ejecutar como Administrador.
)

echo.
echo [2/2] Creando tarea de tarde (20:00 L-V)...
schtasks /create /tn "Pipeline Judicial ASERGES Tarde" /tr "\"%PIPELINE_PATH%\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 20:00 /f /rl HIGHEST
if %errorlevel%==0 (
    echo       OK - Tarea de tarde creada correctamente.
) else (
    echo       ERROR - No se pudo crear la tarea de tarde.
    echo       Asegurese de ejecutar como Administrador.
)

echo.
echo ============================================================
echo   VERIFICACION
echo ============================================================
echo.
echo Tareas programadas activas:
schtasks /query /tn "Pipeline Judicial ASERGES Manana" /fo TABLE 2>nul
schtasks /query /tn "Pipeline Judicial ASERGES Tarde" /fo TABLE 2>nul

echo.
echo ============================================================
echo   IMPORTANTE
echo ============================================================
echo.
echo Las tareas ejecutaran automaticamente el pipeline base
echo (descarga IMAP + clasificacion + copia a Notificaciones/Usu2).
echo.
echo Para el analisis IA, necesita:
echo   1. Tener OPENAI_API_KEY configurada como variable de entorno
echo   2. Usar Manus (nube) o un LLM de escritorio para el analisis
echo.
echo Para desinstalar las tareas:
echo   schtasks /delete /tn "Pipeline Judicial ASERGES Manana" /f
echo   schtasks /delete /tn "Pipeline Judicial ASERGES Tarde" /f
echo.
pause
