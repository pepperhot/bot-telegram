import textwrap, requests, urllib.parse, datetime, random, math, asyncio, re, unicodedata
from functools import partial

from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageChops
from bs4 import BeautifulSoup
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

user_colors = {}
user_fonts = {}

# Pre-calculate translation table for edit function
REMOVE_CHARS = "ÀÃéèêëàâôûùçîïô.;/:,?!\"'()[]<>|\\~@#$%^&*+=_ "
TRANSLATION_TABLE = str.maketrans('', '', REMOVE_CHARS)

color_map = {
    "🔵 Bleu": (11, 38, 117),
    "⚫ Metal": (15, 15, 15),
    "⚪ blanc": (255, 255, 255),
    "🏖️ Plage": (255, 165, 0)
}

font_map = {
    "Arial": "arial.ttf",
    "Angel Wish": "font/Angel wish.ttf",
    "Slow Play": "font/Slow Play.ttf"
}

async def run_blocking(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))

def edit(x):
    return x.translate(TRANSLATION_TABLE).lower()

def split_message(message):
    colors = list(color_map.keys())
    fonts = list(font_map.keys())

    if message in colors:
        return "COLOR", None, None, message
    
    if message in fonts:
        return "FONT", None, None, message

    parts = message.split(":")
    if len(parts) != 2:
        return "Erreur, format attendu : artiste:titre", None, None, None

    artist, song = parts[0], parts[1]
    return True, edit(song), artist, song

_AZ_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

_album_cache: dict = {}
_ALBUM_CACHE_MAX = 50

_GENIUS_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in s if unicodedata.category(c) != "Mn"))

def _genius_get_lyrics(artist, song):
    try:
        q = urllib.parse.quote(f"{artist} {song}")
        r = requests.get(
            f"https://genius.com/api/search/multi?per_page=5&q={q}",
            headers=_GENIUS_HEADERS, timeout=10
        )
        if r.status_code != 200:
            return None

        song_norm = _norm(song)
        url = None
        for section in r.json().get("response", {}).get("sections", []):
            for hit in section.get("hits", []):
                if hit.get("type") != "song":
                    continue
                res = hit.get("result", {})
                title_norm = _norm(res.get("title", ""))
                if song_norm in title_norm or title_norm in song_norm:
                    url = res.get("url")
                    break
            if url:
                break

        if not url:
            return None

        r2 = requests.get(url, headers=_GENIUS_HEADERS, timeout=10)
        soup = BeautifulSoup(r2.text, "html.parser")
        containers = soup.find_all("div", attrs={"data-lyrics-container": "true"})
        if not containers:
            return None

        lines = []
        for c in containers:
            for br in c.find_all("br"):
                br.replace_with("\n")
            text = c.get_text(separator="")
            text = re.sub(r"^.*?\[Paroles de [^\]]+\]\n*", "", text, flags=re.DOTALL)
            text = re.sub(r"^.*? Lyrics\n*", "", text, flags=re.DOTALL)
            for line in text.split("\n"):
                line = re.sub(r'\([^)]*\)', '', line).strip()
                if not line or (line.startswith("[") and line.endswith("]")):
                    continue
                lines.append(line)

        return lines if lines else None
    except Exception as e:
        print(f"❌ Genius fallback error: {e}")
        return None

def _azlyrics_get_lyrics(song, artist):
    url = f"https://www.azlyrics.com/lyrics/{edit(artist)}/{song}.html"
    try:
        response = requests.get(url, headers=_AZ_HEADERS, timeout=10)
        response.encoding = "utf-8"
        if response.status_code == 200:
            for div in BeautifulSoup(response.text, "html.parser").find_all("div"):
                if not div.get("class") and div.get_text(strip=True):
                    lyrics_raw = div.get_text(separator="\n")
                    if len(lyrics_raw.splitlines()) > 10:
                        lines = []
                        for line in lyrics_raw.split("\n"):
                            line = re.sub(r'\([^)]*\)', '', line).strip()
                            if (line
                                and "Submit Corrections" not in line
                                and not (line.startswith("[") and line.endswith("]"))):
                                lines.append(line)
                        if lines:
                            return lines
    except Exception as e:
        print(f"[AZLyrics error] {e}")
    return None

