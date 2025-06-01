@echo off

if not exist "bot_folder" (
    mkdir bot_folder
)
curl -H "Authorization: token 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" -L https://raw.githubusercontent.com/pepperhot/bot-telegram/main/bot.py -o bot_folder\bot.py
curl -H "Authorization: token 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" -L https://raw.githubusercontent.com/pepperhot/bot-telegram/main/.env -o bot_folder\.env
if not exist "bot_folder\.venv" (
    python -m venv bot_folder\.venv
)
call bot_folder\.venv\Scripts\activate.bat
pip install pillow requests beautifulsoup4 python-telegram-bot python-dotenv
python bot_folder\bot.py

pause
