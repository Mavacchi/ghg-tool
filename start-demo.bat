@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM start-demo.bat — variante DEMO di start.bat.
REM
REM Accende l'override docker-compose.quickstart.yml che attiva:
REM   - seed automatico dei CSV in data\raw\
REM   - utente demo/demo gia creato (ruolo editor)
REM   - banner sticky "DEMO MODE" sempre visibile
REM
REM Tutto il resto e' identico a start.bat (stessi check Docker, stesso wait
REM su API + Streamlit, stesso apri-browser finale).
REM ---------------------------------------------------------------------------

echo.
echo ===============================================
echo  GHG Tool - Avvio in modalita' DEMO
echo ===============================================
echo.

call :main
set "_exit_code=%ERRORLEVEL%"

echo.
echo -----------------------------------------------
if "%_exit_code%"=="0" (
    echo  Avvio DEMO completato.
) else (
    echo  Avvio terminato con errori ^(codice %_exit_code%^).
    echo  Leggi i messaggi sopra per capire cosa e' andato storto.
)
echo -----------------------------------------------
echo.
echo Premi un tasto per chiudere questa finestra...
pause >nul
endlocal & exit /b %_exit_code%


:main

cd /d "%~dp0" || (
    echo [ERRORE] Impossibile cambiare directory in "%~dp0".
    exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' installato ^(comando 'docker' non trovato^).
    echo.
    echo Scaricalo da:  https://www.docker.com/products/docker-desktop/
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Docker Desktop non e' in esecuzione.
    echo Apri Docker Desktop dal menu Start e aspetta che parta.
    exit /b 1
)

docker compose version >nul 2>&1
if errorlevel 1 (
    echo [ERRORE] Plugin 'docker compose' v2 non disponibile.
    echo Aggiorna Docker Desktop.
    exit /b 1
)

echo [OK] Docker Desktop in esecuzione.
echo.

if not exist "docker-compose.yml" (
    echo [ERRORE] docker-compose.yml mancante in "%CD%".
    exit /b 1
)
if not exist "docker-compose.quickstart.yml" (
    echo [ERRORE] docker-compose.quickstart.yml mancante in "%CD%".
    exit /b 1
)

echo Avvio dei container in modalita' DEMO ^(db + migrate + api + dashboard^)...
echo La prima volta puo' richiedere 3-5 minuti per scaricare le immagini.
echo.
echo NOTA: in modalita' DEMO il login 'demo / demo' e' attivo e i dati di
echo esempio sono precaricati. Per la modalita' PRODUCTION usa start.bat.
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

start "" "http://localhost:8501"

echo ===============================================
echo  Tutto pronto - modalita' DEMO!
echo.
echo  Dashboard:  http://localhost:8501
echo  Login:      demo / demo
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
