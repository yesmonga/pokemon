import requests
import time
import os
import threading
from flask import Flask
from collections import defaultdict
import re

# Variables d’environnement
USER_TOKEN = os.environ.get("USER_TOKEN")
SOURCE_CHANNEL_IDS = os.environ.get("SOURCE_CHANNEL_IDS").split(",")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")

# Dernier message traité par channel
last_message_ids = {channel_id: None for channel_id in SOURCE_CHANNEL_IDS}

# Tracking des checkouts par produit
product_checkouts = defaultdict(list)

# Headers API Discord
headers = {
    "Authorization": USER_TOKEN,
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json"
}

def parse_checkout(msg):
    content = msg.get("content", "")
    if not content:
        return None
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    if not lines:
        return None
    
    # Headers ou noms users à ignorer pour le titre
    ignore_patterns = [
        r"^\w+.*à \d+:\d+$",  # Nom user + timestamp
        r"^Successful Checkout$",
        r"^PanAIO User Checkout$",
        r"^Checkout Ready.*$",
        r"^APP — \d+:\d+$",
        r"^LE KLAN.*$"
    ]
    
    title = None
    for line in lines:
        if not any(re.match(pattern, line) for pattern in ignore_patterns):
            if len(line) > 10 and not line.startswith(("Store:", "Site:", "Price:", "Mode:", "Payment")):  # Ligne potentiellement titre produit
                title = line
                break
    
    if not title:
        title = lines[0] if lines else ""
    
    url = None
    urls = re.findall(r'https?://[^\s<>"]+', content)
    if urls:
        url = urls[0]  # Prendre la première URL trouvée
    else:
        # Fallback pour 'Query'
        for line in lines:
            if line.startswith("Query"):
                parts = line.split(" ", 1)
                if len(parts) > 1:
                    url = parts[1]
                    break
    
    has_quicktask = False
    quicktask_patterns = [
        "Click to start quick task",
        "Start Quicktask",
        "Quicktask",
        "Start quicktask",
        "Click Here"
    ]
    for pattern in quicktask_patterns:
        if pattern in content:
            has_quicktask = True
            break
    
    # Valide si titre significatif
    if len(title.strip()) > 5:
        return (title.lower().strip(), url, has_quicktask)
    return None

def fetch_messages(channel_id):
    global last_message_ids, product_checkouts
    while True:
        try:
            url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=5"
            response = requests.get(url, headers=headers)

            if response.status_code == 200:
                messages = response.json()
                messages.reverse()

                for msg in messages:
                    if last_message_ids[channel_id] is None or msg["id"] > last_message_ids[channel_id]:
                        parsed = parse_checkout(msg)
                        if parsed:
                            title, url, has_quicktask = parsed
                            now = time.time()
                            product_checkouts[title].append((now, msg["id"], url, has_quicktask))
                            # Nettoyer les entrées anciennes
                            product_checkouts[title] = [entry for entry in product_checkouts[title] if now - entry[0] <= 20]
                            if len(product_checkouts[title]) >= 5:
                                send_popular_notification(title, product_checkouts[title].copy())
                                # Vider pour éviter spam immédiat
                                product_checkouts[title] = []
                        last_message_ids[channel_id] = msg["id"]
            else:
                print(f"[{channel_id}] ❌ Erreur {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[{channel_id}] ⚠️ Erreur dans fetch_messages: {e}")
        time.sleep(2)

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

def send_popular_notification(title, checkouts):
    unique_urls = list(set(entry[2] for entry in checkouts if entry[2]))
    has_qt = any(entry[3] for entry in checkouts)
    content = f"🚀 Produit populaire détecté : {title}\nNombre de checkouts dans les 20 dernières secondes : {len(checkouts)}"
    if has_qt:
        content += "\n🔧 Quicktask disponible"
    
    embeds = []
    if unique_urls:
        embed = {
            "title": "Liens des produits",
            "color": int("9c73cb", 16),
            "fields": [{"name": "URLs", "value": "\n".join(unique_urls[:5]), "inline": False}]
        }
        embeds.append(embed)
    elif has_qt:
        embed = {
            "title": "Détails Quicktask",
            "color": int("9c73cb", 16),
            "description": "Quicktask disponible pour ce produit populaire",
            "fields": []
        }
        embeds.append(embed)
    
    payload = {"content": content, "embeds": embeds}
    response = requests.post(WEBHOOK_URL, json=payload)
    if response.status_code == 204:
        print(f"✅ Notification populaire envoyée pour {title}")
    else:
        print(f"❌ Erreur envoi notification : {response.status_code}")

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