def parole(song, artist):
    # 1. lyrics.ovh
    try:
        url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist)}/{urllib.parse.quote(song)}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            lyrics_raw = response.json().get("lyrics", "")
            if lyrics_raw:
                result = [
                    textwrap.wrap(line, width=30)
                    for line in lyrics_raw.split('\n')
                    if line.strip()
                    and "(feat." not in line
                    and not (line.startswith('[') and line.endswith(']'))
                ]
                if result:
                    return result
    except Exception as e:
        print(f"⚠️ lyrics.ovh error: {e}")

    # 2. AZLyrics
    print(f"[AZLyrics fallback] {artist} - {song}")
    lines = _azlyrics_get_lyrics(song, artist)
    if lines:
        return [textwrap.wrap(line, width=30) for line in lines if line.strip()]

    # 3. Genius
    print(f"[Genius fallback] {artist} - {song}")
    lines = _genius_get_lyrics(artist, song)
    if lines:
        return [textwrap.wrap(line, width=30) for line in lines if line.strip()]
    return None

def get_album_cover(artist, song):
    cache_key = (edit(artist), edit(song))
    if cache_key in _album_cache:
        return _album_cache[cache_key], "cache"
    artist = edit(artist)
    query = f"{artist} {song}"

    img, label = None, None

    # --------------iTunes--------------
    try:
        url = f"https://itunes.apple.com/search?term={requests.utils.quote(query)}&media=music&limit=1"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("resultCount", 0) > 0:
            img_url = data["results"][0]["artworkUrl100"].replace("100x100", "1200x1200")
            img_data = requests.get(img_url).content
            img, label = Image.open(BytesIO(img_data)), f"   iTunes Image: {img_url}"
    except Exception as e:
        print(f"❌ iTunes failed: {e}")

    # --------------Google--------------
    if img is None:
        try:
            search_query = urllib.parse.quote(f"{artist} {song} album cover")
            google_url = f"https://www.google.com/search?q={search_query}&tbm=isch"
            response = requests.get(google_url, headers=_AZ_HEADERS)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            img_tags = soup.find_all("img")
            if len(img_tags) > 1:
                img_src = img_tags[1].get("src")
                if img_src and img_src.startswith("http"):
                    img, label = Image.open(BytesIO(requests.get(img_src).content)), f"   Google Image: {img_src}"
        except Exception as e:
            print(f"❌ Google Images failed: {e}")

    if img is None:
        print("❌ Aucune image d'album trouvée")
        return None, None

    if len(_album_cache) >= _ALBUM_CACHE_MAX:
        _album_cache.pop(next(iter(_album_cache)))
    _album_cache[cache_key] = img
    return img, label

def add_sun(draw, width, _height, side):
    if side == 'right':
        x, y = width - 150, 200
        r = 80
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 0))
        
        for _ in range(12):
            angle = random.uniform(0, 2 * math.pi)
            length = random.randint(100, 200)
            end_x = x + length * math.cos(angle)
            end_y = y + length * math.sin(angle)
            draw.line([(x, y), (end_x, end_y)], fill=(255, 255, 0), width=5)
    else:
        return

