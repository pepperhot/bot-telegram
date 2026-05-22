import yt_dlp, warnings, logging, numpy, time, os, asyncio, datetime, difflib, re

from PIL import Image, ImageDraw, ImageFont
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip
from faster_whisper import WhisperModel
from moviepy.config import change_settings

change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"})
from dotenv import load_dotenv
load_dotenv()
FOLDER_PATH = os.getenv("FOLDER_PATH", ".")

warnings.filterwarnings("ignore")
logging.getLogger("ctranslate2").setLevel(logging.ERROR)

# ── Barre de progression Telegram ──────────────────────────────────────────

def _make_bar(pct: float, width: int = 18) -> str:
    n = max(0, min(width, int(round(width * pct / 100))))
    return "▓" * n + "░" * (width - n)

class _Prog:
    __slots__ = ("pct", "step", "done")
    def __init__(self):
        self.pct  = 0.0
        self.step = "Démarrage..."
        self.done = False

try:
    import proglog as _proglog
    class _MpLogger(_proglog.ProgressBarLogger):
        """Logger moviepy qui transmet la progression frame par frame à _Prog."""
        def __init__(self, prog: _Prog, s: float = 60, e: float = 99):
            super().__init__()
            self._p, self._s, self._e = prog, s, e
        def bars_callback(self, bar, attr, value, old_value=None):
            if bar == "chunk" and attr == "index":
                total = self.bars.get("chunk", {}).get("total", 1) or 1
                self._p.pct  = self._s + min(1.0, value / total) * (self._e - self._s)
                self._p.step = f"🎞 Encodage : {value}/{total} frames"
    _HAS_PROGLOG = True
except ImportError:
    _MpLogger = None
    _HAS_PROGLOG = False

def download_video(url, folder, filename):
    os.makedirs(folder, exist_ok=True)
    
    class MyLogger:
        def debug(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg): print(f"❌ YT-DLP Error: {msg}")

    def my_hook(d):
        if d.get('status') == 'downloading':
            print(f"📥 {d.get('filename','')} {d.get('_percent_str','?%')} à {d.get('_speed_str','?')} - ETA {d.get('_eta_str','?')}", end='\r')

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

def _normalize(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())

def _flat_lyrics(raw_paroles):
    """Convertit la sortie imbriquée de parole() en liste plate de lignes courtes."""
    lines = []
    for block in raw_paroles:
        if isinstance(block, list):
            lines.extend(s.strip() for s in block if s.strip())
        elif str(block).strip():
            lines.append(str(block).strip())
    return lines

def _align_to_whisper(whisper_words, lyrics_lines):
    """
    Aligne les vraies paroles (AZLyrics) sur les timestamps Whisper mot par mot.

    whisper_words : liste de Word objects (faster-whisper) avec .word .start .end
    lyrics_lines  : liste de strings (lignes de la chanson)

    Retourne : [(line_text, start_time, duration), ...]
    """
    if not whisper_words or not lyrics_lines:
        return []

    lyric_words = []  # (word_str, line_idx)
    for i, line in enumerate(lyrics_lines):
        for w in line.split():
            lyric_words.append((w, i))

    if not lyric_words:
        return []

    w_seq = [_normalize(ww.word) for ww in whisper_words]
    l_seq = [_normalize(lw[0]) for lw in lyric_words]

    matcher = difflib.SequenceMatcher(None, w_seq, l_seq, autojunk=False)

    # timing[lyric_word_idx] = (start, end) depuis Whisper
    timing = {}
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            timing[b + k] = (whisper_words[a + k].start, whisper_words[a + k].end)

    # Agréger au niveau ligne
    line_starts, line_ends = {}, {}
    for li_idx, (_, line_idx) in enumerate(lyric_words):
        if li_idx in timing:
            s, e = timing[li_idx]
            if line_idx not in line_starts:
                line_starts[line_idx] = s
            line_ends[line_idx] = e

    # Cap line ends to prevent text from bleeding into the next line
    sorted_known = sorted(line_starts)
    for i in range(len(sorted_known) - 1):
        curr, nxt = sorted_known[i], sorted_known[i + 1]
        if curr in line_ends and line_ends[curr] > line_starts[nxt] - 0.1:
            line_ends[curr] = line_starts[nxt] - 0.1

    # Interpoler les lignes sans timestamp
    known = sorted(line_starts)
    for i in range(len(lyrics_lines)):
        if i not in line_starts:
            prev = [k for k in known if k < i]
            nxt  = [k for k in known if k > i]
            if prev and nxt:
                p, n = max(prev), min(nxt)
                p_end    = line_ends.get(p, line_starts[p] + 2.0)
                ratio    = (i - p) / (n - p)
                line_starts[i] = p_end + ratio * (line_starts[n] - p_end)
                line_ends[i]   = line_starts[i] + 2.0
            elif prev:
                p = max(prev)
                line_starts[i] = line_ends.get(p, line_starts[p] + 2.0)
                line_ends[i]   = line_starts[i] + 2.0
            elif nxt:
                n = min(nxt)
                line_starts[i] = max(0.0, line_starts[n] - 2.0 * (n - i))
                line_ends[i]   = line_starts[i] + 2.0

    result = []
    for i, line in enumerate(lyrics_lines):
        if i in line_starts:
            start = line_starts[i]
            dur   = max(line_ends.get(i, start + 2.0) - start, 1.5)
            result.append((line, start, dur))
    return result

