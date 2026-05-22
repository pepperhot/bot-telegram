import os

from dotenv import load_dotenv
from post_tiktok.lyrics import echo, button_handler, pallette, font_palette
from post_tiktok.karaoke import echo_karaoke, button_handler_karaoke, echo_wordbyword, button_handler_wordbyword
from post_tiktok.comande import start
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler


load_dotenv()
TOKEN = os.getenv("TOKEN")

def main():
    print("Bot started...")
    application = Application.builder().token(TOKEN).build()

    async def karaoke_cmd(update, context):
        await update.message.reply_text("🎤 Mode Karaoke activé ! Envoie artiste:titre ou un lien YouTube")
        context.user_data["mode"] = "karaoke"

    async def lyrics_cmd(update, context):
        context.user_data["mode"] = "lyrics"
        await update.message.reply_text("📝 Mode Lyrics activé ! Envoie artiste:titre")

    async def wordbyword_cmd(update, context):
        context.user_data["mode"] = "wordbyword"
        await update.message.reply_text("✨ Mode Word-by-Word activé ! Envoie artiste:titre ou un lien YouTube")

    async def echo_global(update, context):
        mode = context.user_data.get("mode", "lyrics")
        if mode == "karaoke":
            await echo_karaoke(update, context)
        elif mode == "wordbyword":
            await echo_wordbyword(update, context)
        else:
            await echo(update, context)

    async def callback_router(update, context):
        data = update.callback_query.data if update.callback_query else ""
        pending = context.user_data.get("pending_callback")
        if data.startswith("wbw_"):
            await button_handler_wordbyword(update, context)
        elif pending == "karaoke" or (pending is None and context.user_data.get("mode") == "karaoke"):
            await button_handler_karaoke(update, context)
        else:
            await button_handler(update, context)

    # --- Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pallette", pallette))
    application.add_handler(CommandHandler("font", font_palette))
    application.add_handler(CommandHandler("karaoke", karaoke_cmd))
    application.add_handler(CommandHandler("lyrics", lyrics_cmd))
    application.add_handler(CommandHandler("wordbyword", wordbyword_cmd))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_global))

    # --- Lancement ---
    application.run_polling()

if __name__ == '__main__':
    main()