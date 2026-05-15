@echo off
setlocal

cd /d "%~dp0"

echo ===============================================
echo  Arresto GHG Tool
echo ===============================================
echo.

REM Ferma entrambe le configurazioni (production e quickstart) per essere
REM sicuro di abbattere tutti i container indipendentemente da come sono
REM stati avviati (start.bat vs start-demo.bat).
docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app down

if errorlevel 1 (
    echo.
    echo [ERRORE] Arresto fallito.
    pause
    exit /b 1
)

echo.
echo [OK] Tutti i servizi sono stati fermati.
echo I dati nel database restano salvati nel volume Docker 'ghg_pgdata'
echo e saranno ancora li' al prossimo avvio con start.bat.
echo.
echo Per cancellare anche i dati del database aggiungi -v:
echo   docker compose -f docker-compose.yml -f docker-compose.quickstart.yml --profile app down -v
echo.
pause
exit /b 0