WBW_STYLES = {
    "blanc":       {"colors": ["white"],                                               "label": "⚪ Blanc"},
    "jaune":       {"colors": ["#FFD700"],                                             "label": "🟡 Jaune"},
    "neon":        {"colors": ["#39FF14", "#FF10F0", "#00FFFF", "#FF6600"],            "label": "🟢 Néon"},
    "arc_en_ciel": {"colors": ["#FF2222", "#FF8800", "#FFFF00", "#00DD00", "#0088FF", "#9400D3"], "label": "🌈 Rainbow"},
}

_whisper_model = None

def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper_model

_font_cache = {}

def generer_lyrics_txt(video_file, output_txt, artist=None, song=None, lang=None, progress=None):
    def _upd(pct, step):
        if progress:
            progress.pct  = pct
            progress.step = step
    try:
        _upd(36, "🎤 Chargement modèle Whisper...")
        model = _get_whisper_model()
        _upd(40, "🎤 Transcription audio en cours...")
        segments, _ = model.transcribe(
            video_file, word_timestamps=True, language=lang, beam_size=2, best_of=2
        )

        all_words = []
        for seg in segments:
            if seg.words:
                all_words.extend(seg.words)

        _upd(54, "🔤 Alignement des paroles...")
        if artist and song and artist != "Unknown" and song != "Unknown":
            try:
                from post_tiktok.lyrics import parole, edit as edit_word
                raw = parole(edit_word(song), artist)
                if raw:
                    lyrics_lines = _flat_lyrics(raw)
                    aligned = _align_to_whisper(all_words, lyrics_lines)
                    if len(aligned) >= 3:
                        with open(output_txt, "w", encoding="utf-8") as f:
                            for text, start, duration in aligned:
                                f.write(f"{text}\n{start:.3f}/{duration:.3f}\n\n")
                        _upd(62, f"✅ {len(aligned)} lignes alignées sur AZLyrics")
                        print(f"✅ Paroles réelles alignées : {len(aligned)} lignes")
                        return True
                    print("⚠️ Alignement insuffisant, fallback Whisper")
            except Exception as e:
                print(f"⚠️ Paroles réelles introuvables : {e}")

        _upd(56, "🎤 Génération paroles Whisper...")
        PAUSE_THRESHOLD = 0.4
        with open(output_txt, "w", encoding="utf-8") as f:
            mots = []
            start_time = None
            prev_end = None
            for word in all_words:
                # Flush current group on natural pause before adding new word
                if mots and prev_end is not None and word.start - prev_end > PAUSE_THRESHOLD:
                    f.write(f"{' '.join(mots)}\n{start_time:.3f}/{prev_end - start_time:.3f}\n\n")
                    mots = []
                    start_time = None
                if start_time is None:
                    start_time = word.start
                mots.append(word.word)
                prev_end = word.end
                if len(mots) >= 6 or any(p in word.word for p in [",", ".", "!", "?"]):
                    f.write(f"{' '.join(mots)}\n{start_time:.3f}/{prev_end - start_time:.3f}\n\n")
                    mots = []
                    start_time = None
            if mots and start_time is not None:
                f.write(f"{' '.join(mots)}\n{start_time:.3f}/{prev_end - start_time:.3f}\n")

        _upd(62, "✅ Transcription terminée")
        return True
    except Exception as e:
        print(f"❌ Whisper error: {e}")
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
        print(f"❌ lire_txt error: {e}")
        return []

