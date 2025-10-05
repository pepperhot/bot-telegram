import asyncio
import json
import os
import time
import threading
from collections import deque
from datetime import datetime
from enum import Enum
from io import BytesIO
import requests
import yt_dlp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw
import customtkinter
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, GiftEvent
import tkinter as tk
from tkinter import messagebox

# ==================== CONFIGURATION ====================
TIKTOK_USERNAME = "@mpl.id.official"
JSON_FILE = "live/donations.json"
SESSIONS_FILE = "live/sessions.json"
SONGS_CACHE = "live/songs_cache.json"
TEMP_FOLDER = "live/temp"
IMAGES_FOLDER = "live/images/user"
DEFAULT_USER = "default_user"
WHITELIST_USERS = ["m0idu77580"]

# Configuration du jeu
LOBBY_DURATION = 60
SONG_MAX_DURATION = 60
VOTING_DURATION = 60
MIN_DONATION_TO_PLAY = 1.0
MAX_SONGS_IN_QUEUE = 5
MAX_VIDEO_SIZE_MB = 50

# 🎵 Playlist par défaut (5 chansons de base)
DEFAULT_PLAYLIST = [
    ("system", "Imagine Dragons", "Believer"),
    ("system", "Ed Sheeran", "Shape of You"),
    ("system", "The Weeknd", "Blinding Lights"),
    ("system", "Dua Lipa", "Levitating"),
    ("system", "Bruno Mars", "Uptown Funk")
]

# Tables des gifts TikTok
TIKTOK_GIFTS = {
    "Community Fest": 1, "Smile Face": 10, "Rose": 10, "Star": 50, "Blow a Kiss": 100,
    "Summer Sun": 100, "Lightning": 100, "Sunflower": 100, "Flame Heart GDM": 200,
    "Panda": 200, "Teddy Bear": 200, "Hat and Mustache": 500, "Iced Coffee": 500,
    "Panda Dance": 500, "Love Moon": 500, "TOFU Cat": 500, "Concert": 1000,
    "Drama Queen": 1000, "Rocket": 1000, "Fireworks": 1000, "Crown": 1000,
    "Gold Watch": 1000, "Love Bang": 1000, "TikTok Cake": 500,
    "Ferrari": 5000, "Diamond": 5000, "Car": 5000,
    "Ferrari Classic": 10000, "Lamborghini": 10000, "Castle": 10000, "Yacht": 100000
}

# ==================== ENUMS ====================
class GamePhase(Enum):
    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    VOTING = "VOTING"
    ENDED = "ENDED"

# ==================== UTILITAIRES ====================
def ensure_folders():
    os.makedirs(TEMP_FOLDER, exist_ok=True)
    os.makedirs(IMAGES_FOLDER, exist_ok=True)

def load_json(filepath, default=None):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def cleanup_temp_files():
    try:
        for file in os.listdir(TEMP_FOLDER):
            filepath = os.path.join(TEMP_FOLDER, file)
            if os.path.isfile(filepath):
                os.remove(filepath)
    except Exception as e:
        print(f"❌ Erreur nettoyage: {e}")

def make_song_key(artist, song, user_id):
    return f"{user_id}_{artist.lower()}_{song.lower()}"

def get_cached_song(artist, song, user_id):
    """Récupère le chemin d'une chanson en cache"""
    cache = load_json(SONGS_CACHE, {})
    key = make_song_key(artist, song, user_id)
    
    if key in cache and os.path.exists(cache[key]["path"]):
        return cache[key]["path"]
    return None

def get_songs_from_temp_folder():
    """Récupère toutes les vidéos déjà présentes dans le dossier temp"""
    songs = []
    try:
        if not os.path.exists(TEMP_FOLDER):
            return songs
        
        for filename in os.listdir(TEMP_FOLDER):
            if filename.endswith('.mp4'):
                filepath = os.path.join(TEMP_FOLDER, filename)
                # Format: system_Artist Name_Song Title.mp4
                try:
                    # Enlever l'extension .mp4
                    name_without_ext = filename.replace('.mp4', '')
                    # Séparer par underscore (1er = user, reste = artist_song)
                    parts = name_without_ext.split('_', 1)
                    
                    if len(parts) >= 2:
                        user_id = parts[0]
                        # Séparer artist et song par le dernier underscore
                        artist_song = parts[1]
                        # Chercher le dernier underscore pour séparer artiste et titre
                        last_underscore = artist_song.rfind('_')
                        
                        if last_underscore > 0:
                            artist = artist_song[:last_underscore]
                            song = artist_song[last_underscore + 1:]
                            
                            songs.append({
                                'user_id': user_id,
                                'artist': artist,
                                'song': song,
                                'path': filepath,
                                'filename': filename
                            })
                            print(f"   📀 Trouvé: {artist} - {song} (par @{user_id})")
                except Exception as e:
                    print(f"   ⚠️ Fichier ignoré (format invalide): {filename}")
                    continue
    except Exception as e:
        print(f"❌ Erreur lecture dossier temp: {e}")
    
    return songs

