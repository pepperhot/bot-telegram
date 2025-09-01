import requests
from bs4 import BeautifulSoup
import time
from telegram import Bot

TOKEN = "8415730500:AAH2JYaCIjLqn_uZnU-hDoYzAou6uECpyvw"
CHAT_ID = "sniffeurVinted_bot"
bot = Bot(token=TOKEN)

articles = {
    "souris_razer": "https://www.vinted.fr/items/6734978697-souris-razer-viper-mini-signature?referrer=catalog",
    "gants_vr": "https://www.vinted.fr/items/6734925887-gants-haptiques-bhaptics-vr?referrer=catalog",
    "mug_intelligent": "https://www.vinted.fr/items/6734954260-mug-intelligent-vsitoo-s6-plus?referrer=catalog",
    "tapis_souris": "https://www.vinted.fr/items/6734960946-tapis-de-souris-razer-strider-chroma?referrer=catalog",
    "grille_pain": "https://www.vinted.fr/items/6734983840-grille-pain-intelligent?referrer=catalog",
    "console_portable": "https://www.vinted.fr/items/6735018459-console-portable-anbernic?referrer=catalog"
}

def verifier_article(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return False
        
        soup = BeautifulSoup(response.text, 'html.parser')
        titre = soup.find('h1')
        if titre:
            prix = soup.find('span', class_='Text-module__root___2Kc9E Text-module__bold___1oCge')
            prix_text = prix.text.strip() if prix else None
            if prix_text is None:
                return False
            return {"titre": titre.text.strip(), "prix": prix_text}
        return False
    except:
        return False

articles_en_ligne = set()

while True:
    for nom, url in articles.items():
        resultat = verifier_article(url)
        if resultat and nom not in articles_en_ligne:
            articles_en_ligne.add(nom)
            message = f"Article en ligne !\nNom: {resultat['titre']}\nPrix: {resultat['prix']}\nLien: {url}"
            bot.send_message(chat_id=CHAT_ID, text=message)
            print(message)
        elif not resultat:
            print(f"{nom} pas encore en ligne.")
    time.sleep(30)