def text_with_shadow(text, size=50, fill_color="white"):
    cache_key = ("font", size)
    if cache_key not in _font_cache:
        try:
            _font_cache[cache_key] = ImageFont.truetype("impact.ttf", size)
        except:
            try:
                _font_cache[cache_key] = ImageFont.truetype("arial.ttf", size)
            except:
                _font_cache[cache_key] = ImageFont.load_default()
    font = _font_cache[cache_key]
    
    bbox = font.getbbox(text)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    padding = 50

    img = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    x, y = padding, padding
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
        draw.multiline_text((x + dx, y + dy), text, font=font, fill="black", spacing=10)

    # Texte principal
    draw.multiline_text((x, y), text, font=font, fill=fill_color, spacing=10)
    np_img = numpy.array(img)
    return ImageClip(np_img).set_duration(2)

def create_karaoke_video(video_path, idx_line, output_karaoke, path_txt, duration_limit=60, progress=None):

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Vidéo source introuvable : {video_path}")
    
    if not os.path.exists(path_txt):
        raise FileNotFoundError(f"Fichier lyrics introuvable : {path_txt}")

    if os.path.exists(output_karaoke):
        os.remove(output_karaoke)

    try:
        all_lyrics = lire_txt(path_txt)
        if not (0 <= idx_line < len(all_lyrics)):
            raise ValueError(f"Numéro de ligne invalide : idx_line={idx_line}, total={len(all_lyrics)}")
        lyrics_lines = all_lyrics[idx_line:]

        def _upd(pct, step):
            if progress:
                progress.pct  = pct
                progress.step = step

        _upd(5, "📂 Lecture des paroles...")
        video_start = lyrics_lines[0][1]
        if duration_limit > 0:
            video_end = min(video_start + duration_limit, lyrics_lines[-1][1] + lyrics_lines[-1][2])
        else:
            video_end = lyrics_lines[-1][1] + lyrics_lines[-1][2]

        _upd(10, "🎬 Chargement et découpage vidéo...")
        base_clip = VideoFileClip(video_path, audio=True)
        video_segment = base_clip.subclip(video_start, video_end)

        _upd(20, "📐 Redimensionnement 1080×1920...")
        original_w, original_h = video_segment.w, video_segment.h
        target_w, target_h = 1080, 1920
        scale_factor = target_h / original_h
        new_w = int(original_w * scale_factor)
        video_resized = video_segment.resize((new_w, target_h))

        if new_w > target_w:
            x_center = new_w // 2
            video = video_resized.crop(x1=x_center - target_w//2,
                                       x2=x_center + target_w//2)
        else:
            video = video_resized.resize((target_w, target_h))

        _upd(35, "💬 Création des sous-titres...")
        clips = [video]
        TIMING_OFFSET = 0.2

        for i, (texte, start, duration) in enumerate(lyrics_lines):
            if start < video_end and texte.strip():
                start_adj = max(video_start, start - TIMING_OFFSET)
                if i + 1 < len(lyrics_lines):
                    next_start_adj = max(video_start, lyrics_lines[i + 1][1] - TIMING_OFFSET)
                    duration = min(duration, next_start_adj - start_adj - 0.2)
                remaining = min(duration, video_end - start_adj)
                if remaining > 0.3:
                    try:
                        texte_court = texte[:50] + "..." if len(texte) > 50 else texte
                        txt_clip = text_with_shadow(texte_court).set_start(
                            start_adj - video_start
                        ).set_duration(remaining).set_position(("center", 0.72), relative=True)
                        clips.append(txt_clip)
                    except Exception:
                        pass

        _upd(50, "🎞 Assemblage des clips...")
        final = CompositeVideoClip(clips, size=(1080, 1920))

        if final.duration <= 0:
            raise ValueError("Durée de vidéo finale invalide")

        _upd(60, "🎞 Encodage vidéo en cours...")
        mp_logger = _MpLogger(progress, s=60, e=99) if (_HAS_PROGLOG and progress) else None

        final.write_videofile(
            output_karaoke,
            codec="libx264",
            audio_codec="aac",
            preset="fast",
            bitrate="2000k",
            fps=24,
            temp_audiofile=None,
            remove_temp=True,
            verbose=False,
            logger=mp_logger or None
        )
        _upd(99, "✅ Encodage terminé !")
        
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

def process_song(artist, song, url, lang=None, progress=None):
    def _upd(pct, step):
        if progress:
            progress.pct  = pct
            progress.step = step

    safe_filename = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
    video_path = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
    lyrics_path_txt = os.path.join(FOLDER_PATH, f"{safe_filename}.txt")

    if not url:
        _upd(5, "🔍 Recherche de la vidéo YouTube...")
        search_query = f"ytsearch1:{artist} {song} official"
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(search_query, download=False)
                if info and 'entries' in info and len(info['entries']) > 0:
                    url = info['entries'][0]['webpage_url']
                else:
                    return None
        except Exception as e:
            print(f"❌ YouTube search error: {e}")
            return None

    if not os.path.exists(video_path):
        _upd(10, "📥 Téléchargement de la vidéo...")
        result = download_video(url, FOLDER_PATH, safe_filename)
        if not result:
            return None
    else:
        _upd(30, "♻️ Vidéo déjà en cache")

    if not os.path.exists(lyrics_path_txt):
        _upd(35, "🎤 Transcription Whisper...")
        success = generer_lyrics_txt(video_path, lyrics_path_txt, artist=artist, song=song, lang=lang, progress=progress)
        if not success:
            return None
    else:
        _upd(62, "♻️ Paroles déjà en cache")

    return lyrics_path_txt

def log_attempt(first_name, user_id, message, result, color):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] 🔍 {first_name} ({user_id})")
    print(f"   ↪️ Message : {message}")
    print(f"   🎨 Couleur : {color}")
    print(f"   {"✅" if result else "❌"} Résultat : {'Succès' if result else 'Échec'}")
    print(50 * "-")

