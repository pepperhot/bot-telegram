from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
from bs4 import BeautifulSoup
import urllib.parse
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
import os
import textwrap
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")
user_colors = {}

color_map = {
    "🔵 Bleu": (11, 38, 117),
    "🔴 Rouge": (179, 38, 30),
    "⚪ blanc": (210, 210, 210),
    "🟣 Violet": (120, 81, 169)
}

def edit(x: str) -> str:
    return "".join(c for c in x if c not in "éèêëàâôûùçîïô.;/:’,?\"'()[]<>|\\~@-#$%^&*+=_ ").lower()

def split_message(user_message: str):
    colors = list(color_map.keys())
    if user_message in colors:
        return False, None, None, user_message

    parts = user_message.split(":")
    if len(parts) != 2:
        return "Erreur, format attendu : artiste:titre", None, None, None

    artist, song = parts[0].strip(), parts[1].strip()
    return True, edit(song), edit(artist), song

def parole(song, artist):
    url = f'https://www.azlyrics.com/lyrics/{artist}/{song}.html'
    try:
        response = requests.get(url)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            divs = soup.find_all("div")
            for div in divs:
                if not div.get("class") and div.get_text(strip=True):
                    lyrics_raw = div.get_text(separator='\n').strip()
                    if len(lyrics_raw.splitlines()) > 10:
                        lines = lyrics_raw.split('\n')
                        cleaned = [line.strip() for line in lines if line.strip() and "(feat." not in line and "Submit Corrections" not in line]
                        paroles = [line for line in cleaned if not (line.startswith('[') and line.endswith(':]'))]
                        return paroles
    except Exception as e:
        print(f"Erreur lors de la récupération des paroles: {e}")
    return None

def get_album_image(song: str, artist: str):
    query = urllib.parse.quote(f"{artist} {song} album cover")
    google_url = f"https://www.google.com/search?q={query}&tbm=isch"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        google_response = requests.get(google_url, headers=headers)
        if google_response.status_code == 200:
            soup = BeautifulSoup(google_response.text, 'html.parser')
            img_tags = soup.find_all("img")
            if len(img_tags) > 1:
                img_src = img_tags[1].get("src")
                if img_src and img_src.startswith("http"):
                    img_data = requests.get(img_src).content
                    return Image.open(BytesIO(img_data)).convert("RGB")
    except Exception as e:
        print(f"Erreur lors de la récupération de l'image: {e}")
    return None

