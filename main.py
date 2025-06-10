import requests
import time
import os
import threading
from flask import Flask

# Variables d’environnement
USER_TOKEN = os.environ.get("USER_TOKEN")
SOURCE_CHANNEL_IDS = os.environ.get("SOURCE_CHANNEL_IDS").split(",")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
BLOCKED_KEYWORDS = [
    word.strip().lower()
    for word in os.environ.get("BLOCKED_KEYWORDS", "").split(",")
    if word.strip()
]

# Dernier message traité par channel
last_message_ids = {channel_id: None for channel_id in SOURCE_CHANNEL_IDS}

# Headers API Discord
headers = {
    "Authorization": USER_TOKEN,
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json"
}

def fetch_messages(channel_id):
    global last_message_ids
    while True:
        try:
            url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=5"
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                messages = response.json()
                messages.reverse()

                for msg in messages:
                    if last_message_ids[channel_id] is None or msg["id"] > last_message_ids[channel_id]:
                        if not is_blocked(msg):
                            send_as_yora_webhook(msg)
                        else:
                            print(f"[{channel_id}] 🔕 Message bloqué.")
                        last_message_ids[channel_id] = msg["id"]
            else:
                print(f"[{channel_id}] ❌ Erreur {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[{channel_id}] ⚠️ Erreur dans fetch_messages: {e}")
        time.sleep(1)

def is_blocked(msg):
    content = msg.get("content", "").lower()

    # Vérifie le texte brut
    for keyword in BLOCKED_KEYWORDS:
        if keyword in content:
            print(f"🔕 Bloqué dans content : {keyword}")
            return True

    # Vérifie les embeds
    for embed in msg.get("embeds", []):
        fields_to_check = [
            embed.get("title", ""),
            embed.get("description", ""),
            embed.get("footer", {}).get("text", "")
        ]

        if "fields" in embed:
            fields_to_check += [f.get("name", "") + " " + f.get("value", "") for f in embed["fields"]]

        for field in fields_to_check:
            field_lower = field.lower()
            for keyword in BLOCKED_KEYWORDS:
                if keyword in field_lower:
                    print(f"🔕 Bloqué dans embed : {keyword}")
                    return True

    return False

def send_as_yora_webhook(msg):
    content = msg.get("content", "")

    payload = {
        "content": content
    }

    embeds = msg.get("embeds", [])
    if embeds:
        # Couleur personnalisée violette #9c73cb
        purple_int = int("9c73cb", 16)
        for embed in embeds:
            embed["color"] = purple_int
        payload["embeds"] = embeds

    # Ajout des fichiers joints s’il y en a
    attachments = msg.get("attachments", [])
    for att in attachments:
        payload["content"] += f"\n📎 {att['url']}"

    requests.post(WEBHOOK_URL, json=payload)

# Serveur Railway / UptimeRobot
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot actif ✅", 200

if __name__ == "__main__":
    for channel_id in SOURCE_CHANNEL_IDS:
        thread = threading.Thread(target=fetch_messages, args=(channel_id,))
        thread.start()

    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
