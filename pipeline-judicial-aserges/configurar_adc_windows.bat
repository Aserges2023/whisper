@echo off
:: ============================================================
:: configurar_adc_windows.bat
:: Configura Application Default Credentials (ADC) con
:: Service Account Impersonation para el Pipeline Judicial.
::
:: Ejecutar UNA SOLA VEZ por equipo (o cuando caduquen las
:: credenciales, aunque con ADC/impersonation no caducan).
::
:: Requisitos:
::   1. Google Cloud CLI instalado (gcloud en PATH)
::      Descargar: https://cloud.google.com/sdk/docs/install
::   2. Tu cuenta de usuario (santiago@aserges.es) debe tener
::      el rol roles/iam.serviceAccountTokenCreator sobre la SA
::      pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com
::   3. La API iamcredentials.googleapis.com habilitada en el
::      proyecto aserges-pipeline
:: ============================================================

setlocal

set SA_EMAIL=pipeline-judicial-sa@aserges-pipeline.iam.gserviceaccount.com
set SCOPES=https://www.googleapis.com/auth/calendar.events,https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly

echo.
echo ============================================================
echo   CONFIGURACION ADC - Pipeline Judicial ASERGES
echo ============================================================
echo.
echo Service Account: %SA_EMAIL%
echo Scopes: Calendar + Gmail
echo.

:: Verificar que gcloud está instalado
where gcloud >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Google Cloud CLI no encontrado en PATH.
    echo.
    echo Instala gcloud desde: https://cloud.google.com/sdk/docs/install
    echo Luego reinicia esta ventana y vuelve a ejecutar este script.
    pause
    exit /b 1
)

echo gcloud encontrado. Iniciando configuracion ADC...
echo.
echo Se abrira el navegador para que inicies sesion con santiago@aserges.es
echo.

gcloud auth application-default login ^
    --impersonate-service-account=%SA_EMAIL% ^
    --scopes=%SCOPES%

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: La configuracion ADC fallo.
    echo.
    echo Posibles causas:
    echo   1. Tu cuenta no tiene el rol roles/iam.serviceAccountTokenCreator
    echo      sobre la SA. Pide a un admin de GCP que te lo asigne.
    echo   2. La API iamcredentials.googleapis.com no esta habilitada.
    echo      Habilitala en: https://console.cloud.google.com/apis/library/iamcredentials.googleapis.com?project=aserges-pipeline
    echo   3. Cancelaste el login en el navegador.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   ADC configurado correctamente.
echo ============================================================
echo.
echo Verificando configuracion...
echo.

python scripts\auth_adc.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo La verificacion fallo. Revisa los errores anteriores.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Listo. El pipeline puede ejecutarse en modo ADC.
echo.
echo   Para usar ADC en el analisis IA, ejecuta:
echo     python scripts\analisis_ia_calendar.py --modo-auth adc
echo.
echo   O establece la variable de entorno permanente:
echo     setx PIPELINE_AUTH_MODE adc
echo ============================================================
echo.
pause
endlocal
