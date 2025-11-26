import requests, os, urllib.parse
import textwrap
import yt_dlp, asyncio, warnings, logging, numpy, time

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
FOLDER_PATH = r"C:\Users\Lucas\github\bot-telegram"

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

    draw.multiline_text((text_x, text_y), wrapped_text, font=font, fill="white", spacing=10)

    base.save(file)

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

def emoji_to_rgb(emoji: str):
    return color_map.get(emoji)

async def start(update, _):
    if update.message:
        user = update.message.from_user
    elif update.effective_user:
        user = update.effective_user
    else:
        return
    await update.message.reply_text(f"Salut {user.first_name}, voici mon bot telegram! ")
    await update.message.reply_text("Commandes:\n    - /start : affiche ce message \n    -/lyrics : format de tiktok karoucelle \n    - /pallette : affiche les couleurs disponibles \n    -/karaoke : format de tiktok karaoke avec videos")

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
            
            await query.message.reply_text(f"{song} || {artist}\n#lyrics_songs #playbook #fyp #trend #foryou #{song} #{artist}")
        except Exception as e:
            print(f"❌ Erreur création/envoi images: {e}")
            await query.message.reply_text("❌ Erreur lors de la création des images")

def log_attempt(first_name, user_id, message, result, color, type):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   🎨 Couleur : {color}")
    print(f"   {"✅" if result else "❌"} Résultat : {'Succès' if result else 'Échec'}")
    if result and type == "lyrics":
        _, titre, artist, _ = split_message(message)
        _, url = get_album_cover(titre, artist)
        if url:
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
        def error(self, msg): print(f"❌ YT-DLP Error: {msg}")

    def my_hook(d):
        if d['status'] == 'downloading':
            print(f"📥 {d['filename']} {d['_percent_str']} à {d['_speed_str']} - ETA {d['_eta_str']}", end='\r')
        elif d['status'] == 'finished':
            print(f"\n✅ Téléchargement terminé, fusion en cours...")

    output_path = os.path.join(folder, f"{filename}.%(ext)s")
    
    ydl_opts = {
        'outtmpl': output_path,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'merge_output_format': 'mp4',
        'logger': MyLogger(),
        'progress_hooks': [my_hook],
        'quiet': True,
        'no_warnings': True,
        'concurrent_fragment_downloads': 5
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    video_path = os.path.join(folder, f"{filename}.mp4")
    if os.path.exists(video_path):
        return video_path

def generer_lyrics_txt(video_file, output_txt):
    try:
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
        
        return True
    except Exception as e:
        return False

def lire_txt(filepath):
    if not os.path.exists(filepath):
        return []
    
    lignes = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            contenu = f.read()
        blocs = contenu.split("\n\n")
        for bloc in blocs:
            parts = bloc.split("\n")
            if len(parts) != 2: 
                continue
            try:
                texte = parts[0]
                start, duration = map(float, parts[1].split("/"))
                lignes.append((texte, start, duration))
            except ValueError:
                continue
        return lignes
    except Exception as e:
        return []

def text_with_shadow(text):
    try:
        font = ImageFont.truetype("impact.ttf", 50)
    except:
        try:
            font = ImageFont.truetype("arial.ttf", 50)
        except:
            font = ImageFont.load_default()
    
    tmp_img = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(tmp_img)
    bbox = draw.textbbox((0, 0), text, font=font, spacing=10)

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    padding = 50

    img = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x, y = padding, padding
    # Ombre
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            if dx != 0 or dy != 0:
                draw.multiline_text((x + dx, y + dy), text, font=font, fill="black", spacing=10)

    # Texte principal
    draw.multiline_text((x, y), text, font=font, fill="white", spacing=10)
    np_img = numpy.array(img)
    return ImageClip(np_img).set_duration(2)

def create_karaoke_video(video_path, idx_line, output_karaoke, path_txt):

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Vidéo source introuvable : {video_path}")
    
    if not os.path.exists(path_txt):
        raise FileNotFoundError(f"Fichier lyrics introuvable : {path_txt}")

    if os.path.exists(output_karaoke):
        os.remove(output_karaoke)

    try:
        with open(path_txt, "r", encoding="utf-8") as f:
            lignes = [l.strip() for l in f if l.strip()]

        if not (0 <= idx_line < len(lignes)):
            raise ValueError(f"Numéro de ligne invalide : idx_line={idx_line}, lignes={len(lignes)}")

        lyrics_lines = []
        for i, ligne in enumerate(lignes[idx_line:]):
            if '/' in ligne:
                try:
                    start_str, duration_str = ligne.split('/')
                    start = float(start_str)
                    duration = float(duration_str)
                    texte = lignes[idx_line + i - 1] if (idx_line + i - 1) >= 0 else ""
                    lyrics_lines.append((texte, start, duration))
                except ValueError:
                    continue

        video_start = lyrics_lines[0][1]
        video_end = min(video_start + 60, lyrics_lines[-1][1] + lyrics_lines[-1][2])
        base_clip = VideoFileClip(video_path, audio=True)
        
        video_segment = base_clip.subclip(video_start, video_end)

        original_w, original_h = video_segment.w, video_segment.h
        target_w, target_h = 1080, 1920
        
        scale_factor = target_h / original_h
        new_w = int(original_w * scale_factor)
        new_h = target_h
        
        video_resized = video_segment.resize((new_w, new_h))
        
        if new_w > target_w:
            x_center = new_w // 2
            video = video_resized.crop(x1=x_center - target_w//2, 
                                     x2=x_center + target_w//2)
        else:
            video = video_resized.resize((target_w, target_h))

        clips = [video]
        
        for i, (texte, start, duration) in enumerate(lyrics_lines):
            if start < video_end and texte.strip():
                remaining = min(duration, video_end - start)
                if remaining > 0.5:
                    try:
                        texte_court = texte[:50] + "..." if len(texte) > 50 else texte
                        
                        txt_clip = text_with_shadow(texte_court).set_start(
                            start - video_start
                        ).set_duration(remaining).set_position(("center", "center"))
                        clips.append(txt_clip)
                    except Exception as e:
                        pass

        final = CompositeVideoClip(clips, size=(1080, 1920))

        if final.duration <= 0:
            raise ValueError("Durée de vidéo finale invalide")

        final.write_videofile(
            output_karaoke,
            codec="libx264",
            audio_codec="aac",
            preset="medium",  # Plus stable qu'ultrafast
            bitrate="2000k",
            fps=24,
            temp_audiofile=None,  # Éviter les fichiers temp
            remove_temp=True,
            verbose=True,  # Activer les logs pour déboguer
            logger='bar'   # Afficher la barre de progression
        )
        
        final.close()
        video_segment.close()
        base_clip.close()
        
        time.sleep(2)

        if os.path.exists(output_karaoke):
            file_size = os.path.getsize(output_karaoke)
            if file_size > 0:
                print(f"📏 Taille finale : {file_size / (1024*1024):.2f} MB")
                return True
            else:
                return False
        else:
            return False
            
    except Exception as e:
        try:
            if 'final' in locals():
                final.close()
            if 'video_segment' in locals():
                video_segment.close()
            if 'base_clip' in locals():
                base_clip.close()
        except:
            pass
        raise

def process_song(artist, song, url):
    
    safe_filename = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
    video_path = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
    lyrics_path_txt = os.path.join(FOLDER_PATH, f"{safe_filename}.txt")
    
    if not url:
        search_query = f"ytsearch1:{artist} {song} clip officiel"
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if info and 'entries' in info and len(info['entries']) > 0:
                    url = info['entries'][0]['webpage_url']
                else:
                    return None
        except Exception as e:
            return None
    
    if not os.path.exists(video_path):
        result = download_video(url, FOLDER_PATH, safe_filename)
        if not result:
            return None
    
    if not os.path.exists(lyrics_path_txt):
        success = generer_lyrics_txt(video_path, lyrics_path_txt)
        if not success:
            return None
    
    return lyrics_path_txt

async def send_lyrics_karaoke(update, context, index):
    lines = context.user_data.get("lyrics", [])

    block = lines[index:index+2]
    text = "\n".join([l[0] if isinstance(l, tuple) else str(l) for l in block])

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

    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)

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
        
        safe_filename = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
        video_path = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
        output_karaoke = os.path.join(FOLDER_PATH, f"{safe_filename}_karaoke.mp4")
        lyrics_path = os.path.join(FOLDER_PATH, f"{safe_filename}.txt")

        await update.callback_query.message.reply_text("🎬 Je cuisine la vidéo chéri...")
        
        try:
            create_karaoke_video(video_path, idx, output_karaoke, lyrics_path)
            
            if not os.path.exists(output_karaoke):
                await update.callback_query.message.reply_text("❌ La vidéo n'a pas été générée correctement")
                return

            file_size = os.path.getsize(output_karaoke)
            print(f"📹 Taille vidéo karaoke : {file_size / (1024*1024):.2f} MB")

            if file_size > 50 * 1024 * 1024:
                await update.callback_query.message.reply_text("❌ Vidéo trop volumineuse pour Telegram (>50MB)")
                return
            
            try:
                with open(output_karaoke, "rb") as f:
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id, 
                        video=f,
                        supports_streaming=True,
                        read_timeout=300,
                        write_timeout=300,
                        connect_timeout=300
                    )
                print(f"✅ Vidéo karaoke envoyée avec succès")

                for i in [output_karaoke, lyrics_path, video_path]:
                    os.remove(i) if os.path.exists(i) else None
                
            except FileNotFoundError:
                await update.callback_query.message.reply_text("❌ Fichier vidéo introuvable")
                print(f"❌ Fichier non trouvé : {output_karaoke}")
                
            except Exception as e:
                await update.callback_query.message.reply_text(f"❌ Erreur envoi vidéo : {str(e)[:100]}")
        except Exception as e:
            print(f"❌ Erreur création vidéo karaoke: {e}")
            await update.callback_query.message.reply_text(f"❌ Erreur création vidéo : {str(e)[:100]}")

