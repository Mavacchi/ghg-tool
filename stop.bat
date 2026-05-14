@echo off
setlocal

cd /d "%~dp0"

echo ===============================================
echo  Arresto GHG Tool
echo ===============================================
echo.

docker compose -f docker-compose.yml -f docker-compose.quickstart.yml down

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
echo   docker compose -f docker-compose.yml -f docker-compose.quickstart.yml down -v
echo.
pause
exit /b 0
