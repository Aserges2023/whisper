@echo off
setlocal

REM ============================================================================
REM lexnet_scheduler.bat
REM ============================================================================
REM
REM Script para crear una tarea programada en Windows que ejecute el scraper
REM de LexNET cada 30 minutos.
REM
REM EJECUCIÓN:
REM - Ejecutar este script como Administrador.
REM
REM ============================================================================

set "TASK_NAME=ScraperLexNET_ASERGES"
set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%SCRIPT_DIR%venv\Scripts\python.exe"
set "SCRIPT_TO_RUN=%SCRIPT_DIR%lexnet_scraper.py"

REM --- VERIFICAR ENTORNO VIRTUAL ---
echo [1/2] Verificando entorno virtual...
if not exist "%PYTHON_EXE%" (
    echo ERROR: El entorno virtual no existe en la ruta esperada.
    echo Por favor, ejecute primero 'instalar_worker.bat' para crearlo.
    echo Ruta esperada: %PYTHON_EXE%
    pause
    exit /b 1
)
echo Entorno virtual encontrado.

REM --- CREAR TAREA PROGRAMADA ---
echo.
echo [2/2] Creando/actualizando la tarea programada '%TASK_NAME%'...

REM Eliminar tarea anterior si existe, para asegurar la configuración correcta
schtasks /query /tn "%TASK_NAME%" > nul 2>&1
if %errorlevel% equ 0 (
    echo La tarea ya existe. Se va a eliminar para volver a crearla...
    schtasks /delete /tn "%TASK_NAME%" /f
)

REM Crear la nueva tarea
REM Se ejecuta cada 30 minutos, con el usuario actual, y solo si está logueado.
REM La tarea se inicia 1 minuto después de su creación.

schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%PYTHON_EXE%\" \"%SCRIPT_TO_RUN%\"" ^
    /sc MINUTE /mo 30 ^
    /ru "%USERNAME%" ^
    /rl HIGHEST ^
    /st 00:01 ^
    /f

if %errorlevel% neq 0 (
    echo ERROR: No se pudo crear la tarea programada.
    echo Asegurese de ejecutar este script como Administrador.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo TAREA PROGRAMADA CREADA
echo ============================================================================
echo.
echo La tarea '%TASK_NAME%' se ha creado y se ejecutara cada 30 minutos.
REM echo Puede administrarla desde el Programador de Tareas de Windows.
REM echo Para ejecutarla manualmente, busque la tarea y haga clic en 'Ejecutar'.
echo.

pause
endlocal