def rebuild_cache_from_temp():
    """Reconstruit le cache à partir des fichiers existants dans temp/"""
    print("\n🔄 Scan du dossier temp/ pour détecter les vidéos existantes...")
    print("=" * 60)
    cache = {}
    songs = get_songs_from_temp_folder()
    
    if not songs:
        print("⚠️ Aucune vidéo trouvée dans le dossier temp/")
        print("💡 Place tes fichiers au format: system_Artist Name_Song Title.mp4")
        print("=" * 60 + "\n")
        return songs
    
    for song_info in songs:
        key = make_song_key(song_info['artist'], song_info['song'], song_info['user_id'])
        cache[key] = {
            "path": song_info['path'],
            "timestamp": datetime.now().isoformat()
        }
    
    save_json(SONGS_CACHE, cache)
    print("=" * 60)
    print(f"✅ {len(cache)} vidéos détectées et ajoutées au cache")
    print("=" * 60 + "\n")
    return songs

def save_to_cache(artist, song, user_id, path):
    """Sauvegarde une chanson dans le cache"""
    cache = load_json(SONGS_CACHE, {})
    key = make_song_key(artist, song, user_id)
    cache[key] = {"path": path, "timestamp": datetime.now().isoformat()}
    save_json(SONGS_CACHE, cache)

# ==================== GESTIONNAIRE DE SESSION ====================
class KaraokeSession:
    def __init__(self, use_existing_songs=True):
        self.phase = GamePhase.LOBBY
        self.participants = {}
        self.song_queue = deque()
        self.current_performer = None
        self.current_song = None
        self.phase_start_time = time.time()
        self.votes = {}
        self.command_stats = {"join":0,"song":0,"vote":0,"skip":0}
        
        # 🎵 Charger UNIQUEMENT les chansons existantes dans temp/
        if use_existing_songs:
            existing_songs = get_songs_from_temp_folder()
            if existing_songs:
                self._load_existing_songs(existing_songs)
            else:
                print("⚠️ AUCUNE CHANSON TROUVÉE - La queue est vide")
                print("💡 Place des fichiers .mp4 dans live/temp/ au format:")
                print("   system_Artist Name_Song Title.mp4\n")
    
    def _load_existing_songs(self, songs):
        """Charge les chansons déjà présentes dans temp/"""
        print("🎵 Chargement des chansons dans la queue de lecture...")
        print("-" * 60)
        for i, song_info in enumerate(songs, 1):
            self.song_queue.append((
                song_info['user_id'],
                song_info['artist'],
                song_info['song']
            ))
            print(f"   {i}. {song_info['artist']} - {song_info['song']}")
        print("-" * 60)
        print(f"🎶 {len(self.song_queue)} chansons prêtes à être jouées\n")
    
    def add_participant(self, user_id):
        if user_id not in self.participants:
            self.participants[user_id] = {"score":0,"songs_sung":0,"donations":0.0,"votes":0,"status":"waiting"}
            self.command_stats["join"] += 1
            return True
        return False
    
    def add_song_to_queue(self, user_id, artist, song):
        if len(self.song_queue) < MAX_SONGS_IN_QUEUE:
            self.song_queue.append((user_id, artist, song))
            self.command_stats["song"] += 1
            return True
        return False
    
    def next_song(self):
        if self.song_queue:
            self.current_performer, artist, song = self.song_queue.popleft()
            self.current_song = f"{artist}:{song}"
            self.phase_start_time = time.time()
            return self.current_performer, artist, song
        return None, None, None
    
    def calculate_score(self, user_id):
        if user_id not in self.participants:
            return 0
        
        p = self.participants[user_id]
        score = (
            p["donations"] * 0.5 +
            p["votes"] * 0.3 +
            p["songs_sung"] * 0.2
        )
        p["score"] = score
        return score
    
    def get_leaderboard(self):
        scores = [(uid, self.calculate_score(uid)) for uid in self.participants]
        return sorted(scores, key=lambda x: x[1], reverse=True)
    
    def vote_for(self, voter_id, voted_user_id):
        if voted_user_id in self.participants:
            if voter_id in self.votes:
                old_vote = self.votes[voter_id]
                if old_vote in self.participants:
                    self.participants[old_vote]["votes"] -= 1
            
            self.votes[voter_id] = voted_user_id
            self.participants[voted_user_id]["votes"] += 1
            self.command_stats["vote"] += 1
            return True
        return False

