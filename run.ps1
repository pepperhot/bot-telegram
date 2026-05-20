# Script de lancement du bot Telegram
# Utilise automatiquement le venv

# Arrête toute instance de Python du bot
Write-Host "🛑 Arrêt des instances existantes..." -ForegroundColor Yellow
Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*bot-telegram*" } | Stop-Process -Force -ErrorAction SilentlyContinue

# Petit délai pour être sûr
Start-Sleep -Seconds 2

# Vérifie que le venv existe
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "❌ Le venv n'existe pas. Création en cours..." -ForegroundColor Red
    python3 -m venv .venv
    .\.venv\Scripts\pip.exe install --upgrade python-telegram-bot beautifulsoup4 requests Pillow python-dotenv
}

# Lance le bot avec le venv
Write-Host "🤖 Démarrage du bot..." -ForegroundColor Green
& ".\.venv\Scripts\python.exe" ".\main.py"
