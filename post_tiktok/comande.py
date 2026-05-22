async def start(update, _):
    if not update.message:
        return
    user = update.message.from_user or update.effective_user
    if not user:
        return
    await update.message.reply_text(f"Salut {user.first_name}, voici mon bot telegram! ")
    await update.message.reply_text("Commandes:\n    - /start : affiche ce message " \
    "\n    - /lyrics : format de tiktok carrousel " \
    "\n    - /pallette : affiche les couleurs disponibles " \
    "\n    - /font : affiche les polices disponibles " \
    "\n    - /karaoke : format de tiktok karaoke avec videos" \
    "\n    - /wordbyword : format mot par mot synchronisé")