# ==================== GESTIONNAIRE DE NOTIFICATIONS ====================
class NotificationManager:
    def __init__(self):
        self.notifications = deque(maxlen=20)
        self.listeners = []
    
    def add(self, message, type="info", user=None, action=None):
        notification = {
            "message": message,
            "type": type,
            "user": user,
            "action": action,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        self.notifications.append(notification)
        self._notify_listeners(notification)
    
    def _notify_listeners(self, notification):
        for listener in self.listeners:
            try:
                listener(notification)
            except:
                pass
    
    def get_recent(self, count=10):
        return list(self.notifications)[-count:]

# ==================== GESTIONNAIRE D'AVATARS ====================
class AvatarManager:
    def __init__(self):
        self.cache = {}
        self.default_path = os.path.join(IMAGES_FOLDER, f"{DEFAULT_USER}_profil_rond.png")
        self._create_default_avatar()
    
    def _create_default_avatar(self):
        if not os.path.exists(self.default_path):
            os.makedirs(IMAGES_FOLDER, exist_ok=True)
            img = Image.new("RGB", (100, 100), color=(100, 100, 100))
            draw = ImageDraw.Draw(img)
            draw.ellipse([10, 10, 90, 90], fill=(150, 150, 150))
            img.save(self.default_path)
    
    def get_avatar(self, user_id):
        if user_id in self.cache:
            return self.cache[user_id]
        
        img_path = os.path.join(IMAGES_FOLDER, f"{user_id}_profil_rond.png")
        
        if not os.path.exists(img_path):
            try:
                self._download_tiktok_avatar(user_id)
            except Exception as e:
                print(f"[ERREUR Avatar] @{user_id}: {e}")
                img_path = self.default_path
        
        if os.path.exists(img_path):
            self.cache[user_id] = img_path
            return img_path
        
        return self.default_path
    
    def _download_tiktok_avatar(self, user_id):
        size = (100, 100)
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")

        driver = webdriver.Chrome(options=options)
        driver.get(f"https://www.tiktok.com/@{user_id}")
        
        soup = BeautifulSoup(driver.page_source, "html.parser")
        driver.quit()

        img_tag = soup.find("img")
        if img_tag and "src" in img_tag.attrs:
            img_url = img_tag["src"]
            response = requests.get(img_url)
            img_data = BytesIO(response.content)
            image = Image.open(img_data).convert("RGBA").resize(size)

            masque = Image.new("L", size, 0)
            draw = ImageDraw.Draw(masque)
            draw.ellipse((0, 0, size[0], size[1]), fill=255)
            image.putalpha(masque)

            path = os.path.join(IMAGES_FOLDER, f"{user_id}_profil_rond.png")
            image.save(path, format="png")
        else:
            raise Exception("Avatar TikTok introuvable")

# ======================= DOWNLOAD CLIP =====================
def download_video_sync(artist, song, folder, user_id):
    try:
        ensure_folders()
        key = make_song_key(artist, song, user_id)
        cached = get_cached_song(artist, song, user_id)
        
        if cached:
            print(f"♻️ Utilisation cache pour {artist} - {song}")
            return cached

        search_query = f"{artist} {song} official video"

        class MyLogger:
            def debug(self, msg): pass
            def warning(self, msg): pass
            def error(self, msg): print(f"❌ YT-DLP Error: {msg}")

        def my_hook(d):
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', 'N/A')
                speed = d.get('_speed_str', 'N/A')
                print(f"📥 Téléchargement: {percent} à {speed}", end='\r')
            elif d['status'] == 'finished':
                print(f"\n✅ Téléchargement terminé")

        safe_filename = f"{user_id}_{artist}_{song}".replace("/", "-").replace("\\", "-").replace(":", "-")
        output_path = os.path.join(folder, f"{safe_filename}.%(ext)s")

        ydl_opts = {
            'outtmpl': output_path,
            'format': 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]',
            'merge_output_format': 'mp4',
            'logger': MyLogger(),
            'progress_hooks': [my_hook],
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch1',
            'noplaylist': True
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"ytsearch1:{search_query}"])

        video_path = os.path.join(folder, f"{safe_filename}.mp4")
        if os.path.exists(video_path):
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            if file_size_mb > MAX_VIDEO_SIZE_MB:
                print(f"⚠️ Vidéo trop volumineuse: {file_size_mb:.2f}MB")
                os.remove(video_path)
                return None

            print(f"✅ Vidéo sauvegardée: {video_path} ({file_size_mb:.2f}MB)")
            save_to_cache(artist, song, user_id, video_path)
            return video_path

        return None
    except Exception as e:
        print(f"❌ Erreur téléchargement: {e}")
        return None

