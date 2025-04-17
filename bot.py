from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
from bs4 import BeautifulSoup
import urllib.parse
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram import ReplyKeyboardMarkup, KeyboardButton
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
def c(x):
    return "".join([c for c in x if c not in "éèêëàâôûùçîïô.;/:’,!?\"'()[]<>|\\~@#$%^&*+=_ "]).lower()

def split_message(user_message: str):
    colors = ["🔵 Bleu", "🔴 Rouge", "⚪ blanc", "🟣 Violet"]
    if user_message in colors:
        return None, None, user_message
    words = user_message.split(":")
    if len(words) != 2:
        return "Erreur, format attendu : artiste:titre", "", "" 
    song = words[1]
    words = [w.lower().replace(" ", "") for w in words]
    return c(song), c(words[0]), song

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
                        snippet = "\n".join(cleaned[:10])
                        paroles = [textwrap.fill(line, 30) for line in snippet.split('\n')]
                        return '\n'.join(paroles)
    except Exception as e:
        print(f"Erreur lors de la récupération des paroles: {e}")
    return None


def get_album_image(song, artist):
    url = f"https://www.azlyrics.com/lyrics/{artist}/{song}.html"
    try:
# ------------------------azlyrics Images--------------- #
        response = requests.get(url)
        if response.status_code == 200:
            album_img_tag = BeautifulSoup(response.text, 'html.parser').find('img', {'class': 'album-image'})
            
            if album_img_tag and 'src' in album_img_tag.attrs:
                img_url = "https://www.azlyrics.com/" + album_img_tag['src']
                img_data = requests.get(img_url).content
                return Image.open(BytesIO(img_data))
# ------------------------Google Images--------------- #
        query = urllib.parse.quote(f"{artist} {song} album cover")
        google_url = f"https://www.google.com/search?q={query}&tbm=isch"
        headers = {"User-Agent": "Mozilla/5.0"}
        google_response = requests.get(google_url, headers=headers)
        if google_response.status_code == 200:
            soup = BeautifulSoup(google_response.text, 'html.parser')
            img_tags = soup.find_all("img")
            
            if len(img_tags) > 1:
                img_src = img_tags[1].get("src")
                if img_src and img_src.startswith("http"):
                    return Image.open(BytesIO(requests.get(img_src).content))
    except Exception as e:
        print(f"Erreur lors de la récupération de l'image: {e}")
    return None


def create_image(text, album_image, file, side='right',bg_color=(11, 38, 117)):
    base = Image.new("RGB", (1080, 1920), color=bg_color)
    draw = ImageDraw.Draw(base)
# ---------------creation album--------------- #
    album = album_image.resize((600, 700))
    half = album.crop((0, 0, 300, 700)) if side == 'right' else album.crop((300, 0, 600, 700))
    x_pos = 780 if side == 'right' else 0
    base.paste(half, (x_pos, 575))
# ---------------creation texte--------------- #
    font = ImageFont.truetype("arial.ttf", 40)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = ((810-(len(text)*25))//2) if side == 'right' else ((1080 - text_width) // 2) + 70
    text_y = ((1920 - text_height) // 2  ) -100
# ---------------creation police--------------- #
    i = 2
    for dx in range(-i, i + 1):
        for dy in range(-i, i + 1):
            if dx != 0 or dy != 0:
                draw.multiline_text((text_x + dx, text_y + dy), text, font=font, fill="black", spacing=10)
    draw.multiline_text((text_x, text_y), text, font=font, fill="white", spacing=10)

    base.save(file)

async def start(update, context):
    await update.message.reply_text("Envoie-moi deux mots séparés par ' : ' \nexemple: 'Sabrina Carpenter:Espresso")

async def pallette(update, context):
    boutons = [
        [KeyboardButton("🔵 Bleu"), KeyboardButton("🔴 Rouge")],
        [KeyboardButton("⚪ blanc"), KeyboardButton("🟣 Violet")]
    ]
    clavier = ReplyKeyboardMarkup(
        keyboard=boutons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Creer ton tiktok!!"
    )
    await update.message.reply_text(
        "Choisis ta couleur :", 
        reply_markup=clavier
    )

def emoji_to_rgb(emoji):
    return color_map.get(emoji)

async def echo(update, context):
    user = update.message.from_user
    user_id = user.id
    first_name = user.first_name

    user_message = update.message.text
    titre, artist, song = split_message(user_message)
    paroles_text = parole(titre, artist)
    album_image = get_album_image(titre, artist)
    
    if titre is None and artist is None:
        user_colors[user_id] = emoji_to_rgb(song)
        await update.message.reply_text(f"🎨 Tu as choisi la couleur {song} !")
        return

    else:
        message = f"🔍 {first_name} ({user_id}) → {user_message} couleur : {next((k for k, v in color_map.items() if v == user_colors.get(user_id)), '🔵 Bleu')}"
        print(message+(80-len(message))*" ", end="")
        if paroles_text and album_image:
            bg_color = user_colors.get(user_id, (11, 38, 117))
            create_image(paroles_text, album_image, "img2.jpg", side='left', bg_color=bg_color)
            create_image(song, album_image, "img1.jpg", side='right', bg_color=bg_color)

            with open("img1.jpg", "rb") as img1:
                await update.message.reply_photo(photo=img1)
            with open("img2.jpg", "rb") as img2:
                await update.message.reply_photo(photo=img2)
            
            os.remove("img1.jpg")
            os.remove("img2.jpg")
            print("✅ Tentative réussie")
            await update.message.reply_text(f"{song} || {artist}\n#lyrics_songs#playback#fyp#trend#foryou#{titre}#{artist}")
        else:
            print("❌ Tentative échouée")
            await update.message.reply_text("Erreur lors de la récupération des paroles ou de l'image.")

def main():
    print("Bot started...")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pallette", pallette))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.run_polling()
    

if __name__ == '__main__':
    main()