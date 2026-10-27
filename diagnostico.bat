@echo off
cd /d "%~dp0"
set "OUT=%~dp0diagnostico.txt"
echo DIAGNOSTICO PERFECT SHOCK DATA > "%OUT%"
echo Pasta: %cd% >> "%OUT%"
echo --- Windows --- >> "%OUT%"
ver >> "%OUT%"
echo --- arquivos --- >> "%OUT%"
if exist app.py (echo app.py: OK >> "%OUT%") else (echo app.py: NAO ENCONTRADO >> "%OUT%")
if exist requirements.txt (echo requirements.txt: OK >> "%OUT%") else (echo requirements.txt: NAO ENCONTRADO >> "%OUT%")
if exist data\perfect_shock.db (echo banco: OK >> "%OUT%") else (echo banco: nao encontrado - sera criado vazio >> "%OUT%")
echo --- python --- >> "%OUT%"
where py >> "%OUT%" 2>&1
py -3 --version >> "%OUT%" 2>&1
where python >> "%OUT%" 2>&1
python --version >> "%OUT%" 2>&1
echo --- porta 5000 --- >> "%OUT%"
netstat -ano | findstr ":5000" >> "%OUT%" 2>&1
echo --- ultimo log do iniciar --- >> "%OUT%"
if exist iniciar_log.txt type iniciar_log.txt >> "%OUT%"
echo.
echo Pronto. Envie o arquivo diagnostico.txt (nesta pasta) para suporte.
type "%OUT%"
pause