# ==================== LECTEUR VIDÉO ====================
class VideoPlayer:
    def __init__(self):
        self.window = None
        self.is_playing = False
        self.current_video = None
        self.process = None
    
    def play(self, video_path, title="Karaoké"):
        """Joue une vidéo dans une fenêtre séparée avec le lecteur système"""
        if not os.path.exists(video_path):
            print(f"❌ Fichier introuvable: {video_path}")
            return False
        
        try:
            # Arrêter la vidéo précédente si en cours
            if self.is_playing:
                self.stop()
            
            self.current_video = video_path
            self.is_playing = True
            
            # Lancer dans un thread séparé
            thread = threading.Thread(target=self._play_video, args=(video_path, title), daemon=True)
            thread.start()
            return True
        except Exception as e:
            print(f"❌ Erreur lecture vidéo: {e}")
            return False
    
    def _play_video(self, video_path, title):
        """Thread interne pour jouer la vidéo avec le lecteur système"""
        try:
            import subprocess
            import platform
            
            abs_path = os.path.abspath(video_path)
            
            # Détection du système d'exploitation
            system = platform.system()
            
            if system == "Windows":
                # Windows: utiliser le lecteur par défaut
                os.startfile(abs_path)
                print(f"▶️ Lecture avec lecteur Windows: {abs_path}")
            
            elif system == "Darwin":  # macOS
                subprocess.Popen(["open", abs_path])
                print(f"▶️ Lecture avec lecteur macOS: {abs_path}")
            
            elif system == "Linux":
                # Linux: essayer différents lecteurs
                players = ["xdg-open", "vlc", "mpv", "ffplay"]
                for player in players:
                    try:
                        subprocess.Popen([player, abs_path])
                        print(f"▶️ Lecture avec {player}: {abs_path}")
                        break
                    except FileNotFoundError:
                        continue
            
            self.is_playing = True
            
        except Exception as e:
            print(f"❌ Erreur lecture vidéo: {e}")
            self.is_playing = False
    
    def stop(self):
        """Arrête la lecture (note: difficile de contrôler le lecteur externe)"""
        self.is_playing = False
        if self.process:
            try:
                self.process.terminate()
            except:
                pass

