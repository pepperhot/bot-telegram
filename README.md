# 🎤 Telegram Lyrics Bot

Ce bot Telegram permet de générer automatiquement des visuels TikTok-friendly à partir des paroles d'une chanson. L'utilisateur envoie un message au format `artiste:titre`, sélectionne un bloc de paroles et une couleur, et reçoit deux images format portrait contenant :

- Une moitié de la pochette de l'album
- Le texte sélectionné, stylisé avec la couleur choisie

## 🚀 Fonctionnalités

- 🎶 Récupération automatique des paroles depuis AZLyrics
- 🖼 Téléchargement de la pochette d’album via Google Images
- 🧠 Sélection de blocs de paroles via boutons interactifs
- 🎨 Choix de la couleur de fond parmi 4 options
- 🖌 Génération d’images prêtes à être utilisées sur TikTok

## 🛠 Stack utilisée

- `python-telegram-bot` (Telegram API)
- `Pillow` pour la génération d'images
- `BeautifulSoup4` pour le scraping de paroles et images
- `dotenv` pour la gestion des variables sensibles

## ▶️ Lancer le bot

Assure-toi d'avoir Python 3.9+ installé.

1. Clone le repo :
   ```bash
   git clone https://github.com/ton-utilisateur/bot-telegram.git
   cd bot-telegram
