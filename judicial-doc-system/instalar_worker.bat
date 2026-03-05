@echo off
setlocal

REM ============================================================================
REM instalar_worker.bat
REM ============================================================================
REM
REM Script para instalar el worker Python como un servicio de Windows usando NSSM.
REM
REM PASOS:
REM 1. Verifica si Python 3.11+ está instalado.
REM 2. Crea un entorno virtual (venv).
REM 3. Instala las dependencias de Python desde requirements.txt.
REM 4. Descarga y configura NSSM (Non-Sucking Service Manager).
REM 5. Instala el servicio 'JudicialWorkerASERGESSL'.
REM
REM EJECUCIÓN:
REM - Ejecutar este script como Administrador.
REM
REM ============================================================================

set "PYTHON_EXE=python"
set "VENV_DIR=venv"
set "SERVICE_NAME=JudicialWorkerASERGESSL"
set "SCRIPT_PATH=%~dp0judicial_worker.py"
set "NSSM_URL=https://nssm.cc/release/nssm-2.24.zip"
set "NSSM_ZIP=nssm.zip"
set "NSSM_DIR=nssm-2.24"

REM --- 1. VERIFICAR PYTHON ---
echo [1/5] Verificando instalacion de Python...
%PYTHON_EXE% --version > nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python no encontrado en el PATH.
    echo Por favor, instale Python 3.11 o superior y asegurese de que este en el PATH.
    pause
    exit /b 1
)

%PYTHON_EXE% -c "import sys; sys.exit(0) if sys.version_info >= (3, 11) else sys.exit(1)"
if %errorlevel% neq 0 (
    echo ERROR: Se requiere Python 3.11 o superior.
    %PYTHON_EXE% --version
    pause
    exit /b 1
)
echo Python encontrado.

REM --- 2. CREAR ENTORNO VIRTUAL ---
echo.
echo [2/5] Creando entorno virtual en '%VENV_DIR%'...
if not exist "%VENV_DIR%" (
    %PYTHON_EXE% -m venv %VENV_DIR%
    if %errorlevel% neq 0 (
        echo ERROR: No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)
echo Entorno virtual creado.

REM --- 3. INSTALAR DEPENDENCIAS ---
echo.
echo [3/5] Instalando dependencias de Python...

REM Crear requirements.txt
(
    echo flask
    echo python-dotenv
    echo pdfplumber
    echo pytesseract
    echo pdf2image
    echo pyodbc
    echo requests
) > requirements.txt

call "%VENV_DIR%\Scripts\activate.bat"

%VENV_DIR%\Scripts\pip.exe install --upgrade pip
%VENV_DIR%\Scripts\pip.exe install -r requirements.txt

if %errorlevel% neq 0 (
    echo ERROR: Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo Dependencias instaladas.

REM --- 4. DESCARGAR Y CONFIGURAR NSSM ---
echo.
echo [4/5] Configurando NSSM (Non-Sucking Service Manager)...

if not exist "%NSSM_DIR%\win64\nssm.exe" (
    echo Descargando NSSM...
    powershell -Command "Invoke-WebRequest -Uri %NSSM_URL% -OutFile %NSSM_ZIP%"
    if %errorlevel% neq 0 (
        echo ERROR: No se pudo descargar NSSM. Por favor, descarguelo manualmente desde %NSSM_URL%
        pause
        exit /b 1
    )
    powershell -Command "Expand-Archive -Path %NSSM_ZIP% -DestinationPath ." 
    del %NSSM_ZIP%
)

set "NSSM_EXE=%~dp0%NSSM_DIR%\win64\nssm.exe"

REM --- 5. INSTALAR SERVICIO ---
echo.
echo [5/5] Instalando el servicio de Windows '%SERVICE_NAME%'...

REM Verificar si el servicio ya existe
%NSSM_EXE% status %SERVICE_NAME% > nul 2>&1
if %errorlevel% equ 0 (
    echo El servicio '%SERVICE_NAME%' ya existe. Desinstalando version anterior...
    %NSSM_EXE% stop %SERVICE_NAME%
    %NSSM_EXE% remove %SERVICE_NAME% confirm
)

%NSSM_EXE% install %SERVICE_NAME% "%~dp0%VENV_DIR%\Scripts\python.exe" "%SCRIPT_PATH%"
if %errorlevel% neq 0 (
    echo ERROR: No se pudo instalar el servicio con NSSM.
    pause
    exit /b 1
)

REM Configurar el servicio
%NSSM_EXE% set %SERVICE_NAME% AppDirectory "%~dp0"
%NSSM_EXE% set %SERVICE_NAME% AppStdout "%~dp0judicial_worker.log"
%NSSM_EXE% set %SERVICE_NAME% AppStderr "%~dp0judicial_worker.log"
%NSSM_EXE% set %SERVICE_NAME% AppRotateFiles 1
%NSSM_EXE% set %SERVICE_NAME% AppRotateOnline 0
%NSSM_EXE% set %SERVICE_NAME% AppRotateSeconds 86400
%NSSM_EXE% set %SERVICE_NAME% AppRotateBytes 10485760

REM Iniciar el servicio
%NSSM_EXE% start %SERVICE_NAME%

echo.
echo ============================================================================
echo INSTALACION COMPLETADA
echo ============================================================================
echo.
echo El servicio '%SERVICE_NAME%' ha sido instalado y iniciado.
REM echo Para ver los logs, revise el archivo: %~dp0judicial_worker.log
REM echo Para administrar el servicio, use los comandos:
REM echo   nssm start %SERVICE_NAME%
REM echo   nssm stop %SERVICE_NAME%
REM echo   nssm restart %SERVICE_NAME%
REM echo   nssm status %SERVICE_NAME%
REM echo   nssm remove %SERVICE_NAME% confirm
echo.

pause
endlocal
