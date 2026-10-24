@echo off
setlocal
chcp 65001 >nul

echo ===================================================
echo     Compilador Automatizado de Balisco (.exe)
echo ===================================================
echo.

cd /d "%~dp0\.."

echo [1/3] Verificando dependencias...
python -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo [!] PyInstaller no encontrado. Instalando dependencias de build...
    python -m pip install -e ".[build]"
)

echo [2/3] Compilando ejecutable e instalador oficial...
python scripts\build_installer.py
if %errorlevel% neq 0 (
    echo.
    echo [X] Error durante la creacion del instalador.
    pause
    exit /b %errorlevel%
)

echo.
echo [3/3] ¡Instalador generado con exito!
echo Ubicacion: dist\BaliscoSetup.exe
echo.
echo ===================================================
pause
