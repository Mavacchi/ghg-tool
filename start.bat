@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM Bulletproof wrapper: whatever happens inside :main, we ALWAYS pause before
REM the window closes. This way, even on a parse error / missing command /
REM antivirus block, the user can read the error message instead of seeing the
REM black window vanish.
REM ---------------------------------------------------------------------------

echo.
echo ===============================================
echo  GHG Tool - Avvio in corso
echo ===============================================
echo.

call :main
set "_exit_code=%ERRORLEVEL%"

echo.
echo -----------------------------------------------
if "%_exit_code%"=="0" (
    echo  Avvio completato.
) else (
    echo  Avvio terminato con errori ^(codice %_exit_code%^).
    echo  Leggi i messaggi sopra per capire cosa e' andato storto.
)
echo -----------------------------------------------
echo.
echo Premi un tasto per chiudere questa finestra...
pause >nul
endlocal & exit /b %_exit_code%


REM ===========================================================================
REM :main - actual start-up logic. Returns 0 on success, non-zero on error.
REM ===========================================================================
:main

REM ---- Sposta cwd nella cartella di questo script (PRIMA di qualsiasi cosa) --
cd /d "%~dp0" || (
    echo [ERRORE] Impossibile cambiare directory in "%~dp0".
    exit /b 1
)

REM ---- Verifica Docker Desktop installato -----------------------------------
where docker >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' installato ^(comando 'docker' non trovato^).
    echo.
    echo Scaricalo da:  https://www.docker.com/products/docker-desktop/
    echo.
    echo Dopo l'installazione:
    echo   1. Apri Docker Desktop dal menu Start
    echo   2. Aspetta che l'icona della balena diventi stabile
    echo   3. Rilancia questo file start.bat con doppio click
    exit /b 1
)

REM ---- Verifica che il daemon stia girando ----------------------------------
docker info >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' in esecuzione.
    echo.
    echo Apri Docker Desktop dal menu Start, aspetta che parta
    echo del tutto ^(icona balena nella tray di sistema^), poi
    echo rilancia questo file start.bat.
    exit /b 1
)

REM ---- Verifica plugin Compose v2 -------------------------------------------
docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Plugin 'docker compose' v2 non disponibile.
    echo.
    echo Aggiorna Docker Desktop all'ultima versione: include Compose v2
    echo come plugin del CLI ^(comando 'docker compose', non 'docker-compose'^).
    exit /b 1
)

echo [OK] Docker Desktop in esecuzione.
echo.

REM ---- Verifica presenza file compose ---------------------------------------
if not exist "docker-compose.yml" (
    echo [ERRORE] Non trovo docker-compose.yml in "%CD%".
    echo Assicurati di aver scaricato l'intero progetto da GitHub
    echo e di aver scompattato lo ZIP correttamente.
    exit /b 1
)
if not exist "docker-compose.quickstart.yml" (
    echo [ERRORE] Non trovo docker-compose.quickstart.yml in "%CD%".
    exit /b 1
)

echo Avvio dei container ^(db + migrate + api + dashboard^)...
echo La prima volta puo' richiedere 3-5 minuti per scaricare
echo e buildare le immagini. Le volte successive sara' pronto
echo in meno di 30 secondi.
echo.

docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app up -d --build
if errorlevel 1 (
    echo.
    echo [ERRORE] Avvio dei container fallito.
    echo Per vedere i log esegui in un nuovo prompt:
    echo   docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app logs
    exit /b 1
)

echo.
echo Attendo che l'API sia pronta ^(max 90 secondi^)...

set /a tries=0
:wait_api
set /a tries+=1
if %tries% GTR 45 goto api_timeout

REM Use curl when available (modern Windows 10/11 ships it). PowerShell is the
REM fallback. We do NOT rely on PowerShell alone because corporate execution
REM policies may block it.
where curl >nul 2>&1
if not errorlevel 1 (
    curl -fsS --max-time 2 http://localhost:8000/healthz >nul 2>&1
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'http://localhost:8000/healthz' -UseBasicParsing -TimeoutSec 2 ^| Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
)
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait_api
)

echo [OK] API risponde su http://localhost:8000

REM ---- Aspetta anche Streamlit ----------------------------------------------
set /a tries=0
:wait_streamlit
set /a tries+=1
if %tries% GTR 30 goto streamlit_ok

where curl >nul 2>&1
if not errorlevel 1 (
    curl -fsS --max-time 2 http://localhost:8501 >nul 2>&1
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'http://localhost:8501' -UseBasicParsing -TimeoutSec 2 ^| Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
)
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait_streamlit
)

:streamlit_ok
echo [OK] Dashboard pronta su http://localhost:8501
echo.

REM ---- Apri il browser ------------------------------------------------------
start "" "http://localhost:8501"

echo ===============================================
echo  Tutto pronto!
echo.
echo  Dashboard:  http://localhost:8501
echo  API docs:   http://localhost:8000/docs
echo.
echo  Per fermare tutto, doppio click su stop.bat
echo ===============================================
exit /b 0

:api_timeout
echo.
echo [AVVISO] L'API non risponde entro 90 secondi.
echo Per controllare cosa e' successo:
echo   docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app logs app
exit /b 1
