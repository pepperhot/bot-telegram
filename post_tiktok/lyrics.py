import os, textwrap, requests, urllib.parse, datetime

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

user_colors = {}
color_map = {
    "🔵 Bleu": (11, 38, 117),
    "🔴 Rouge": (179, 38, 30),
    "⚪ blanc": (255, 255, 255),
    "🟣 Violet": (120, 81, 169)
}

def edit(x):
    return "".join(c for c in x if c not in "ÀÃéèêëàâôûùçîïô.;/:,?!\"'()[]<>|\\~@#$%^&*+=_ ").lower()

def split_message(message):
    colors = list(color_map.keys())
    if message in colors:
        return False, None, None, message

    parts = message.split(":")
    if len(parts) != 2:
        return "Erreur, format attendu : artiste:titre", None, None, None

    artist, song = parts[0], parts[1]
    return True, edit(song), edit(artist), song

def parole(song, artist):
    url = f'https://www.azlyrics.com/lyrics/{artist}/{song}.html'
    try:
        response = requests.get(url)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            for div in BeautifulSoup(response.text, 'html.parser').find_all("div"):
                if not div.get("class") and div.get_text(strip=True):
                    lyrics_raw = div.get_text(separator='\n')
                    if len(lyrics_raw.splitlines()) > 10:
                        result = [textwrap.wrap(line, width=30)for line in [line for line in lyrics_raw.split('\n') if line and "(feat." not in line and "Submit Corrections" not in line and not (line.startswith('[') and line.endswith(']'))]]
                        return result
    except Exception as e:
        print(f"❌ Erreur lors de la récupération des paroles: {e}")
    return None

