import os

from dotenv import load_dotenv
from post_tiktok.lyrics import echo, button_handler, pallette, font_palette
from post_tiktok.karaoke import echo_karaoke, button_handler_karaoke
from post_tiktok.comande import start
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler


load_dotenv()
TOKEN = os.getenv("TOKEN")

def main():
    print("Bot started...")
    application = Application.builder().token(TOKEN).build()

    async def karaoke_cmd(update, context):
        await update.message.reply_text("🎤 Mode Karaoke activé ! Envoie artiste:titre ou un lien YouTube")
        context.user_data["karaoke_mode"] = True

    async def lyrics_cmd(update, context):
        context.user_data["karaoke_mode"] = False
        await update.message.reply_text("📝 Mode Lyrics activé ! Envoie artiste:titre")

    async def echo_global(update, context):
        if context.user_data.get("karaoke_mode", False):
            await echo_karaoke(update, context)
        else:
            await echo(update, context)

    async def callback_router(update, context):
        """Route les callbacks selon le mode actif"""
        if context.user_data.get("karaoke_mode", False):
            await button_handler_karaoke(update, context)
        else:
            await button_handler(update, context)

    # --- Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pallette", pallette))
    application.add_handler(CommandHandler("font", font_palette))
    application.add_handler(CommandHandler("karaoke", karaoke_cmd))
    application.add_handler(CommandHandler("lyrics", lyrics_cmd))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_global))

    # --- Lancement ---
    application.run_polling()

if __name__ == '__main__':
    main()