# ==================== CLIENT TIKTOK LIVE ====================
class KaraokeTikTokClient:
    def __init__(self, username, session, notifications):
        self.client = TikTokLiveClient(unique_id=username)
        self.session = session
        self.notifications = notifications
        self.donations_data = load_json(JSON_FILE, {})
        
        self.client.add_listener(ConnectEvent, self.on_connect)
        self.client.add_listener(GiftEvent, self.on_gift)
        self.client.add_listener(CommentEvent, self.on_comment)
    
    async def on_connect(self, event: ConnectEvent):
        print(f"✅ Connecté à @{event.unique_id} (Room ID: {self.client.room_id})")
        self.notifications.add(
            f"🔴 Live démarré ! Room {self.client.room_id}",
            "success",
            action="CONNECT"
        )
        self.notifications.add(
            "📋 COMMANDES: !join | !song artiste:titre | !vote @user | !skip (VIP)",
            "info",
            action="HELP"
        )
    
    async def on_gift(self, event: GiftEvent):
        user_id = event.user.unique_id
        gift_name = event.gift.name
        quantity = event.repeat_count if (event.gift.streakable and not event.streaking) else 1
        
        coins = TIKTOK_GIFTS.get(gift_name, 0)
        if coins == 0:
            return
        
        amount = coins * quantity * 0.001
        
        if user_id not in self.donations_data:
            self.donations_data[user_id] = {"donate_emojie": {}, "taux": 0.0}
        
        if gift_name in self.donations_data[user_id]["donate_emojie"]:
            self.donations_data[user_id]["donate_emojie"][gift_name] += quantity
        else:
            self.donations_data[user_id]["donate_emojie"][gift_name] = quantity
        
        self.donations_data[user_id]["taux"] += amount
        save_json(JSON_FILE, self.donations_data)
        
        if user_id in self.session.participants:
            self.session.participants[user_id]["donations"] += amount
        
        self.notifications.add(
            f"💎 @{user_id} envoie {quantity}x {gift_name} (+{amount:.2f}€)",
            "gift",
            user=user_id,
            action="GIFT"
        )
        print(f"💎 @{user_id} sent {quantity}x \"{gift_name}\" (+{amount:.2f}€)")
    
    async def on_comment(self, event: CommentEvent):
        user_id = event.user.unique_id
        comment = event.comment.strip()
        
        # Commande !join
        if comment.lower() == "!join":
            total_donations = self.donations_data.get(user_id, {}).get("taux", 0.0)
            is_whitelisted = user_id in WHITELIST_USERS
            has_enough_donations = total_donations >= MIN_DONATION_TO_PLAY
            
            if is_whitelisted or has_enough_donations:
                if self.session.add_participant(user_id):
                    status = "VIP 👑" if is_whitelisted else f"{total_donations:.2f}€"
                    self.notifications.add(
                        f"🎤 @{user_id} rejoint le concours ! ({status})",
                        "join",
                        user=user_id,
                        action="JOIN"
                    )
                    print(f"🎤 @{user_id} a rejoint le concours")
                else:
                    self.notifications.add(
                        f"ℹ️ @{user_id} est déjà inscrit au concours",
                        "info",
                        user=user_id,
                        action="JOIN_DUPLICATE"
                    )
            else:
                needed = MIN_DONATION_TO_PLAY - total_donations
                self.notifications.add(
                    f"❌ @{user_id} doit donner {needed:.2f}€ de plus pour participer",
                    "error",
                    user=user_id,
                    action="JOIN_DENIED"
                )
        
        # Commande !song artiste:titre
        elif comment.lower().startswith("!song "):
            if user_id not in self.session.participants:
                self.notifications.add(
                    f"❌ @{user_id} doit d'abord rejoindre avec !join",
                    "error",
                    user=user_id,
                    action="SONG_DENIED"
                )
                return
            
            try:
                song_info = comment[6:].strip()
                if ":" not in song_info:
                    raise ValueError("Format invalide")
                
                artist, song = song_info.split(":", 1)
                artist, song = artist.strip(), song.strip()
                
                if self.session.add_song_to_queue(user_id, artist, song):
                    self.notifications.add(
                        f"🎵 @{user_id} ajoute: {artist} - {song}",
                        "song",
                        user=user_id,
                        action="SONG_ADDED"
                    )
                    print(f"🎵 @{user_id} -> Chanson: {artist} - {song}")
                    
                    # ❌ DÉSACTIVÉ: Pas de téléchargement automatique
                    # Les utilisateurs ne peuvent ajouter QUE des chansons déjà dans temp/
                    self.notifications.add(
                        f"ℹ️ La chanson sera jouée si elle existe dans temp/",
                        "info",
                        action="SONG_CHECK"
                    )
                else:
                    self.notifications.add(
                        f"❌ Queue pleine ! Max {MAX_SONGS_IN_QUEUE} chansons",
                        "error",
                        user=user_id,
                        action="SONG_QUEUE_FULL"
                    )
            
            except Exception as e:
                self.notifications.add(
                    f"❌ @{user_id} format incorrect. Utilise: !song artiste:titre",
                    "error",
                    user=user_id,
                    action="SONG_FORMAT_ERROR"
                )
        
        # Commande !vote @username
        elif comment.lower().startswith("!vote "):
            try:
                voted_user = comment[6:].strip().lstrip("@")
                if self.session.vote_for(user_id, voted_user):
                    self.notifications.add(
                        f"✅ @{user_id} vote pour @{voted_user}",
                        "vote",
                        user=user_id,
                        action="VOTE"
                    )
                    print(f"✅ @{user_id} vote pour @{voted_user}")
                else:
                    self.notifications.add(
                        f"❌ @{voted_user} n'est pas participant",
                        "error",
                        user=user_id,
                        action="VOTE_INVALID"
                    )
            except:
                self.notifications.add(
                    f"❌ @{user_id} format incorrect. Utilise: !vote @username",
                    "error",
                    user=user_id,
                    action="VOTE_FORMAT_ERROR"
                )
        
        # Commande !skip (VIP only)
        elif comment.lower() == "!skip":
            total_donations = self.donations_data.get(user_id, {}).get("taux", 0.0)
            if total_donations >= 2 or user_id in WHITELIST_USERS:
                if self.session.current_performer:
                    self.notifications.add(
                        f"⏭️ @{user_id} (VIP) skip la chanson",
                        "skip",
                        user=user_id,
                        action="SKIP"
                    )
                    self.session.command_stats["skip"] += 1
                    self.session.next_song()
            else:
                self.notifications.add(
                    f"❌ @{user_id} : Skip réservé aux VIP (2€+)",
                    "error",
                    user=user_id,
                    action="SKIP_DENIED"
                )
    
    async def start(self):
        await self.client.start()