def get_album_cover(artist, song):
    query = f"{artist} {song}"

    # --------------iTunes--------------
    try:
        url = f"https://itunes.apple.com/search?term={requests.utils.quote(query)}&media=music&limit=1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) > 0:
            img_url = data["results"][0]["artworkUrl100"].replace("100x100", "1200x1200")
            img_data = requests.get(img_url).content
            return Image.open(BytesIO(img_data)), f"   iTunes Image: {img_url}"
    except Exception as e:
        print(f"❌ iTunes failed: {e}")

    # --------------azlyrics--------------
    try:
        az_url = f"https://www.azlyrics.com/lyrics/{artist}/{song}.html"
        response = requests.get(az_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        img_tag = soup.find('img', {'class': 'album-image'})
        if img_tag and 'src' in img_tag.attrs:
            img_url = "https://www.azlyrics.com/" + img_tag['src']
            img_data = requests.get(img_url).content
            return Image.open(BytesIO(img_data)), f"   azlyrics Image: {img_url}"
    except Exception as e:
        print(f"❌ AZLyrics failed: {e}")

    # --------------Google--------------
    try:
        search_query = urllib.parse.quote(f"{artist} {song} album cover")
        google_url = f"https://www.google.com/search?q={search_query}&tbm=isch"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(google_url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        img_tags = soup.find_all("img")
        if len(img_tags) > 1:
            img_src = img_tags[1].get("src")
            if img_src and img_src.startswith("http"):
                return Image.open(BytesIO(requests.get(img_src).content)), f"   Google Image: {img_src}"
    except Exception as e:
        print(f"❌ Google Images failed: {e}")
    
    print("❌ Aucune image d'album trouvée")
    return None, None

def create_image(text, album_image, file, side='right', bg_color=(11, 38, 117)):
    W, H = 1082, 1919
    base = Image.new("RGB", (W, H), color=bg_color)
    draw = ImageDraw.Draw(base)
    album_resized = album_image.resize((600, 600), Image.LANCZOS)

    half = album_resized.crop((0, 0, 302, 600)) if side == 'right' else album_resized.crop((300, 0, 600, 600))
    x_pos = 780 if side == 'right' else 0

    base.paste(half, (x_pos, H // 2 - 270))

    font = ImageFont.truetype("arial.ttf", 50)
    wrapped_text = text
    bbox = draw.multiline_textbbox((0, 0), wrapped_text, font=font, spacing=10)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    text_x = ((W - 300 - text_width) // 2) if side == 'right' else ((W - 300 - text_width) // 2) + 300
    text_y = H // 2 - text_height // 2

    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx or dy:
                draw.multiline_text((text_x + dx, text_y + dy), wrapped_text, font=font, fill="black", spacing=10)

    draw.multiline_text((text_x, text_y), wrapped_text, font=font, fill="black" if bg_color == (255, 255, 255) else "white", spacing=10)

    base.save(file)

def log_attempt(first_name, user_id, message, result, color):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   🎨 Couleur : {color}")
    print(f"   {"✅" if result else "❌"} Résultat : {'Succès' if result else 'Échec'}")
    if result:
        _, titre, artist, _ = split_message(message)
        _, url = get_album_cover(titre, artist)
        if url:
            print(url)
    print(50 * "-")
    
async def pallette(update, _):
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

async def send_lyrics(update, context, index):
    lines = context.user_data.get("lyrics", [])
    if not lines:
        await update.message.reply_text("Aucune parole chargée.")
        return

    block = lines[index:index+2]
    text = "\n".join(block[i] if isinstance(block[i], str) else " ".join(block[i]) for i in range(len(block)))

    keyboard = []
    nav_buttons = []

    if index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Retour", callback_data=f"back:{index}"))
    if index + 2 < len(lines):
        nav_buttons.append(InlineKeyboardButton("▶️ Suite", callback_data=f"next:{index}"))

    keyboard.append([InlineKeyboardButton("✅ Valider ce bloc", callback_data=f"select:{index}")])
    if nav_buttons:
        keyboard.append(nav_buttons)

    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup)
    except Exception as e:
        print(f"❌ Erreur affichage lyrics: {e}")

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
        block = lines[current_index:current_index+15]
        if not block:
            await query.message.reply_text("Erreur : aucun bloc de paroles à cet index.")
            return
        
        text = text = "\n".join(line for sublist in block for line in sublist)

        user_id = query.from_user.id
        bg_color = user_colors.get(user_id, (11, 38, 117))
        titre = context.user_data.get("titre")
        artist = context.user_data.get("artist")
        song = context.user_data.get("song")
        album_image, _ = get_album_cover(titre, artist)

        if album_image is None:
            await query.message.reply_text("❌ Erreur lors de la récupération de l'image.")
            return

        try:
            create_image(text, album_image, "img2.jpg", side='left', bg_color=bg_color)
            create_image(song, album_image, "img1.jpg", side='right', bg_color=bg_color)

            with open("img1.jpg", "rb") as img1:
                await query.message.reply_photo(photo=img1, read_timeout=300, write_timeout=300, connect_timeout=300)
            with open("img2.jpg", "rb") as img2:
                await query.message.reply_photo(photo=img2, read_timeout=300, write_timeout=300, connect_timeout=300)

            os.remove("img1.jpg")
            os.remove("img2.jpg")
            
            await query.message.reply_text(f"{song} || {artist}\n#lyrics_songs #fyp #pourtoi #{song} #{artist}")
        except Exception as e:
            print(f"❌ Erreur création/envoi images: {e}")
            await query.message.reply_text("❌ Erreur lors de la création des images")

async def echo(update, context):
    user = update.message.from_user
    user_id = user.id
    message = update.message.text
    first_name = user.first_name or "Inconnu"

    choose_line, titre, artist, song = split_message(message)
    color_name = next((k for k, v in color_map.items() if v == user_colors.get(user_id)), '🔵 Bleu')

    if choose_line == "Erreur, format attendu : artiste:titre":
        log_attempt(first_name, user_id, message, False, color_name, type="lyrics")
        await update.message.reply_text(choose_line)
        return

    if choose_line is False:
        user_colors[user_id] = color_map.get(song)
        await update.message.reply_text(f"🎨 Tu as choisi la couleur {song} !")
        return

    all_lines = parole(titre, artist)
    result = all_lines is not None
    log_attempt(first_name, user_id, message, result, color_name, type="lyrics")

    if not result:
        return

    context.user_data["lyrics"] = all_lines
    context.user_data["index"] = 0
    context.user_data["titre"] = song
    context.user_data["artist"] = artist
    context.user_data["song"] = song

    await send_lyrics(update, context, index=0)
