@echo off
setlocal

echo ===============================================
echo  GHG Tool - Avvio in corso
 echo ===============================================
echo.

REM ---- Verifica Docker Desktop installato ----
docker --version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' installato.
    echo.
    echo Scaricalo da:  https://www.docker.com/products/docker-desktop/
    echo.
    echo Dopo l'installazione:
    echo   1. Apri Docker Desktop dal menu Start
    echo   2. Aspetta che l'icona della balena diventi stabile
    echo   3. Rilancia questo file start.bat con doppio click
    echo.
    pause
    exit /b 1
)

REM ---- Verifica che il daemon stia girando ----
docker ps >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' in esecuzione.
    echo.
    echo Apri Docker Desktop dal menu Start, aspetta che parta
    echo del tutto (icona balena nella tray di sistema), poi
    echo rilancia questo file start.bat.
    echo.
    pause
    exit /b 1
)

echo [OK] Docker Desktop in esecuzione.
echo.

REM ---- Sposta cwd nella cartella di questo script ----
cd /d "%~dp0"

REM ---- Verifica presenza file compose ----
if not exist "docker-compose.yml" (
    echo [ERRORE] Non trovo docker-compose.yml in questa cartella.
    echo Assicurati di aver scaricato l'intero progetto da GitHub
    echo e di aver scompattato lo ZIP correttamente.
    echo.
    pause
    exit /b 1
)

echo Avvio dei container (db + migrate + api + dashboard)...
echo La prima volta puo' richiedere 3-5 minuti per scaricare
echo e buildare le immagini. Le volte successive sara' pronto
echo in meno di 30 secondi.
echo.

docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app up -d --build

if errorlevel 1 (
    echo.
    echo [ERRORE] Avvio fallito.
    echo Per vedere i log:
    echo   docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app logs
    echo.
    pause
    exit /b 1
)

echo.
echo Attendo che l'API sia pronta (max 90 secondi)...

set /a tries=0
:wait_api
set /a tries+=1
if %tries% gtr 45 goto api_timeout

powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:8000/health' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait_api
)

echo [OK] API risponde su http://localhost:8000

REM ---- Aspetta anche Streamlit ----
set /a tries=0
:wait_streamlit
set /a tries+=1
if %tries% gtr 30 goto streamlit_ok

powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://localhost:8501' -UseBasicParsing -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    goto wait_streamlit
)

:streamlit_ok
echo [OK] Dashboard pronta su http://localhost:8501
echo.

REM ---- Apri il browser ----
start "" "http://localhost:8501"

echo ===============================================
echo  Tutto pronto!
echo.
echo  Dashboard:  http://localhost:8501
echo  API docs:   http://localhost:8000/docs
echo.
echo  Per fermare tutto, doppio click su stop.bat
 echo ===============================================
echo.
echo Premi un tasto per chiudere questa finestra.
pause >nul
exit /b 0

:api_timeout
echo.
echo [AVVISO] L'API non risponde entro 90 secondi.
echo Per controllare cosa e' successo:
echo   docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app logs app
echo.
pause
exit /b 1