# ==================== INTERFACE TKINTER ====================
class KaraokeGUI:
    def __init__(self, session, notifications, avatar_manager):
        self.session = session
        self.notifications = notifications
        self.avatar_manager = avatar_manager
        self.images_cache = {}

        self.app = customtkinter.CTk()
        self.app.geometry("550x800")
        self.app.title("🎤 TikTok Karaoké Live")
        self.app.resizable(False, False)

        # HEADER
        self.header_frame = customtkinter.CTkFrame(self.app, height=100)
        self.header_frame.pack(fill="x", padx=10, pady=10)
        
        self.timer_label = customtkinter.CTkLabel(
            self.header_frame,
            text="00:00",
            font=("Helvetica", 40, "bold")
        )
        self.timer_label.pack(pady=5)
        
        self.phase_label = customtkinter.CTkLabel(
            self.header_frame,
            text="LOBBY",
            font=("Helvetica", 20),
            text_color="#00FF00"
        )
        self.phase_label.pack()

        # COMMANDS
        self.commands_frame = customtkinter.CTkFrame(self.app, height=80)
        self.commands_frame.pack(fill="x", padx=10, pady=5)
        
        commands_title = customtkinter.CTkLabel(
            self.commands_frame,
            text="📋 COMMANDES",
            font=("Helvetica", 16, "bold")
        )
        commands_title.pack(pady=2)
        
        commands_text = customtkinter.CTkLabel(
            self.commands_frame,
            text="!join | !song artiste:titre | !vote @user | !skip",
            font=("Courier", 12),
            text_color="#AAAAAA"
        )
        commands_text.pack(pady=2)
        
        self.stats_label = customtkinter.CTkLabel(
            self.commands_frame,
            text="Stats: 0 joins | 0 songs | 0 votes | 0 skips",
            font=("Courier", 10),
            text_color="#888888"
        )
        self.stats_label.pack(pady=2)

        # LEADERBOARD
        self.leaderboard_frame = customtkinter.CTkFrame(self.app, height=250)
        self.leaderboard_frame.pack(fill="x", padx=10, pady=10)
        
        self.leaderboard_title = customtkinter.CTkLabel(
            self.leaderboard_frame,
            text="🏆 CLASSEMENT",
            font=("Helvetica", 18, "bold")
        )
        self.leaderboard_title.pack(pady=5)
        
        self.podium_frame = customtkinter.CTkFrame(self.leaderboard_frame)
        self.podium_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.top1_frame = self._create_podium_slot(self.podium_frame, "🥇", 0.5, 0.3)
        self.top2_frame = self._create_podium_slot(self.podium_frame, "🥈", 0.25, 0.6)
        self.top3_frame = self._create_podium_slot(self.podium_frame, "🥉", 0.75, 0.6)

        # CURRENT SONG
        self.current_frame = customtkinter.CTkFrame(self.app, height=80)
        self.current_frame.pack(fill="x", padx=10, pady=10)
        
        self.current_label = customtkinter.CTkLabel(
            self.current_frame,
            text="🎤 En attente...",
            font=("Helvetica", 14)
        )
        self.current_label.pack(pady=5)
        
        self.queue_label = customtkinter.CTkLabel(
            self.current_frame,
            text="Queue: 0 chansons",
            font=("Helvetica", 12),
            text_color="#888888"
        )
        self.queue_label.pack(pady=5)

        # NOTIFICATIONS
        self.notif_frame = customtkinter.CTkFrame(self.app, height=200)
        self.notif_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.notif_title = customtkinter.CTkLabel(
            self.notif_frame,
            text="📊 ACTIVITÉ EN DIRECT",
            font=("Helvetica", 14, "bold")
        )
        self.notif_title.pack(pady=5)
        
        self.notif_text = customtkinter.CTkTextbox(
            self.notif_frame,
            height=150,
            font=("Courier", 9),
            wrap="word"
        )
        self.notif_text.pack(fill="both", expand=True, padx=5, pady=5)

        self.notifications.listeners.append(self._on_notification)

    def _create_podium_slot(self, parent, medal, relx, rely):
        frame = customtkinter.CTkFrame(parent, width=120, height=150)
        frame.place(relx=relx, rely=rely, anchor="center")
        
        medal_label = customtkinter.CTkLabel(frame, text=medal, font=("Helvetica", 30))
        medal_label.pack(pady=5)
        
        avatar_label = customtkinter.CTkLabel(frame, text="")
        avatar_label.pack()
        
        name_label = customtkinter.CTkLabel(frame, text="---", font=("Helvetica", 12))
        name_label.pack()
        
        score_label = customtkinter.CTkLabel(frame, text="0.00€", font=("Helvetica", 10))
        score_label.pack()
        
        return {"frame": frame, "avatar": avatar_label, "name": name_label, "score": score_label}

    def _on_notification(self, notification):
        timestamp = notification.get("timestamp", datetime.now().strftime("%H:%M:%S"))
        msg = notification.get("message", "")
        action = notification.get("action", "")
        formatted = f"[{timestamp}] [{action}] {msg}\n" if action else f"[{timestamp}] {msg}\n"
        
        self.notif_text.insert("end", formatted)
        try:
            self.notif_text.see("end")
        except:
            pass

    def update_display(self):
        phase = self.session.phase
        elapsed = time.time() - self.session.phase_start_time
        
        if phase == GamePhase.LOBBY:
            remaining = max(0, LOBBY_DURATION - elapsed)
        elif phase == GamePhase.PLAYING:
            remaining = max(0, SONG_MAX_DURATION - elapsed)
        elif phase == GamePhase.VOTING:
            remaining = max(0, VOTING_DURATION - elapsed)
        else:
            remaining = 0
        
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        self.timer_label.configure(text=f"{mins:02d}:{secs:02d}")
        
        phase_colors = {
            GamePhase.LOBBY: "#00FF00",
            GamePhase.PLAYING: "#FFA500",
            GamePhase.VOTING: "#FF00FF",
            GamePhase.ENDED: "#FF0000"
        }
        self.phase_label.configure(
            text=phase.value,
            text_color=phase_colors.get(phase, "#FFFFFF")
        )
        
        stats = self.session.command_stats
        self.stats_label.configure(
            text=f"Stats: {stats['join']} joins | {stats['song']} songs | {stats['vote']} votes | {stats['skip']} skips"
        )
        
        leaderboard = self.session.get_leaderboard()
        
        for i, slot in enumerate([self.top1_frame, self.top2_frame, self.top3_frame]):
            if i < len(leaderboard):
                user_id, score = leaderboard[i]
                avatar_path = self.avatar_manager.get_avatar(user_id)
                
                if avatar_path not in self.images_cache:
                    img = customtkinter.CTkImage(
                        Image.open(avatar_path),
                        size=(80, 80)
                    )
                    self.images_cache[avatar_path] = img
                
                slot["avatar"].configure(image=self.images_cache[avatar_path])
                slot["name"].configure(text=user_id[:10])
                slot["score"].configure(text=f"{score:.2f}€")
            else:
                slot["name"].configure(text="---")
                slot["score"].configure(text="0.00€")
        
        if self.session.current_performer:
            self.current_label.configure(
                text=f"🎤 @{self.session.current_performer} - {self.session.current_song}"
            )
        else:
            self.current_label.configure(text="🎤 En attente de chansons...")
        
        self.queue_label.configure(text=f"Queue: {len(self.session.song_queue)} chansons")
        
        self.app.after(1000, self.update_display)
    
    def run(self):
        self.update_display()
        self.app.mainloop()