async def send_lyrics_karaoke(update, context, index):
    context.user_data["pending_callback"] = "karaoke"
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
        context.user_data.pop("pending_callback", None)
        artist = context.user_data.get("artist", "")
        song = context.user_data.get("song", "")
        
        safe_filename = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
        video_path = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
        output_karaoke = os.path.join(FOLDER_PATH, f"{safe_filename}_karaoke.mp4")
        lyrics_path = os.path.join(FOLDER_PATH, f"{safe_filename}.txt")

        prog = _Prog()
        status = await update.callback_query.message.reply_text(
            f"🎬 Génération vidéo...\n[{_make_bar(0)}]  0%\nPréparation..."
        )

        async def _upd_loop():
            while not prog.done:
                bar = _make_bar(prog.pct)
                pct = int(prog.pct)
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=status.message_id,
                        text=f"🎬 Génération vidéo...\n[{bar}] {pct}%\n{prog.step}"
                    )
                except Exception:
                    pass
                await asyncio.sleep(2)

        upd = asyncio.create_task(_upd_loop())
        loop = asyncio.get_running_loop()

        try:
            await loop.run_in_executor(
                None,
                lambda: create_karaoke_video(video_path, idx, output_karaoke, lyrics_path, progress=prog)
            )
        except Exception as e:
            prog.done = True
            upd.cancel()
            print(f"❌ Erreur création vidéo karaoke: {e}")
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, message_id=status.message_id,
                text=f"❌ Erreur création vidéo : {str(e)[:100]}"
            )
            return
        finally:
            prog.done = True
            upd.cancel()

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status.message_id,
            text="✅ Vidéo prête ! Envoi en cours..."
        )

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
            await update.callback_query.message.reply_text(
                f"{song} || {artist}\n#karaoke #fyp #pourtoi #{song} #{artist}"
            )
            for i in [output_karaoke, lyrics_path, video_path]:
                os.remove(i) if os.path.exists(i) else None

        except FileNotFoundError:
            await update.callback_query.message.reply_text("❌ Fichier vidéo introuvable")
            print(f"❌ Fichier non trouvé : {output_karaoke}")

        except Exception as e:
            await update.callback_query.message.reply_text(f"❌ Erreur envoi vidéo : {str(e)[:100]}")

