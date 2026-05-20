import yt_dlp, warnings, logging, numpy, time, os, asyncio, datetime, difflib, re

from PIL import Image, ImageDraw, ImageFont
from PIL import Image
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from moviepy.editor import VideoFileClip, CompositeVideoClip, ImageClip
from faster_whisper import WhisperModel
from moviepy.config import change_settings

change_settings({"IMAGEMAGICK_BINARY": r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"})
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("TOKEN")
user_colors = {}
FOLDER_PATH = os.getenv("FOLDER_PATH", ".")

warnings.filterwarnings("ignore")
logging.getLogger("ctranslate2").setLevel(logging.ERROR)

# ── Barre de progression Telegram ──────────────────────────────────────────

def _make_bar(pct: float, width: int = 18) -> str:
    n = max(0, min(width, int(round(width * pct / 100))))
    return "▓" * n + "░" * (width - n)

class _Prog:
    __slots__ = ("pct", "step", "done", "t_start", "frame_cur", "frame_tot", "lyrics_source")
    def __init__(self):
        self.pct           = 0.0
        self.step          = "Démarrage..."
        self.done          = False
        self.t_start       = time.time()
        self.frame_cur     = 0
        self.frame_tot     = 0
        self.lyrics_source = "whisper"

def _format_status(prog: "_Prog") -> str:
    elapsed = time.time() - prog.t_start
    mins, secs = divmod(int(elapsed), 60)
    time_str = f"{mins:02d}:{secs:02d}" if mins else f"{secs}s"
    bar = _make_bar(prog.pct)
    return f"[{bar}] ⏱ {time_str}\n{prog.step}"

try:
    import proglog as _proglog
    class _MpLogger(_proglog.ProgressBarLogger):
        """Logger moviepy — transmet la progression frame par frame à _Prog."""
        def __init__(self, prog: "_Prog", s: float = 60, e: float = 99):
            super().__init__()
            self._p, self._s, self._e = prog, s, e
        def bars_callback(self, bar, attr, value, old_value=None):
            if bar != "chunk":
                return
            if attr == "total":
                self._p.frame_tot = value or 1
            elif attr == "index":
                self._p.frame_cur = value
                tot = self._p.frame_tot or 1
                self._p.pct  = self._s + min(1.0, value / tot) * (self._e - self._s)
                self._p.step = f"🎞 Encodage : {value}/{tot} frames"
    _HAS_PROGLOG = True
except ImportError:
    _MpLogger = None
    _HAS_PROGLOG = False

async def _show_duration_picker(message):
    keyboard = [
        [
            InlineKeyboardButton("⏱ 15s", callback_data="kdur:15"),
            InlineKeyboardButton("⏱ 30s", callback_data="kdur:30"),
            InlineKeyboardButton("⏱ 60s", callback_data="kdur:60"),
        ],
        [
            InlineKeyboardButton("⏱ 90s", callback_data="kdur:90"),
            InlineKeyboardButton("🎵 Chanson complète", callback_data="kdur:0"),
        ]
    ]
    await message.reply_text(
        "⏱ Choisir la durée de la vidéo karaoke :",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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

def generer_lyrics_txt(video_file, output_txt, artist=None, song=None, lang=None, progress=None):
    def _upd(pct, step):
        if progress:
            progress.pct  = pct
            progress.step = step
    try:
        _upd(36, "🎤 Chargement modèle Whisper...")
        model = WhisperModel("small", device="cpu", compute_type="int8")
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
                        if progress:
                            progress.lyrics_source = "azlyrics"
                        _upd(62, f"✅ {len(aligned)} lignes alignées sur AZLyrics")
                        print(f"✅ Paroles réelles alignées : {len(aligned)} lignes")
                        return True
                    print("⚠️ Alignement insuffisant, fallback Whisper")
            except Exception as e:
                print(f"⚠️ Paroles réelles introuvables : {e}")

        _upd(56, "🎤 Génération paroles Whisper...")
        with open(output_txt, "w", encoding="utf-8") as f:
            mots = []
            start_time = None
            end_time = 0
            for word in all_words:
                if start_time is None:
                    start_time = word.start
                mots.append(word.word)
                end_time = word.end
                if len(mots) >= 6 or any(p in word.word for p in [",", ".", "!", "?"]):
                    f.write(f"{' '.join(mots)}\n{start_time:.3f}/{end_time - start_time:.3f}\n\n")
                    mots = []
                    start_time = None
            if mots and start_time is not None:
                f.write(f"{' '.join(mots)}\n{start_time:.3f}/{end_time - start_time:.3f}\n")

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

def create_karaoke_video(video_path, idx_line, output_karaoke, path_txt, duration_limit=60, progress=None):

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
        new_h = target_h
        video_resized = video_segment.resize((new_w, new_h))

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
                    duration = min(duration, next_start_adj - start_adj - 0.05)
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
            ffmpeg_params=["-threads", "4"],
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
    print(f"   {'✅' if result else '❌'} Résultat : {'Succès' if result else 'Échec'}")
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

async def _run_karaoke_generation(update, context, line_idx, duration_limit):
    """Lance la génération karaoke avec barre de progression et envoie la vidéo."""
    query = update.callback_query
    artist = context.user_data.get("artist", "")
    song   = context.user_data.get("song", "")

    safe_filename  = f"{artist} - {song}".replace("/", "-").replace("\\", "-")
    video_path     = os.path.join(FOLDER_PATH, f"{safe_filename}.mp4")
    output_karaoke = os.path.join(FOLDER_PATH, f"{safe_filename}_karaoke.mp4")
    lyrics_path    = os.path.join(FOLDER_PATH, f"{safe_filename}.txt")

    prog      = _Prog()
    dur_label = f"{duration_limit}s" if duration_limit else "chanson complète"
    status    = await query.message.reply_text(
        f"🎬 Génération ({dur_label})...\n{_format_status(prog)}"
    )

    async def _upd_loop():
        while not prog.done:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=status.message_id,
                    text=f"🎬 Génération ({dur_label})...\n{_format_status(prog)}"
                )
            except Exception:
                pass
            await asyncio.sleep(2)

    upd  = asyncio.create_task(_upd_loop())
    loop = asyncio.get_running_loop()

    try:
        await loop.run_in_executor(
            None,
            lambda: create_karaoke_video(
                video_path, line_idx, output_karaoke, lyrics_path,
                duration_limit=duration_limit, progress=prog
            )
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

    src_label = "🎵 AZLyrics" if prog.lyrics_source == "azlyrics" else "🎤 Whisper"
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id, message_id=status.message_id,
        text=f"✅ Vidéo prête ! Envoi en cours...\nParoles : {src_label}"
    )

    if not os.path.exists(output_karaoke):
        await query.message.reply_text("❌ La vidéo n'a pas été générée correctement")
        return

    file_size = os.path.getsize(output_karaoke)
    print(f"📹 Taille vidéo karaoke : {file_size / (1024*1024):.2f} MB")

    if file_size > 50 * 1024 * 1024:
        await query.message.reply_text("❌ Vidéo trop volumineuse pour Telegram (>50MB)")
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
        print("✅ Vidéo karaoke envoyée avec succès")
        await query.message.reply_text(
            f"{song} || {artist}\n#karaoke #fyp #pourtoi #{song} #{artist}"
        )
        for path in [output_karaoke, lyrics_path, video_path]:
            if os.path.exists(path):
                os.remove(path)

    except FileNotFoundError:
        await query.message.reply_text("❌ Fichier vidéo introuvable")
        print(f"❌ Fichier non trouvé : {output_karaoke}")

    except Exception as e:
        await query.message.reply_text(f"❌ Erreur envoi vidéo : {str(e)[:100]}")

async def button_handler_karaoke(update, context):
    query = update.callback_query
    await query.answer()
    action, idx = query.data.split(":")
    idx = int(idx)

    if action == "next":
        await send_lyrics_karaoke(update, context, idx + 2)
    elif action == "back":
        await send_lyrics_karaoke(update, context, max(0, idx - 2))
    elif action == "select":
        context.user_data["pending_karaoke_idx"] = idx
        await _show_duration_picker(query.message)
    elif action == "kdur":
        duration_limit = idx  # 0 = chanson complète
        line_idx = context.user_data.get("pending_karaoke_idx", 0)
        await _run_karaoke_generation(update, context, line_idx, duration_limit)

async def echo_karaoke(update, context):
    user = update.message.from_user
    first_name = user.first_name or "Inconnu"
    user_id = user.id
    message = update.message.text
    loop = asyncio.get_running_loop()

    log_attempt(first_name, user_id, message, result=True, color=None)

    async def _run_with_progress(fn, *args):
        prog   = _Prog()
        status = await update.message.reply_text(
            f"⏳ Traitement en cours...\n{_format_status(prog)}"
        )
        async def _upd_loop():
            while not prog.done:
                try:
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=status.message_id,
                        text=f"⏳ Traitement en cours...\n{_format_status(prog)}"
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
        return result, status, prog

    if message.startswith("https://www.youtube.com/watch?v="):
        try:
            lyrics_path, status, prog = await _run_with_progress(process_song, "Unknown", "Unknown", message)
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
        lang = context.user_data.get("language")
        if message[-2:] in ("fr", "en", "es", "it", "de"):
            lang = message[-2:]
            context.user_data["language"] = lang
            message = message[:-2].strip()
            await update.message.reply_text(f"🌐 Langue définie sur : {lang}")

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

        lyrics_path, status, prog = await _run_with_progress(process_song, artist, song, None, lang)
        if not lyrics_path:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id, message_id=status.message_id,
                text="❌ Impossible de traiter cette chanson"
            )
            return

        src_label = "🎵 AZLyrics" if prog.lyrics_source == "azlyrics" else "🎤 Whisper"
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id, message_id=status.message_id,
            text=f"✅ Prêt ! Sélectionne un bloc de paroles.\nParoles : {src_label}"
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
