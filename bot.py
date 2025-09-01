import requests, os, urllib.parse
import textwrap
import yt_dlp, asyncio, warnings, logging, numpy

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from bs4 import BeautifulSoup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from datetime import datetime
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip
from faster_whisper import WhisperModel
from moviepy.config import change_settings

change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"})

load_dotenv()
TOKEN = os.getenv("TOKEN")
user_colors = {}
FOLDER_PATH = r"C:\Users\FlowUP\github\bot-telegram"

warnings.filterwarnings("ignore")
logging.getLogger("ctranslate2").setLevel(logging.ERROR)

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
        print(f"Erreur lors de la récupération des paroles: {e}")
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
    except:
        pass

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
    except:
        pass

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
    except:
        pass
    
    return None
            
def create_image(text, album_image, file, side='right', bg_color=(11, 38, 117)):

    W, H = 1082, 1920
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

    draw.multiline_text((text_x, text_y), wrapped_text, font=font, fill="white", spacing=10)

    base.save(file)

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

async def start(update, context):
    user = update.message.from_user
    await update.message.reply_text(f"Salut {user.first_name}, envoie-moi artiste:titre ou lien YouTube pour commencer le karaoké !")

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
    except:
        print("   freeze")

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
        
        text = "\n".join(block)
        user_id = query.from_user.id
        bg_color = user_colors.get(user_id, (11, 38, 117))
        titre = context.user_data.get("titre")
        artist = context.user_data.get("artist")
        song = context.user_data.get("song")
        album_image, _ = get_album_cover(titre, artist)

        if album_image is None:
            await query.message.reply_text("Erreur lors de la récupération de l'image.")
            return

        create_image(text, album_image, "img2.jpg", side='left', bg_color=bg_color)
        create_image(song, album_image, "img1.jpg", side='right', bg_color=bg_color)

        with open("img1.jpg", "rb") as img1:
            await query.message.reply_photo(photo=img1, timeout=120)
        with open("img2.jpg", "rb") as img2:
            await query.message.reply_photo(photo=img2, timeout=120)
        os.remove("img1.jpg") 
        os.remove("img2.jpg")
        await query.message.reply_text(f"{song} || {artist}\n#lyrics_songs #playback #fyp #trend #foryou #{titre} #{artist}")

def log_attempt(first_name, user_id, message, result, color, type):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   🎨 Couleur : {color}")
    print(f"   {"✅" if result else "❌"} Résultat : {'Succès' if result else 'Échec'}")
    if result and type == "lyrics":
        _, titre, artist, _ = split_message(message)
        _, url = get_album_cover(titre, artist)
        print(url)
    print(50 * "-")

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
        user_colors[user_id] = emoji_to_rgb(song)
        await update.message.reply_text(f"🎨 Tu as choisi la couleur {song} !")
        return

    all_lines = parole(titre, artist)
    result = all_lines is not None
    log_attempt(first_name, user_id, message, result, color_name, type="lyrics")

    if not result:
        await update.message.reply_text("Paroles introuvables.")
        return

    context.user_data["lyrics"] = all_lines
    context.user_data["index"] = 0
    context.user_data["titre"] = song
    context.user_data["artist"] = artist
    context.user_data["song"] = song

    await send_lyrics(update, context, index=0)