async def echo_karaoke(update, context):
    user = update.message.from_user
    first_name = user.first_name or "Inconnu"
    user_id = user.id
    message = update.message.text
    loop = asyncio.get_running_loop()

    log_attempt(first_name, user_id, message, result=True, color=None)

    async def _run_with_progress(fn, *args):
        prog = _Prog()
        status = await update.message.reply_text(
            f"⏳ Traitement en cours...\n[{_make_bar(0)}]  0%\nDémarrage..."
        )
        async def _upd_loop():
            while not prog.done:
                bar  = _make_bar(prog.pct)
                pct  = int(prog.pct)
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=status.message_id,
                        text=f"⏳ Traitement en cours...\n[{bar}] {pct}%\n{prog.step}"
                    )
                except Exception:
                    pass
                await asyncio.sleep(2)
        upd = asyncio.create_task(_upd_loop())
        try:
            result = await loop.run_in_executor(None, lambda: fn(*args, progress=prog))
        finally:
            prog.done = True
            upd.cancel()
        return result, status

    if message.startswith(("https://www.youtube.com/watch", "https://youtu.be/", "https://www.youtube.com/shorts/")):
        try:
            lyrics_path, status = await _run_with_progress(process_song, "Unknown", "Unknown", message)
            if not lyrics_path:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id, message_id=status.message_id,
                    text="❌ Échec du traitement de la vidéo YouTube"
                )
                return
            lines = lire_txt(lyrics_path)
            if not lines:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id, message_id=status.message_id,
                    text="❌ Aucune parole détectée dans la vidéo"
                )
                return
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, message_id=status.message_id,
                text="✅ Prêt ! Sélectionne un bloc de paroles."
            )
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
            context.user_data["lang"] = message[-2:]
            message = message[:-2].strip()
            await update.message.reply_text(f"🌐 Langue définie sur : {context.user_data['lang']}")

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
        lang = context.user_data.get("lang")

        lyrics_path, status = await _run_with_progress(process_song, artist, song, None, lang)
        if not lyrics_path:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, message_id=status.message_id,
                text="❌ Impossible de traiter cette chanson"
            )
            return
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status.message_id,
            text="✅ Prêt ! Sélectionne un bloc de paroles."
        )
            
        lines = lire_txt(lyrics_path)
        if not lines:
            await update.message.reply_text("❌ Aucune parole générée pour cette chanson")
            return
            
        context.user_data["lyrics"] = lines
        await send_lyrics_karaoke(update, context, index=0)
        
    except Exception as e:
        print(f"❌ Erreur echo_karaoke: {e}")
        await update.message.reply_text("❌ Erreur lors du traitement de la demande")

# ── Word-by-word ────────────────────────────────────────────────────────────

def _build_word_entries(lyric_words, timing):
    """Construit [(word, start, duration)] en interpolant les mots sans timestamp."""
    entries = []
    prev_end = 0.0
    for i, word in enumerate(lyric_words):
        if i in timing:
            s, e = timing[i]
            entries.append((word, s, max(e - s, 0.08)))
            prev_end = e
        else:
            next_known = next((j for j in range(i + 1, len(lyric_words)) if j in timing), None)
            if next_known is not None:
                ns = timing[next_known][0]
                gap = max(ns - prev_end, 0.1)
                dur = gap / (next_known - i + 1)
            else:
                dur = 0.3
            entries.append((word, prev_end, dur))
            prev_end += dur
    return entries


