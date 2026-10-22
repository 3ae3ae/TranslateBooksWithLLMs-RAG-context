@echo off
echo ============================================
echo   Prompt Optimizer - Verification Prerequis
echo ============================================
echo.

REM Verifier Python
echo [1/3] Verification de Python...
uv run python --version >nul 2>&1
if errorlevel 1 (
    echo   [ERREUR] Python n'est pas installe ou pas dans le PATH
    goto :error
) else (
    uv run python --version
    echo   [OK] Python trouve
)
echo.

REM Verifier les dependances Python
echo [2/3] Verification des dependances Python...
uv run python -c "import yaml" >nul 2>&1
if errorlevel 1 (
    echo   [MANQUANT] pyyaml - Installation: uv sync
    set MISSING_DEPS=1
) else (
    echo   [OK] pyyaml
)

uv run python -c "import dotenv" >nul 2>&1
if errorlevel 1 (
    echo   [MANQUANT] python-dotenv - Installation: uv sync
    set MISSING_DEPS=1
) else (
    echo   [OK] python-dotenv
)

uv run python -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo   [MANQUANT] requests - Installation: uv sync
    set MISSING_DEPS=1
) else (
    echo   [OK] requests
)
echo.

REM Verifier le fichier .env
echo [3/3] Verification du fichier .env...
if exist "..\..\.env" (
    echo   [OK] .env trouve
) else (
    if exist "..\.env" (
        echo   [OK] .env trouve
    ) else (
        echo   [ERREUR] .env non trouve - Creez-le a la racine du projet
        goto :error
    )
)
echo.

if defined MISSING_DEPS (
    echo ============================================
    echo   Des dependances sont manquantes!
    echo   Executez: uv sync
    echo ============================================
) else (
    echo ============================================
    echo   Tous les prerequis sont satisfaits!
    echo   Vous pouvez lancer l'optimisation.
    echo ============================================
)
echo.
pause
exit /b 0

:error
echo.
echo Corrigez les erreurs ci-dessus avant de continuer.
pause
exit /b 1
