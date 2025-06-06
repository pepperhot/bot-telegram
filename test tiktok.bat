@echo off
setlocal enabledelayedexpansion

if not exist "bot_folder" (
    mkdir bot_folder
)

curl -L https://raw.githubusercontent.com/pepperhot/bot-telegram/refs/heads/main/bot.py?token=GHSAT0AAAAAADEYLXPXQ74H7E7EJX5OF3R42CC7I2Q -o bot_folder\bot.py
if %errorlevel% neq 0 exit /b

curl -L https://raw.githubusercontent.com/pepperhot/bot-telegram/refs/heads/main/.env?token=GHSAT0AAAAAADEYLXPXVQKLO4633ASQH2Z62CC7JLA -o bot_folder\.env
if %errorlevel% neq 0 exit /b

if not exist "bot_folder\.venv" (
    python -m venv bot_folder\.venv
    if %errorlevel% neq 0 exit /b
)

call bot_folder\.venv\Scripts\activate.bat

bot_folder\.venv\Scripts\python.exe -m pip install --upgrade pip
bot_folder\.venv\Scripts\python.exe -m pip install pillow requests beautifulsoup4 python-telegram-bot python-dotenv

bot_folder\.venv\Scripts\python.exe bot_folder\bot.py

pause