def generer_words_txt(video_file, output_txt, artist=None, song=None, lang=None, progress=None):
    def _upd(pct, step):
        if progress:
            progress.pct = pct
            progress.step = step
    try:
        _upd(36, "🎤 Chargement modèle Whisper...")
        model = _get_whisper_model()
        _upd(40, "🎤 Transcription mot par mot...")
        segments, _ = model.transcribe(
            video_file, word_timestamps=True, language=lang, beam_size=2, best_of=2
        )
        all_words = [w for seg in segments if seg.words for w in seg.words]

        # Essaie d'aligner avec les vraies paroles (AZLyrics / Genius)
        if artist and song and artist != "Unknown" and song != "Unknown":
            try:
                from post_tiktok.lyrics import parole, edit as edit_word
                raw = parole(edit_word(song), artist)
                if raw:
                    lyric_words = [w for line in _flat_lyrics(raw) for w in line.split() if w]
                    w_seq = [_normalize(ww.word) for ww in all_words]
                    l_seq = [_normalize(lw) for lw in lyric_words]
                    matcher = difflib.SequenceMatcher(None, w_seq, l_seq, autojunk=False)
                    timing = {}
                    for a, b, size in matcher.get_matching_blocks():
                        for k in range(size):
                            timing[b + k] = (all_words[a + k].start, all_words[a + k].end)

                    if len(timing) >= len(lyric_words) * 0.3:
                        entries = _build_word_entries(lyric_words, timing)
                        if entries:
                            _upd(58, f"✅ {len(entries)} mots alignés sur paroles réelles")
                            with open(output_txt, "w", encoding="utf-8") as f:
                                for word, start, dur in entries:
                                    if word.strip():
                                        f.write(f"{word.strip()}\n{start:.3f}/{dur:.3f}\n\n")
                            return True
                    print("⚠️ Alignement insuffisant, fallback Whisper")
            except Exception as e:
                print(f"⚠️ Word alignment failed: {e}")

        # Fallback : timestamps Whisper directs
        _upd(58, "📝 Écriture des timestamps Whisper...")
        with open(output_txt, "w", encoding="utf-8") as f:
            for w in all_words:
                word = w.word.strip()
                if word:
                    f.write(f"{word}\n{w.start:.3f}/{max(w.end - w.start, 0.08):.3f}\n\n")

        _upd(62, f"✅ {len(all_words)} mots transcrits")
        return True
    except Exception as e:
        print(f"❌ Words error: {e}")
        return False


