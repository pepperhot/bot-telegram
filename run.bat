@echo off
REM Script de lancement du bot Telegram (Windows Batch)

echo 🛑 Arrêt des instances existantes...
taskkill /F /IM python.exe /T 2>nul

REM Petit délai
timeout /t 2 /nobreak

REM Lance le bot avec le venv
echo 🤖 Démarrage du bot...
.\.venv\Scripts\python.exe ".\main.py"

pause
