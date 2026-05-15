@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM create-admin.bat - Crea il primo amministratore della piattaforma.
REM
REM Da usare UNA VOLTA SOLA dopo il primo avvio (start.bat), per creare
REM un account admin con cui poter entrare nella dashboard.
REM
REM Lo script:
REM   1. Chiede username (puoi usare la tua email aziendale)
REM   2. Chiede email di contatto
REM   3. Chiede password (con conferma, non vista a schermo)
REM   4. Crea l'utente nel container 'ghg_app' tramite il sistema integrato
REM
REM Tutti gli altri account potranno essere creati dalla pagina Admin della
REM dashboard, senza dover usare di nuovo questo file.
REM ---------------------------------------------------------------------------

echo.
echo ===============================================
echo  GHG Tool - Creazione amministratore
echo ===============================================
echo.

cd /d "%~dp0" || (
    echo [ERRORE] Impossibile cambiare directory.
    pause
    exit /b 1
)

REM ---- Docker check ---------------------------------------------------------
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' in esecuzione.
    echo.
    echo Prima apri Docker Desktop, poi avvia il tool con start.bat,
    echo e infine rilancia questo script.
    pause
    exit /b 1
)

REM ---- Container 'ghg_app' running? -----------------------------------------
for /f "tokens=*" %%i in ('docker ps --filter "name=ghg_app" --format "{{.Names}}"') do set "_app_running=%%i"
if not "%_app_running%"=="ghg_app" (
    echo [ERRORE] Il container 'ghg_app' non e' in esecuzione.
    echo.
    echo Avvia prima il tool con start.bat ^(o start-demo.bat^), aspetta
    echo che la dashboard sia pronta, poi rilancia questo script.
    pause
    exit /b 1
)

echo [OK] Container 'ghg_app' attivo.
echo.

REM ---- Prompt user info -----------------------------------------------------
set /p _username="Username (es. la tua email): "
if "%_username%"=="" (
    echo [ERRORE] Username vuoto. Operazione annullata.
    pause
    exit /b 1
)

set /p _email="Email di contatto: "
if "%_email%"=="" (
    echo [ERRORE] Email vuota. Operazione annullata.
    pause
    exit /b 1
)

echo.
echo Adesso ti chiedero' la password (la digiti due volte per conferma).
echo La password NON sara' visibile a schermo mentre la digiti.
echo Requisiti: minimo 12 caratteri, nessuno spazio.
echo.

REM ---- Run the python CLI inside the container -----------------------------
docker compose -f docker-compose.yml --profile app exec -it app ^
    python -m scripts.create_admin ^
    --username "%_username%" ^
    --email "%_email%"

set "_rc=%ERRORLEVEL%"

echo.
if "%_rc%"=="0" (
    echo ===============================================
    echo  Amministratore creato correttamente.
    echo  Adesso puoi entrare nella dashboard con:
    echo    URL:       http://localhost:8501
    echo    username:  %_username%
    echo    password:  ^(quella che hai appena digitato^)
    echo ===============================================
) else (
    echo ===============================================
    echo  Creazione fallita ^(codice %_rc%^).
    echo  Leggi i messaggi sopra per capire cosa e' andato storto.
    echo  Esempi tipici:
    echo    - username gia' esistente: scegline un altro
    echo    - password troppo corta: minimo 12 caratteri
    echo    - le due password non coincidono: riprova
    echo ===============================================
)
echo.
echo Premi un tasto per chiudere...
pause >nul
endlocal & exit /b %_rc%