def create_wordbyword_video(video_path, output_path, path_words_txt, duration_limit=60, style="blanc", progress=None):
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Vidéo source introuvable : {video_path}")
    if not os.path.exists(path_words_txt):
        raise FileNotFoundError(f"Fichier mots introuvable : {path_words_txt}")
    if os.path.exists(output_path):
        os.remove(output_path)

    def _upd(pct, step):
        if progress:
            progress.pct = pct
            progress.step = step

    try:
        word_entries = lire_txt(path_words_txt)
        if not word_entries:
            raise ValueError("Aucun mot trouvé dans le fichier")

        _upd(5, "📂 Lecture des mots...")
        video_start = word_entries[0][1]
        video_end = min(video_start + duration_limit, word_entries[-1][1] + word_entries[-1][2]) if duration_limit > 0 else word_entries[-1][1] + word_entries[-1][2]

        _upd(10, "🎬 Chargement et découpage vidéo...")
        base_clip = VideoFileClip(video_path, audio=True)
        video_segment = base_clip.subclip(video_start, video_end)

        _upd(20, "📐 Redimensionnement 1080×1920...")
        target_w, target_h = 1080, 1920
        scale_factor = target_h / video_segment.h
        new_w = int(video_segment.w * scale_factor)
        video_resized = video_segment.resize((new_w, target_h))
        if new_w > target_w:
            x_center = new_w // 2
            video = video_resized.crop(x1=x_center - target_w // 2, x2=x_center + target_w // 2)
        else:
            video = video_resized.resize((target_w, target_h))

        _upd(35, "💬 Création des clips mots...")
        colors = WBW_STYLES.get(style, WBW_STYLES["blanc"])["colors"]
        clips = [video]
        color_idx = 0
        for word, start, duration in word_entries:
            if start >= video_end or not word.strip():
                continue
            remaining = min(duration, video_end - start)
            if remaining > 0.05:
                try:
                    fill = colors[color_idx % len(colors)]
                    color_idx += 1
                    txt_clip = (
                        text_with_shadow(word.strip(), size=90, fill_color=fill)
                        .set_start(start - video_start)
                        .set_duration(remaining)
                        .set_position("center")
                    )
                    clips.append(txt_clip)
                except Exception:
                    pass

        _upd(50, "🎞 Assemblage des clips...")
        final = CompositeVideoClip(clips, size=(target_w, target_h))
        if final.duration <= 0:
            raise ValueError("Durée de vidéo finale invalide")

        _upd(60, "🎞 Encodage vidéo en cours...")
        mp_logger = _MpLogger(progress, s=60, e=99) if (_HAS_PROGLOG and progress) else None
        final.write_videofile(
            output_path, codec="libx264", audio_codec="aac",
            preset="fast", bitrate="2000k", fps=24,
            temp_audiofile=None, remove_temp=True, verbose=False,
            logger=mp_logger or None
        )
        _upd(99, "✅ Encodage terminé !")
        final.close()
        video_segment.close()
        base_clip.close()
        time.sleep(2)

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            print(f"📏 Taille finale : {os.path.getsize(output_path) / (1024*1024):.2f} MB")
            return True
        return False

    except Exception:
        for var in ('final', 'video_segment', 'base_clip'):
            try:
                if var in locals(): locals()[var].close()
            except Exception:
                pass
        raise


def process_wordbyword(artist, song, url, lang=None, progress=None):
    def _upd(pct, step):
        if progress:
            progress.pct = pct
            progress.step = step

    safe_filename = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
    video_path = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
    words_path = os.path.join(FOLDER_PATH, f"{safe_filename}.words.txt")

    if not url:
        _upd(5, "🔍 Recherche YouTube...")
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(f"ytsearch1:{artist} {song} clip officiel", download=False)
                if info and 'entries' in info and info['entries']:
                    url = info['entries'][0]['webpage_url']
                else:
                    return None
        except Exception:
            return None

    if not os.path.exists(video_path):
        _upd(10, "📥 Téléchargement vidéo...")
        if not download_video(url, FOLDER_PATH, safe_filename):
            return None
    else:
        _upd(30, "♻️ Vidéo déjà en cache")

    if not os.path.exists(words_path):
        _upd(35, "🎤 Transcription mot par mot...")
        if not generer_words_txt(video_path, words_path, artist=artist, song=song, lang=lang, progress=progress):
            return None
    else:
        _upd(62, "♻️ Mots déjà en cache")

    return words_path


def _wbw_keyboard(current_style="blanc"):
    dur_row = [
        InlineKeyboardButton("15s",     callback_data="wbw_dur:15"),
        InlineKeyboardButton("30s",     callback_data="wbw_dur:30"),
        InlineKeyboardButton("60s",     callback_data="wbw_dur:60"),
        InlineKeyboardButton("90s",     callback_data="wbw_dur:90"),
        InlineKeyboardButton("Tout", callback_data="wbw_dur:0"),
    ]
    style_row = [
        InlineKeyboardButton(
            ("✅ " if s == current_style else "") + WBW_STYLES[s]["label"],
            callback_data=f"wbw_style:{s}"
        )
        for s in WBW_STYLES
    ]
    return InlineKeyboardMarkup([dur_row, style_row])


async def _generate_and_send_wbw(context, chat_id, artist, song, words_path, duration_limit, style):
    loop = asyncio.get_running_loop()
    safe_filename = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
    video_path  = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
    output_path = os.path.join(FOLDER_PATH, f"{safe_filename}_wbw.mp4")

    prog = _Prog()
    status = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎬 Génération word-by-word...\n[{_make_bar(0)}]  0%\nPréparation..."
    )

    async def _upd_loop():
        while not prog.done:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=status.message_id,
                    text=f"🎬 Génération word-by-word...\n[{_make_bar(prog.pct)}] {int(prog.pct)}%\n{prog.step}"
                )
            except Exception:
                pass
            await asyncio.sleep(2)

    upd = asyncio.create_task(_upd_loop())
    try:
        await loop.run_in_executor(
            None,
            lambda: create_wordbyword_video(
                video_path, output_path, words_path,
                duration_limit=duration_limit, style=style, progress=prog
            )
        )
    except Exception as e:
        prog.done = True
        upd.cancel()
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=status.message_id,
            text=f"❌ Erreur : {str(e)[:100]}"
        )
        return
    finally:
        prog.done = True
        upd.cancel()

    await context.bot.edit_message_text(
        chat_id=chat_id, message_id=status.message_id,
        text="✅ Vidéo prête ! Envoi en cours..."
    )

    if not os.path.exists(output_path):
        await context.bot.send_message(chat_id=chat_id, text="❌ La vidéo n'a pas été générée")
        return
    if os.path.getsize(output_path) > 50 * 1024 * 1024:
        await context.bot.send_message(chat_id=chat_id, text="❌ Vidéo trop volumineuse pour Telegram (>50MB)")
        return

    try:
        with open(output_path, "rb") as f:
            await context.bot.send_video(
                chat_id=chat_id, video=f, supports_streaming=True,
                read_timeout=300, write_timeout=300, connect_timeout=300
            )
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{song} || {artist}\n#wordbyword #fyp #pourtoi #{song} #{artist}"
        )
        for path in [output_path, words_path, video_path]:
            if os.path.exists(path):
                os.remove(path)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Erreur envoi : {str(e)[:100]}")


