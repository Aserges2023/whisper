@echo off
:: ============================================================
:: activar_modo_adc.bat
:: Activa el modo ADC (Service Account Impersonation) como
:: método de autenticación permanente del Pipeline Judicial.
::
:: Qué hace este script:
::   1. Establece PIPELINE_AUTH_MODE=adc de forma permanente
::      para el usuario actual (no requiere administrador).
::   2. Verifica que las credenciales ADC están guardadas en disco.
::   3. Muestra el estado final de la configuración.
::
:: Requisito previo: haber ejecutado configurar_adc_windows.bat
:: ============================================================

setlocal

echo.
echo ============================================================
echo   ACTIVAR MODO ADC - Pipeline Judicial ASERGES
echo ============================================================
echo.

:: ── Paso 1: Establecer variable de entorno permanente ────────
echo [1/3] Estableciendo PIPELINE_AUTH_MODE=adc...
setx PIPELINE_AUTH_MODE adc >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: No se pudo establecer la variable de entorno.
    pause
    exit /b 1
)
echo       OK - Variable guardada para el usuario actual.
echo.

:: ── Paso 2: Verificar credenciales ADC en disco ──────────────
echo [2/3] Verificando credenciales ADC en disco...
set ADC_FILE=%APPDATA%\gcloud\application_default_credentials.json
if exist "%ADC_FILE%" (
    echo       OK - Credenciales encontradas en:
    echo       %ADC_FILE%
) else (
    echo.
    echo AVISO: No se encontraron credenciales ADC en disco.
    echo.
    echo Debes ejecutar primero:
    echo   configurar_adc_windows.bat
    echo.
    echo O manualmente:
    echo   gcloud auth application-default login --impersonate-service-account=pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com --scopes=https://www.googleapis.com/auth/calendar.events,https://www.googleapis.com/auth/gmail.send
    echo.
    pause
    exit /b 1
)
echo.

:: ── Paso 3: Mostrar configuración final ─────────────────────
echo [3/3] Configuracion final:
echo.
echo   Variable de entorno:  PIPELINE_AUTH_MODE = adc
echo   Credenciales ADC:     %ADC_FILE%
echo   Modo activo:          Service Account Impersonation
echo   Sin expiracion:       Las credenciales ADC no caducan
echo.
echo ============================================================
echo   Listo. El pipeline usara modo ADC automaticamente.
echo.
echo   Para volver al modo MCP (Manus Cowork), ejecuta:
echo     setx PIPELINE_AUTH_MODE mcp
echo ============================================================
echo.
pause
endlocal
