@echo off
setlocal
cd /d "%~dp0"
title PERFECT Shock Data
set "LOG=%~dp0iniciar_log.txt"
echo === %date% %time% === > "%LOG%"
echo Pasta: %cd% >> "%LOG%"
if not exist "app.py" goto sem_pasta

set "PY="
py -3 --version >> "%LOG%" 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto achou
python --version >> "%LOG%" 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto achou
goto sem_python

:achou
echo Python encontrado: %PY%
echo Python: %PY% >> "%LOG%"
if exist ".venv\Scripts\python.exe" goto venv_ok
echo Criando ambiente (.venv)...
%PY% -m venv .venv >> "%LOG%" 2>&1
if not exist ".venv\Scripts\python.exe" goto erro_venv

:venv_ok
echo Instalando/verificando dependencias (na 1a vez precisa de internet)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --prefer-binary -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 goto erro_pip
echo.
echo Abrindo http://127.0.0.1:5000  (feche esta janela para encerrar o sistema)
start "" /min cmd /c "ping -n 4 127.0.0.1 >nul & start http://127.0.0.1:5000"
".venv\Scripts\python.exe" app.py
echo.
echo O sistema parou. Leia a mensagem acima.
pause
exit /b 0

:sem_pasta
echo.
echo ARQUIVOS NAO ENCONTRADOS nesta pasta.
echo Extraia o ZIP inteiro (botao direito - Extrair tudo) e execute o iniciar.bat de dentro da pasta extraida.
pause
exit /b 1

:sem_python
echo.
echo O PYTHON NAO ESTA INSTALADO. O Windows so tem o atalho da Microsoft Store, que nao funciona.
echo.
where winget >nul 2>nul
if errorlevel 1 goto manual
choice /c SN /m "Instalar o Python agora automaticamente (winget)"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
echo.
echo Concluido. FECHE esta janela e de dois cliques em iniciar.bat novamente.
pause
exit /b 0

:manual
echo Instale em https://www.python.org/downloads/  e MARQUE a caixa "Add python.exe to PATH".
echo Depois feche esta janela e execute o iniciar.bat de novo.
pause
exit /b 1

:erro_venv
echo.
echo NAO FOI POSSIVEL CRIAR O AMBIENTE PYTHON. Detalhes:
type "%LOG%"
echo.
echo Envie o arquivo iniciar_log.txt (desta pasta) para suporte.
pause
exit /b 1

:erro_pip
echo.
echo FALHA AO INSTALAR AS DEPENDENCIAS (verifique a internet, proxy ou antivirus). Detalhes:
powershell -NoProfile -Command "Get-Content -Tail 15 '%LOG%'"
echo.
echo Envie o arquivo iniciar_log.txt (desta pasta) para suporte.
pause
exit /b 1