async def button_handler_wordbyword(update, context):
    query = update.callback_query
    await query.answer()
    action, value = query.data.split(":", 1)

    if action == "wbw_style":
        context.user_data["wbw_style"] = value
        current_style = value
        try:
            await query.edit_message_reply_markup(reply_markup=_wbw_keyboard(current_style))
        except Exception:
            pass
        return

    if action == "wbw_dur":
        duration_limit = int(value)
        artist     = context.user_data.get("wbw_artist", "Unknown")
        song       = context.user_data.get("wbw_song",   "Unknown")
        words_path = context.user_data.get("wbw_words_path")
        style      = context.user_data.get("wbw_style", "blanc")

        if not words_path or not os.path.exists(words_path):
            await query.edit_message_text("❌ Session expirée, renvoie artiste:titre")
            return

        label = f"{duration_limit}s" if duration_limit > 0 else "complète"
        await query.edit_message_text(f"⏳ Génération {label} en style {WBW_STYLES[style]['label']}...")

        await _generate_and_send_wbw(
            context, update.effective_chat.id,
            artist, song, words_path, duration_limit, style
        )


async def echo_wordbyword(update, context):
    user    = update.message.from_user
    message = update.message.text
    loop    = asyncio.get_running_loop()

    log_attempt(user.first_name or "Inconnu", user.id, message, result=True, color=None)

    async def _run_with_progress(fn, *args):
        prog = _Prog()
        status = await update.message.reply_text(
            f"⏳ Traitement en cours...\n[{_make_bar(0)}]  0%\nDémarrage..."
        )
        async def _upd_loop():
            while not prog.done:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=status.message_id,
                        text=f"⏳ Traitement en cours...\n[{_make_bar(prog.pct)}] {int(prog.pct)}%\n{prog.step}"
                    )
                except Exception:
                    pass
                await asyncio.sleep(2)
        upd = asyncio.create_task(_upd_loop())
        try:
            result = await loop.run_in_executor(None, lambda: fn(*args, progress=prog))
        finally:
            prog.done = True
            upd.cancel()
        return result, status

    artist, song = "Unknown", "Unknown"

    if message.startswith(("https://www.youtube.com/watch", "https://youtu.be/", "https://www.youtube.com/shorts/")):
        words_path, status = await _run_with_progress(process_wordbyword, artist, song, message)
    else:
        if ":" not in message:
            await update.message.reply_text("❌ Format attendu : artiste:titre ou lien YouTube")
            return
        if message[-2:] in ("fr", "en", "es", "it", "de"):
            context.user_data["lang"] = message[-2:]
            message = message[:-2].strip()
        parts = message.split(":", 1)
        if len(parts) != 2:
            await update.message.reply_text("❌ Format attendu : artiste:titre")
            return
        artist, song = [x.strip() for x in parts]
        lang = context.user_data.get("lang")
        words_path, status = await _run_with_progress(process_wordbyword, artist, song, None, lang)

    if not words_path:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status.message_id,
            text="❌ Impossible de traiter cette chanson"
        )
        return

    context.user_data["wbw_artist"]     = artist
    context.user_data["wbw_song"]       = song
    context.user_data["wbw_words_path"] = words_path
    current_style = context.user_data.get("wbw_style", "blanc")

    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id, message_id=status.message_id,
        text="✅ Prêt ! Choisis la durée et le style :",
        reply_markup=_wbw_keyboard(current_style)
    )