def download_video(url, folder, filename):
    os.makedirs(folder, exist_ok=True)
    
    class MyLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): pass

    def my_hook(d):
        if d['status'] == 'downloading':
            print(f"{d['filename']} {d['_percent_str']} à {d['_speed_str']} - ETA {d['_eta_str']}", end='\r')

    ydl_opts = {
        'outtmpl': os.path.join(folder, filename),
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'merge_output_format': 'mp4',
        'logger': MyLogger(),
        'progress_hooks': [my_hook],
        'quiet': True,
        'no_warnings': True,
        'concurrent_fragment_downloads': 5
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError:
            print("Erreur téléchargement")

def generer_lyrics_txt(video_file, output_txt):
    model = WhisperModel("base", device="cpu", compute_type="float32")
    segments, _ = model.transcribe(video_file, word_timestamps=True)

    with open(output_txt, "w", encoding="utf-8") as f:
        for seg in segments:
            mots = []
            start_time = None
            for word in seg.words:
                if start_time is None:
                    start_time = word.start
                mots.append(word.word)
                end_time = word.end
                if len(mots) >= 6 or any(p in word.word for p in [",",".","!","?"]):
                    duration = end_time - start_time
                    f.write(f"{' '.join(mots)}\n{start_time:.3f}/{duration:.3f}\n\n")
                    mots = []
                    start_time = None
            if mots and start_time is not None:
                duration = end_time - start_time
                f.write(f"{' '.join(mots)}\n{start_time:.3f}/{duration:.3f}\n")

def lire_txt(filepath):
    lignes = []
    with open(filepath, 'r', encoding='utf-8') as f:
        contenu = f.read()
    blocs = contenu.split("\n\n")
    for bloc in blocs:
        parts = bloc.split("\n")
        if len(parts) != 2: continue
        try:
            texte = parts[0]
            start, duration = map(float, parts[1].split("/"))
            lignes.append((texte, start, duration))
        except ValueError:
            continue
    return lignes

def text_with_shadow(text):
    font = ImageFont.truetype("impact.ttf", 50)
    tmp_img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp_img)
    bbox = draw.textbbox((0, 0), text, font=font, spacing=10)

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    padding = 50

    img = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x, y = padding, padding
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx != 0 or dy != 0:
                draw.multiline_text((x + dx, y + dy), text, font=font, fill="black", spacing=10)

    draw.multiline_text((x, y), text, font=font, fill="white", spacing=10)
    np_img = numpy.array(img)
    return ImageClip(np_img).set_duration(2)

def create_karaoke_video(video_path, idx_line, output_karaoke, path_txt):
    with open(path_txt, "r", encoding="utf-8") as f:
        lignes = [l for l in f if l]

    if not (0 <= idx_line < len(lignes)):
        raise ValueError(f"Numéro de ligne invalide : idx_line={idx_line}, lignes={len(lignes)}")

    lyrics_lines = []
    for i, ligne in enumerate(lignes[idx_line:]):
        if '/' in ligne:
            start_str, duration_str = ligne.split('/')
            start = float(start_str)
            duration = float(duration_str)
            texte = lignes[idx_line + i - 1]
            lyrics_lines.append((texte, start, duration))

    if not lyrics_lines:
        raise ValueError("Aucune ligne valide de start/duration trouvée")

    video_start = lyrics_lines[0][1]
    video_end = video_start + 60 #secondes
    video = VideoFileClip(video_path).subclip(video_start, video_end)

    clip_zoomed = video.resize(1.2)
    video = clip_zoomed.resize(height=1920).crop(
        x_center=clip_zoomed.w//2,
        y_center=clip_zoomed.h//2,
        width=1080,
        height=1920)
    
    clips = []
    for texte, start, duration in lyrics_lines:
        if start < video_end:
            remaining = min(duration, video_end - start)
            txt_clip = text_with_shadow(texte).set_start(start - video_start).set_duration(remaining).set_position("center")
            clips.append(txt_clip)

    final = CompositeVideoClip([video, *clips])
    final.write_videofile(output_karaoke, codec="libx264", audio_codec="aac", preset="ultrafast", bitrate="1500k")

def process_song(artist, song, url):
    video_path = os.path.join(FOLDER_PATH, f"{artist} - {song}.mp4")
    lyrics_path_txt = os.path.join(FOLDER_PATH, f"{artist} - {song}.txt")
    if not url:
        search_query = f"ytsearch1:{artist} {song} clip officiel"
        url = yt_dlp.YoutubeDL({'quiet': True}).extract_info(search_query, download=False)['entries'][0]['webpage_url']
    if not os.path.exists(video_path):
        download_video(url, FOLDER_PATH, video_path)
    lyrics_path = os.path.join(FOLDER_PATH, lyrics_path_txt)
    if not os.path.exists(lyrics_path_txt):
        generer_lyrics_txt(video_path, lyrics_path_txt)
    return lyrics_path_txt

