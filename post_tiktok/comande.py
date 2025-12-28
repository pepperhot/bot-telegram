async def start(update, _):
    if update.message:
        user = update.message.from_user
    elif update.effective_user:
        user = update.effective_user
    else:
        return
    await update.message.reply_text(f"Salut {user.first_name}, voici mon bot telegram! ")
    await update.message.reply_text("Commandes:\n    - /start : affiche ce message " \
    "\n    -/lyrics : format de tiktok karoucelle " \
    "\n    - /pallette : affiche les couleurs disponibles " \
    "\n    - /font : affiche les polices disponibles "
    "\n    -/karaoke : format de tiktok karaoke avec videos")
