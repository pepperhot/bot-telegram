import os
import yt_dlp
import numpy
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip
from faster_whisper import WhisperModel
from telegram.ext import Application, MessageHandler, filters, CallbackQueryHandler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
from datetime import datetime
import asyncio
import warnings, logging
from moviepy.config import change_settings

change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"})


load_dotenv()
TOKEN = os.getenv("TOKEN")
FOLDER_PATH = r"C:\Users\FlowUP\github\bot-telegram"

warnings.filterwarnings("ignore")
logging.getLogger("ctranslate2").setLevel(logging.ERROR)

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
                mots.append(word.word.strip())
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
        contenu = f.read().strip()
    blocs = contenu.split("\n\n")
    for bloc in blocs:
        parts = bloc.strip().split("\n")
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
        lignes = [l.strip() for l in f if l.strip()]

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
    final.write_videofile(output_karaoke, codec="libx264", audio_codec="aac")

def process_song(artist, song, url):
    video_path = os.path.join(FOLDER_PATH, f"{artist} - {song}.mp4")
    lyrics_path_txt = os.path.join(FOLDER_PATH, f"{artist} - {song}.txt")
    if not url:
        search_query = f"ytsearch1:{artist} {song} clip officiel"
        url = yt_dlp.YoutubeDL({'quiet': True}).extract_info(search_query, download=False)['entries'][0]['webpage_url']
    if not os.path.exists(video_path):
        download_video(url, FOLDER_PATH, video_path)
    lyrics_path = os.path.join(FOLDER_PATH, lyrics_path_txt)
    if not os.path.exists(lyrics_path):
        generer_lyrics_txt(video_path, lyrics_path_txt)
    return lyrics_path_txt

def log_attempt(first_name, user_id, message, result):
    now = datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   {'✅' if result else '❌'} Résultat : {'Succès' if result else 'Échec'}")
    print(50 * "-")

async def send_lyrics(update, context, index):
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

async def button_handler(update, context):
    query = update.callback_query
    await query.answer()
    action, idx = query.data.split(":")
    idx = int(idx)

    if action == "next":
        await send_lyrics(update, context, idx+2)
    elif action == "back":
        await send_lyrics(update, context, max(0, idx-2))
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

async def echo(update, context):
    user = update.message.from_user
    first_name = user.first_name or "Inconnu"
    user_id = user.id
    message = update.message.text
    loop = asyncio.get_event_loop()

    if message:
        await update.message.reply_text("Traitement en cours...")
        log_attempt(first_name, user_id, message, result=True)

    if ":" not in message and not message.startswith("https://www.youtube.com/watch?v="):
        await update.message.reply_text("Format attendu : artiste:titre ou lien YouTube")
        return

    if message.startswith("https://www.youtube.com/watch?v="):
        lyrics_path = await loop.run_in_executor(None, process_song, None, None, message)
        lines = lire_txt(lyrics_path)
        context.user_data["lyrics"] = lines
        await send_lyrics(update, context, index=0)
        print("je demander les lyrics")
        return

    artist, song = [x.strip() for x in message.split(":", 1)]
    context.user_data["artist"] = artist
    context.user_data["song"] = song

    lyrics_path = await loop.run_in_executor(None, process_song, artist, song, None)
    lines = lire_txt(lyrics_path)
    context.user_data["lyrics"] = lines

    await send_lyrics(update, context, index=0)

def main():
    print("Bot Karaoke...")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()

if __name__ == "__main__":
    main()