def create_image(text, album_image, file, side='right', bg_color=(11, 38, 117)):
    base = Image.new("RGB", (1080, 1920), color=bg_color)
    draw = ImageDraw.Draw(base)

    album_resized = album_image.resize((600, 700))
    if side != 'right':
        half = album_resized.crop((300, 0, 600, 700))
        x_pos = 0
    else:
        half = album_resized.crop((0, 0, 300, 700))
        x_pos = 780
    base.paste(half, (x_pos, 575))

    font = ImageFont.truetype("arial.ttf", 40)

    wrapped_text = textwrap.fill(text, width=30)

    bbox = draw.textbbox((0, 0), wrapped_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    if side == 'right':
        text_x = (810 - text_width) // 2
    else:
        text_x = ((1080 - text_width) // 2) + 70

    text_y = ((1920 - text_height) // 2) - 100

    i = 2
    for dx in range(-i, i + 1):
        for dy in range(-i, i + 1):
            if dx != 0 or dy != 0:
                draw.multiline_text((text_x + dx, text_y + dy), wrapped_text, font=font, fill="black", spacing=10)

    draw.multiline_text((text_x, text_y), wrapped_text, font=font, fill="white", spacing=10)

    base.save(file)

async def start(update, context):
    await update.message.reply_text("Envoie-moi deux mots séparés par ' : '\nExemple : 'Sabrina Carpenter:Espresso'")

async def pallette(update, context):
    boutons = [
        [KeyboardButton("🔵 Bleu"), KeyboardButton("🔴 Rouge")],
        [KeyboardButton("⚪ blanc"), KeyboardButton("🟣 Violet")]
    ]
    clavier = ReplyKeyboardMarkup(
        keyboard=boutons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Crée ton tiktok !!"
    )
    await update.message.reply_text("Choisis ta couleur :", reply_markup=clavier)

def emoji_to_rgb(emoji: str):
    return color_map.get(emoji)

async def send_lyrics(update, context, index):
    lines = context.user_data.get("lyrics", [])
    if not lines:
        await update.message.reply_text("Aucune parole chargée.")
        return

    block = lines[index:index+2]
    text = "\n".join(block)

    keyboard = []
    nav_buttons = []

    if index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Retour", callback_data=f"back:{index}"))
    if index + 10 < len(lines):
        nav_buttons.append(InlineKeyboardButton("▶️ Suite", callback_data=f"next:{index}"))

    keyboard.append([InlineKeyboardButton("✅ Valider ce bloc", callback_data=f"select:{index}")])
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    action, current_index = query.data.split(":")
    current_index = int(current_index)

    if action == "next":
        new_index = current_index + 2
        context.user_data["index"] = new_index
        await send_lyrics(update, context, index=new_index)

    elif action == "back":
        new_index = max(0, current_index - 2)
        context.user_data["index"] = new_index
        await send_lyrics(update, context, index=new_index)

    elif action == "select":
        lines = context.user_data.get("lyrics", [])
        block = lines[current_index:current_index+10]
        if not block:
            await query.message.reply_text("Erreur : aucun bloc de paroles à cet index.")
            return
        text = "\n".join(block)
        user_id = query.from_user.id
        bg_color = user_colors.get(user_id, (11, 38, 117))
        titre = context.user_data.get("titre")
        artist = context.user_data.get("artist")
        song = context.user_data.get("song")
        album_image = get_album_image(titre, artist)

        if album_image is None:
            await query.message.reply_text("Erreur lors de la récupération de l'image.")
            return

        create_image(text, album_image, "img2.jpg", side='left', bg_color=bg_color)
        create_image(song, album_image, "img1.jpg", side='right', bg_color=bg_color)

        with open("img1.jpg", "rb") as img1:
            await query.message.reply_photo(photo=img1)
        with open("img2.jpg", "rb") as img2:
            await query.message.reply_photo(photo=img2)
        os.remove("img1.jpg")
        os.remove("img2.jpg")
        await query.message.reply_text(f"{song} || {artist}\n#lyrics_songs #playback #fyp #trend #foryou #{titre} #{artist}")

async def echo(update, context):
    user = update.message.from_user
    user_id = user.id
    user_message = update.message.text
    first_name = user.first_name or "Inconnu"

    choose_line, titre, artist, song = split_message(user_message)
    message = f"🔍 {first_name} ({user_id}) → {user_message} couleur : {next((k for k, v in color_map.items() if v == user_colors.get(user_id)), '🔵 Bleu')}"
    print(message+(80-len(message))*" ", end="")

    if choose_line == "Erreur, format attendu : artiste:titre":
        print("❌ Tentative échouée")
        await update.message.reply_text(choose_line)
        return

    if choose_line is False:
        user_colors[user_id] = emoji_to_rgb(song)
        await update.message.reply_text(f"🎨 Tu as choisi la couleur {song} !")
        return
    
    all_lines = parole(titre, artist)
    if not all_lines:
        await update.message.reply_text("Paroles introuvables.")
        print("❌ Tentative échouée")
        return

    print("✅ Tentative réussie")
    context.user_data["lyrics"] = all_lines
    context.user_data["index"] = 0
    context.user_data["titre"] = song
    context.user_data["artist"] = artist
    context.user_data["song"] = song

    await send_lyrics(update, context, index=0)

def main():
    print("Bot started...")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pallette", pallette))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == '__main__':
    main()