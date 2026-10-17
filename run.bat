@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Preparando o ambiente pela primeira vez...
  python -m venv .venv || goto :erro
)
rem Reinstala as dependencias quando o requirements.txt muda.
fc /b requirements.txt .venv\requirements.instalado >nul 2>&1
if errorlevel 1 (
  echo Instalando dependencias...
  .venv\Scripts\python.exe -m pip install -q -r requirements.txt || goto :erro
  copy /y requirements.txt .venv\requirements.instalado >nul
)
start "" .venv\Scripts\pythonw.exe -m tracofirme %*
exit /b 0
:erro
echo Falha ao preparar o ambiente. Verifique se o Python 3.10+ esta instalado.
pause