async def echo_karaoke(update, context):
    user = update.message.from_user
    first_name = user.first_name or "Inconnu"
    user_id = user.id
    message = update.message.text
    loop = asyncio.get_event_loop()

    if message:
        await update.message.reply_text("⏳ Traitement en cours...")
        log_attempt(first_name, user_id, message, result=True, color=None, type="karaoke")

    if message.startswith("https://www.youtube.com/watch?v="):
        try:
            lyrics_path = await loop.run_in_executor(None, process_song, "Unknown", "Unknown", message)
            if not lyrics_path:
                await update.message.reply_text("❌ Échec du traitement de la vidéo YouTube")
                return
                
            lines = lire_txt(lyrics_path)
            if not lines:
                await update.message.reply_text("❌ Aucune parole détectée dans la vidéo")
                return
                
            context.user_data["lyrics"] = lines
            context.user_data["artist"] = "Unknown"
            context.user_data["song"] = "Unknown"
            await send_lyrics_karaoke(update, context, index=0)
            return
        except Exception as e:
            print(f"❌ Erreur traitement YouTube: {e}")
            await update.message.reply_text("❌ Erreur lors du traitement du lien YouTube")
            return

    if ":" not in message:
        await update.message.reply_text("❌ Format attendu : artiste:titre ou lien YouTube")
        return

    try:
        parts = message.split(":", 1)
        if len(parts) != 2:
            await update.message.reply_text("❌ Format attendu : artiste:titre")
            return
            
        artist, song = [x.strip() for x in parts]
        if not artist or not song:
            await update.message.reply_text("❌ Artiste et titre ne peuvent pas être vides")
            return
            
        context.user_data["artist"] = artist
        context.user_data["song"] = song

        lyrics_path = await loop.run_in_executor(None, process_song, artist, song, None)
        if not lyrics_path:
            await update.message.reply_text("❌ Impossible de traiter cette chanson")
            return
            
        lines = lire_txt(lyrics_path)
        if not lines:
            await update.message.reply_text("❌ Aucune parole générée pour cette chanson")
            return
            
        context.user_data["lyrics"] = lines
        await send_lyrics_karaoke(update, context, index=0)
        
    except Exception as e:
        print(f"❌ Erreur echo_karaoke: {e}")
        await update.message.reply_text("❌ Erreur lors du traitement de la demande")

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
    application.add_handler(CommandHandler("karaoke", karaoke_cmd))
    application.add_handler(CommandHandler("lyrics", lyrics_cmd))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_global))

    # --- Lancement ---
    application.run_polling()

if __name__ == '__main__':
    main()