# ==================== GESTIONNAIRE PRINCIPAL ====================
class GameManager:
    def __init__(self, session, notifications, video_player):
        self.session = session
        self.notifications = notifications
        self.video_player = video_player
        self.running = True
    
    async def run(self):
        while self.running:
            phase = self.session.phase
            elapsed = time.time() - self.session.phase_start_time
            
            if phase == GamePhase.LOBBY:
                if elapsed >= LOBBY_DURATION:
                    await self._start_game()
            elif phase == GamePhase.PLAYING:
                if elapsed >= SONG_MAX_DURATION or not self.session.current_performer:
                    await self._next_song()
            elif phase == GamePhase.VOTING:
                if elapsed >= VOTING_DURATION:
                    await self._end_game()
            
            await asyncio.sleep(1)
    
    async def _start_game(self):
        if len(self.session.song_queue) < 1:
            self.notifications.add(
                "❌ Il faut au moins 1 chanson avant de commencer !",
                "error",
                action="START_DENIED"
            )
            self.session.phase_start_time = time.time()
            return
        
        self.session.phase = GamePhase.PLAYING
        self.session.phase_start_time = time.time()
        self.notifications.add("🎮 LE JEU COMMENCE !", "success", action="START")
        await self._next_song()
    
    async def _next_song(self):
        if self.session.song_queue:
            user, artist, song = self.session.next_song()
            
            if user in self.session.participants:
                self.session.participants[user]["songs_sung"] += 1
            
            self.notifications.add(
                f"🎵 @{user} chante: {artist} - {song}",
                "song",
                user=user,
                action="NEXT_SONG"
            )

            # Chercher la vidéo en cache
            cached = get_cached_song(artist, song, user)
            
            if cached:
                # Lancer la vidéo dans une fenêtre séparée
                title = f"🎤 {artist} - {song} (par @{user})"
                if self.video_player.play(cached, title):
                    print(f"▶️ Lecture: {cached}")
                else:
                    self.notifications.add(
                        f"❌ Impossible de lire la vidéo pour @{user}",
                        "error",
                        user=user,
                        action="PLAY_ERROR"
                    )
            else:
                # Téléchargement si non présent
                self.notifications.add(
                    f"📥 Téléchargement de {artist} - {song}...",
                    "info",
                    action="DOWNLOAD"
                )
                
                loop = asyncio.get_event_loop()
                path = await loop.run_in_executor(
                    None,
                    download_video_sync,
                    artist,
                    song,
                    TEMP_FOLDER,
                    user
                )
                
                if path:
                    title = f"🎤 {artist} - {song} (par @{user})"
                    self.video_player.play(path, title)
                else:
                    self.notifications.add(
                        f"❌ Vidéo introuvable pour {artist} - {song}",
                        "error",
                        action="PLAY_MISSING"
                    )
        else:
            self.session.phase = GamePhase.VOTING
            self.session.phase_start_time = time.time()
            self.notifications.add("🗳️ PHASE DE VOTE FINALE !", "vote", action="VOTING")
    
    async def _end_game(self):
        self.session.phase = GamePhase.ENDED
        self.notifications.add("✅ FIN DU JEU", "success", action="END")
        self.running = False
        
        leaderboard = self.session.get_leaderboard()
        if leaderboard:
            winner_id, winner_score = leaderboard[0]
            self.notifications.add(
                f"🏆 GAGNANT: @{winner_id} avec {winner_score:.2f}€ !",
                "trophy",
                user=winner_id,
                action="WINNER"
            )
            print(f"🏆 GAGNANT: @{winner_id} avec {winner_score:.2f}€ !")