async def send_lyrics_karaoke(update, context, index):
    lines = context.user_data.get("lyrics", [])
    if not lines:
        await update.message.reply_text("Aucune parole chargée.")
        return

    block = lines[index:index+2]
    text = "\n".join([l[0] for l in block])

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
    except:
        print("Erreur affichage Telegram")

async def button_handler_karaoke(update, context):
    query = update.callback_query
    await query.answer()
    action, idx = query.data.split(":")
    idx = int(idx)

    if action == "next":
        await send_lyrics_karaoke(update, context, idx+2)
    elif action == "back":
        await send_lyrics_karaoke(update, context, max(0, idx-2))
    elif action == "select":
        artist = context.user_data.get("artist", "")
        song = context.user_data.get("song", "")
        video_path = os.path.join(FOLDER_PATH, f"{artist} - {song}.mp4")
        output_karaoke = os.path.join(FOLDER_PATH, f"{artist} - {song}_karaoke.mp4")
        lyrics_path = os.path.join(FOLDER_PATH, f"{artist} - {song}.txt")

        await update.callback_query.message.reply_text("Je cuisine la vidéo chéri")
        create_karaoke_video(video_path, idx, output_karaoke, lyrics_path)

        try:
            with open(output_karaoke, "rb") as f:
                await context.bot.send_video(chat_id=update.effective_chat.id, video=f)
        except Exception as e:
            print("error:", e)
            await update.callback_query.message.reply_text("on a un petit contretemps dans la maintenace appelé le suport")

async def echo_karaoke(update, context):
    user = update.message.from_user
    first_name = user.first_name or "Inconnu"
    user_id = user.id
    message = update.message.text
    loop = asyncio.get_event_loop()

    if message:
        await update.message.reply_text("Traitement en cours...")
        log_attempt(first_name, user_id, message, result=True, color=None, type="karaoke")

    if ":" not in message and not message.startswith("https://www.youtube.com/watch?v="):
        await update.message.reply_text("Format attendu : artiste:titre ou lien YouTube")
        return

    if message.startswith("https://www.youtube.com/watch?v="):
        lyrics_path = await loop.run_in_executor(None, process_song, None, None, message)
        lines = lire_txt(lyrics_path)
        context.user_data["lyrics"] = lines
        await send_lyrics_karaoke(update, context, index=0)
        print("je demander les lyrics")
        return

    artist, song = [x for x in message.split(":", 1)]
    context.user_data["artist"] = artist
    context.user_data["song"] = song

    lyrics_path = await loop.run_in_executor(None, process_song, artist, song, None)
    lines = lire_txt(lyrics_path)
    context.user_data["lyrics"] = lines

    await send_lyrics_karaoke(update, context, index=0)

def main():
    print("Bot fusionné lyrics + karaoke...")
    application = Application.builder().token(TOKEN).build()

    # --- bot karoucelle ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("pallette", pallette))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(next|back|select).*"))

    async def karaoke_cmd(update, context):
        await update.message.reply_text("🎤 Mode Karaoke activé ! Envoie artiste:titre ou un lien YouTube")
        context.user_data["karaoke_mode"] = True

    async def echo_global(update, context):
        if context.user_data.get("karaoke_mode", False):
            await echo_karaoke(update, context)
        else:
            await echo(update, context)

    # --- Handlers ajoutés ---
    application.add_handler(CommandHandler("karaoke", karaoke_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_global))
    application.add_handler(CallbackQueryHandler(button_handler_karaoke, pattern="^(karaoke_).*"))

    # --- Lancement ---
    application.run_polling()

if __name__ == '__main__':
    main()