import yt_dlp, warnings, logging, numpy, time, os, asyncio, datetime

from PIL import Image, ImageDraw, ImageFont
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip
from faster_whisper import WhisperModel
from moviepy.config import change_settings

change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"})
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("TOKEN")
user_colors = {}
FOLDER_PATH = r"C:\Users\Lucas\github\bot-telegram"

warnings.filterwarnings("ignore")
logging.getLogger("ctranslate2").setLevel(logging.ERROR)
language = None

def download_video(url, folder, filename):
    os.makedirs(folder, exist_ok=True)
    
    class MyLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): print(f"❌ YT-DLP Error: {msg}")

    def my_hook(d):
        if d['status'] == 'downloading':
            print(f"📥 {d['filename']} {d['_percent_str']} à {d['_speed_str']} - ETA {d['_eta_str']}", end='\r')

    output_path = os.path.join(folder, f"{filename}.%(ext)s")
    
    ydl_opts = {
        'outtmpl': output_path,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
        'merge_output_format': 'mp4',
        'logger': MyLogger(),
        'progress_hooks': [my_hook],
        'quiet': True,
        'no_warnings': True,
        'concurrent_fragment_downloads': 5,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
            'Sec-Fetch-Mode': 'navigate'
        }
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    video_path = os.path.join(folder, f"{filename}.mp4")
    if os.path.exists(video_path):
        return video_path

def generer_lyrics_txt(video_file, output_txt):
    try:
        model = WhisperModel("base", device="cpu", compute_type="float32")
        segments, _ = model.transcribe(
            video_file, word_timestamps=True, language=language, beam_size=5, best_of=5
        )

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

def log_attempt(first_name, user_id, message, result, color):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   🎨 Couleur : {color}")
    print(f"   {"✅" if result else "❌"} Résultat : {'Succès' if result else 'Échec'}")
    print(50 * "-")

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
                await update.callback_query.message.reply_text(f"{song} || {artist}\n#karaoke #fyp #pourtoi #{song} #{artist}")

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
        log_attempt(first_name, user_id, message, result=True, color=None)

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
        if message[-2:] in ("fr", "en", "es", "it", "de"):
            global language
            language = message[-2:]
            message = message[:-2].strip()
            await update.message.reply_text(f"🌐 Langue définie sur : {language}")

        parts = message.split(":", 1)
        if len(parts) != 2:
            await update.message.reply_text("❌ Format attendu : artiste:titre(fr/en/es/it/de)")
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