# ==================== MAIN ====================
async def main():
    print("=" * 60)
    print("🎤 TikTok Karaoké Live - Lecture depuis dossier temp/")
    print("=" * 60)
    ensure_folders()
    
    # 🔄 Reconstruire le cache à partir des fichiers existants UNIQUEMENT
    existing_songs = rebuild_cache_from_temp()
    
    # Créer la session (charge automatiquement les chansons du dossier temp/)
    session = KaraokeSession(use_existing_songs=True)
    notifications = NotificationManager()
    avatar_manager = AvatarManager()
    video_player = VideoPlayer()
    
    # ❌ PAS de téléchargement - on joue UNIQUEMENT ce qui est dans temp/
    if not existing_songs:
        print("⚠️ ATTENTION: Aucune vidéo trouvée dans live/temp/")
        print("Le jeu ne démarrera pas sans chansons.\n")
        print("📋 Instructions:")
        print("1. Place tes fichiers .mp4 dans: live/temp/")
        print("2. Format du nom: system_Artist Name_Song Title.mp4")
        print("3. Exemple: system_Bruno Mars_Uptown Funk.mp4\n")
    else:
        print("✅ Prêt à lancer le karaoké avec les vidéos locales\n")
    
    # Client TikTok
    tiktok_client = KaraokeTikTokClient(
        TIKTOK_USERNAME,
        session,
        notifications
    )
    
    # Game Manager
    game_manager = GameManager(session, notifications, video_player)
    
    # GUI dans un thread séparé
    def run_gui():
        gui = KaraokeGUI(session, notifications, avatar_manager)
        gui.run()
    
    gui_thread = threading.Thread(target=run_gui, daemon=True)
    gui_thread.start()
    
    # Démarrage TikTok Live
    print("🔴 Connexion au live TikTok...")
    tiktok_task = asyncio.create_task(tiktok_client.start())
    
    # Attendre un peu pour la connexion
    await asyncio.sleep(3)
    
    # Démarrage Game Manager
    print("🎮 Démarrage du gestionnaire de jeu...")
    await game_manager.run()
    
    print("✅ Session terminée !")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️ Arrêt manuel")
    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # ⚠️ Utilise cleanup_temp_files_disabled() pour GARDER les vidéos
        cleanup_temp_files_disabled()
        print("🧹 Session terminée - Vidéos conservées pour la prochaine fois")