def add_birds(draw, width, height):
    for _ in range(random.randint(10, 15)):
        x = random.randint(50, width - 50)
        y = random.randint(50, height // 3)
        size = random.randint(15, 30)
        draw.line([(x, y), (x + size // 2, y + size // 2), (x + size, y)], fill="black", width=3)

def add_lightning(draw, width, height):
    for _ in range(random.randint(1, 3)):
        x = random.randint(0, width)
        y = 0
        points = [(x, y)]
        while y < height:
            x += random.randint(-50, 50)
            y += random.randint(20, 100)
            points.append((x, y))
        draw.line(points, fill="white", width=random.randint(3, 8))

def add_purple_rain(draw, width, height):
    for _ in range(150):
        x = random.randint(0, width)
        y = random.randint(0, height)
        length = random.randint(30, 80)
        draw.line([(x, y), (x, y + length)], fill=(120, 81, 169), width=3)

def apply_glitch(base):
    width, height = base.size
    r, g, b = base.split()
    r = ImageChops.offset(r, random.randint(-10, 10), 0)
    b = ImageChops.offset(b, random.randint(-10, 10), 0)
    base = Image.merge("RGB", (r, g, b))
    
    for _ in range(random.randint(5, 10)):
        y = random.randint(0, height - 50)
        h = random.randint(20, 100)
        x_shift = random.randint(-50, 50)
        box = (0, y, width, y + h)
        region = base.crop(box)
        base.paste(region, (x_shift, y))
    return base

font_cache = {}
def get_cached_font(font_path, size):
    key = (font_path, size)
    if key not in font_cache:
        try:
            font_cache[key] = ImageFont.truetype(font_path, size)
        except:
            font_cache[key] = ImageFont.truetype(font_path, 60)
    return font_cache[key]

def create_image(text, album_image, side='right', bg_color=(11, 38, 117), font_path="arial.ttf"):
    W, H = 1082, 1919
    base = Image.new("RGB", (W, H), color=bg_color)
    draw = ImageDraw.Draw(base)

    is_metal = bg_color == (15, 15, 15)
    is_plage = bg_color == (255, 165, 0)

    if is_metal:
        add_lightning(draw, W, H)
        add_purple_rain(draw, W, H)

    if is_plage:
        add_sun(draw, W, H, side)
        add_birds(draw, W, H)

    album_resized = album_image.resize((600, 600), Image.LANCZOS)

    half = album_resized.crop((0, 0, 302, 600)) if side == 'right' else album_resized.crop((300, 0, 600, 600))
    x_pos = 780 if side == 'right' else 0

    base.paste(half, (x_pos, H // 2 - 270))

    try:
        size = 45 if "Slow Play" in font_path else 50
        font = get_cached_font(font_path, size)
    except:
        font = get_cached_font(font_path, 60)
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

    if is_metal:
        base = apply_glitch(base)

    bio = BytesIO()
    base.save(bio, 'JPEG')
    bio.seek(0)
    return bio

def log_attempt(first_name, user_id, message, result, color):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   🎨 Couleur : {color}")
    print(f"   {"✅" if result else "❌"} Résultat : {'Succès' if result else 'Échec'}")
    print(50 * "-")
    
async def pallette(update, _):
    boutons = [
        [KeyboardButton("🔵 Bleu"), KeyboardButton("⚫ Metal")],
        [KeyboardButton("⚪ blanc"), KeyboardButton("🏖️ Plage")]
    ]
    clavier = ReplyKeyboardMarkup(
        keyboard=boutons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Crée ton tiktok !!"
    )
    await update.message.reply_text("Choisis ta couleur :", reply_markup=clavier)

async def font_palette(update, _):
    boutons = [
        [KeyboardButton("Arial"), KeyboardButton("Angel Wish"), KeyboardButton("Slow Play")]
    ]
    clavier = ReplyKeyboardMarkup(
        keyboard=boutons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Choisis ta police !!"
    )
    await update.message.reply_text("Choisis ta police :", reply_markup=clavier)

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
        
        text = "\n".join(line for sublist in block for line in sublist)

        user_id = query.from_user.id
        bg_color = user_colors.get(user_id, (11, 38, 117))
        font_path = user_fonts.get(user_id, "arial.ttf")
        titre = context.user_data.get("titre")
        artist = context.user_data.get("artist")
        song = context.user_data.get("song")
        album_image, _ = await run_blocking(get_album_cover, artist, titre)

        if album_image is None:
            await query.message.reply_text("❌ Erreur lors de la récupération de l'image.")
            return

        try:
            img2_bio, img1_bio = await asyncio.gather(
                run_blocking(create_image, text, album_image.copy(), side='left', bg_color=bg_color, font_path=font_path),
                run_blocking(create_image, song, album_image.copy(), side='right', bg_color=bg_color, font_path="arial.ttf")
            )

            await query.message.reply_photo(photo=img1_bio, read_timeout=300, write_timeout=300, connect_timeout=300)
            await query.message.reply_photo(photo=img2_bio, read_timeout=300, write_timeout=300, connect_timeout=300)
            
            await query.message.reply_text(f"{song} || {artist}\n#lyrics_songs #fyp #pourtoi #{edit(song)} #{edit(artist)}")
        except Exception as e:
            print(f"❌ Erreur création/envoi images: {e}")
            await query.message.reply_text("❌ Erreur lors de la création des images")

async def echo(update, context):
    user = update.message.from_user
    user_id = user.id
    message = update.message.text
    first_name = user.first_name or "Inconnu"

    choose_line, _, artist, song = split_message(message)
    color_name = next((k for k, v in color_map.items() if v == user_colors.get(user_id)), '🔵 Bleu')

    if choose_line == "Erreur, format attendu : artiste:titre":
        log_attempt(first_name, user_id, message, False, color_name)
        await update.message.reply_text(choose_line)
        return

    if choose_line == "COLOR":
        user_colors[user_id] = color_map.get(song)
        await update.message.reply_text(f"🎨 Tu as choisi la couleur {song} !")
        return

    if choose_line == "FONT":
        user_fonts[user_id] = font_map.get(song)
        await update.message.reply_text(f"🔤 Tu as choisi la police {song} !")
        return

    all_lines = await run_blocking(parole, song, artist)
    result = all_lines is not None
    log_attempt(first_name, user_id, message, result, color_name)

    if not result:
        await update.message.reply_text(f"❌ Paroles non trouvées pour {artist} - {song}. Vérifie l'orthographe ou essaie un autre titre.")
        return

    context.user_data["lyrics"] = all_lines
    context.user_data["index"] = 0
    context.user_data["titre"] = song
    context.user_data["artist"] = artist
    context.user_data["song"] = song

    await send_lyrics(update, context, index=0)