import requests
import time
import os
import threading
from flask import Flask
from collections import defaultdict
import re

# Variables d’environnement (pour Railway)
USER_TOKEN = os.environ.get("USER_TOKEN")
if not USER_TOKEN:
    print("❌ ERREUR : Var manquante USER_TOKEN")
    exit(1)

SOURCE_CHANNEL_IDS_STR = os.environ.get("SOURCE_CHANNEL_IDS", "")
if not SOURCE_CHANNEL_IDS_STR:
    print("❌ ERREUR : Var manquante SOURCE_CHANNEL_IDS (format: id1,id2,...)")
    exit(1)
SOURCE_CHANNEL_IDS = [cid.strip() for cid in SOURCE_CHANNEL_IDS_STR.split(",") if cid.strip()]

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
if not WEBHOOK_URL:
    print("❌ ERREUR : Var manquante WEBHOOK_URL")
    exit(1)

print(f"[START] Bot prêt pour Railway ! Channels: {len(SOURCE_CHANNEL_IDS)} | Webhook: {WEBHOOK_URL[:50]}...")

# Dernier message traité par channel
last_message_ids = {channel_id: None for channel_id in SOURCE_CHANNEL_IDS}

# Tracking des checkouts par produit (avec msg full pour forward)
product_checkouts = defaultdict(list)

# Headers API Discord
headers = {
    "Authorization": USER_TOKEN,
    "User-Agent": "Mozilla/5.0",
    "Content-Type": "application/json"
}

# Liste bad titles/headers à ignorer
bad_titles = [
    "successful checkout", "panaio user checkout", "checkout ready", "click to start quick task",
    "start quicktask", "quicktask", "remote qt", "image", "app", "le klan", "antares",
    "checked out :success:", "gymshark us", "gymshark eu", "gymshark"
]

def parse_checkout(msg):
    content = msg.get("content", "")
    embeds = msg.get("embeds", [])
    
    if not content and not embeds:
        return None
    
    title = None
    url = None
    has_quicktask = False
    
    lines = []
    if content:
        lines = [line.strip() for line in content.split('\n') if line.strip()]
    
    if embeds:
        embed = embeds[0]
        print(f"[DEBUG EMBED] Fields: {embed.get('fields', [])}")
        if embed.get('title') and len(embed['title']) > 5:
            title = embed['title'].lower().strip()
        else:
            fields = embed.get('fields', [])
            for field in fields:
                value = field['value'].strip()
                if len(value) > 10 and not value.startswith(('Store:', 'Site:', 'Price:', 'Mode:', 'Payment', 'Size:', 'Method:', 'Quantity:', 'Input:', 'Checkout:', 'Release Type:', 'Delay:', 'Checkout Time:', 'Quicktask:', 'Remote QT', 'Click to start quick task', 'Start Quicktask', 'Click Here', 'Mass Link Change:', 'Restock Monitoring:')):
                    title = value.lower().strip()
                    break
            if not title and fields:
                title = fields[0]['value'].lower().strip() if fields[0]['value'].strip() else ""
        
        fields = embed.get('fields', [])
        for field in fields:
            if field['name'].lower() in ['query', 'site', 'url', 'link']:
                parts = field['value'].split(" ", 1)
                if len(parts) > 1:
                    url = parts[1]
                    break
        if not url:
            urls = re.findall(r'https?://[^\s<>"]+', str(embed))
            if urls:
                url = urls[0]
        
        embed_text = str(embed).lower()
        quicktask_patterns = ["click to start quick task", "start quicktask", "quicktask", "start quick task", "click here", "remote qt"]
        for pattern in quicktask_patterns:
            if pattern in embed_text:
                has_quicktask = True
                break
    else:
        ignore_patterns = [
            r"^\w+.*à \d+:\d+$", r"^Successful Checkout$", r"^PanAIO User Checkout$",
            r"^Checkout Ready.*$", r"^APP — \d+:\d+$", r"^LE KLAN.*$", r"^Antarès$",
            r"^Product$", r"^Multi Cart Checkout$", r"^Image$"
        ]
        
        for line in lines:
            if not any(re.match(pattern, line) for pattern in ignore_patterns):
                if len(line) > 10 and not line.startswith(("Store:", "Site:", "Price:", "Mode:", "Payment", "Size:", "Method:", "Quantity:", "Input:", "Checkout:", "Release Type:", "Delay:", "Checkout Time:", "Quicktask:", "Remote QT", "Click to start quick task", "Start Quicktask", "Click Here", "Mass Link Change:", "Restock Monitoring:")):
                    title = line.lower().strip()
                    break
        
        if not title:
            title = lines[0].lower().strip() if lines else ""
        
        urls = re.findall(r'https?://[^\s<>"]+', content)
        if urls:
            url = urls[0]
        else:
            for line in lines:
                if line.startswith("Query"):
                    parts = line.split(" ", 1)
                    if len(parts) > 1:
                        url = parts[1]
                        break
                elif line.startswith("Input:"):
                    parts = line.split(" ", 1)
                    if len(parts) > 1:
                        url = parts[1]
        
        content_lower = content.lower()
        for pattern in quicktask_patterns:
            if pattern in content_lower:
                has_quicktask = True
                break
    
    # Skip bad titles
    if title in bad_titles or any(bad in title for bad in bad_titles):
        return None
    
    # URL valide seulement
    if url and not (url.startswith('http') or re.match(r'^[A-Z0-9-]+$', url) and len(url) > 5):
        url = None
    
    if len(title.strip()) > 5 and title not in bad_titles:
        return (title, url, has_quicktask)
    return None

def send_as_yora_webhook(msg):
    content = msg.get("content", "")
    payload = {
        "content": content
    }
    embeds = msg.get("embeds", [])
    if embeds:
        purple_int = int("9c73cb", 16)
        for embed in embeds:
            embed["color"] = purple_int
        payload["embeds"] = embeds
    attachments = msg.get("attachments", [])
    for att in attachments:
        payload["content"] += f"\n📎 {att['url']}"
    response = requests.post(WEBHOOK_URL, json=payload)
    print(f"[DEBUG] Forward webhook: Status {response.status_code}")

def fetch_messages(channel_id):
    global last_message_ids, product_checkouts
    while True:
        try:
            url = f"https://discord.com/api/v9/channels/{channel_id}/messages?limit=50"
            response = requests.get(url, headers=headers)
            print(f"[DEBUG] Fetch {channel_id}: Status {response.status_code}, {len(response.json() if response.status_code == 200 else [])} messages")
            
            if response.status_code == 200:
                messages = response.json()
                messages.reverse()
                parsed_count = 0
                
                for msg in messages:
                    if last_message_ids[channel_id] is None or msg["id"] > last_message_ids[channel_id]:
                        parsed = parse_checkout(msg)
                        if parsed:
                            title, url, has_quicktask = parsed
                            print(f"[DEBUG] Produit parsé dans {channel_id}: '{title}' | URL: {url} | Quicktask: {has_quicktask}")
                            now = time.time()
                            product_checkouts[title].append((now, msg["id"], url, has_quicktask, msg.copy()))
                            parsed_count += 1
                            # Nettoyer
                            product_checkouts[title] = [entry for entry in product_checkouts[title] if now - entry[0] <= 120]
                            print(f"[DEBUG] Checkouts pour '{title}': {len(product_checkouts[title])} après nettoyage")
                            if len(product_checkouts[title]) >= 3:
                                recent_msgs = product_checkouts[title][-5:]
                                prefix = f"🚀 Produit hot détecté ({title.title()}) - Messages originaux (3+ en 2min) :"
                                for i, entry in enumerate(recent_msgs):
                                    _, _, _, _, msg = entry
                                    if i == 0:
                                        msg_copy = msg.copy()
                                        msg_copy["content"] = prefix + "\n" + msg_copy.get("content", "")
                                        send_as_yora_webhook(msg_copy)
                                    else:
                                        send_as_yora_webhook(msg)
                                # Cooldown 5min
                                product_checkouts[f"cooldown_{title}"] = now + 300
                                product_checkouts[title] = []
                        last_message_ids[channel_id] = msg["id"]
                print(f"[DEBUG] {channel_id}: {parsed_count} produits parsés ce fetch")
            else:
                print(f"[{channel_id}] ❌ Erreur {response.status_code}: {response.text}")
        except Exception as e:
            print(f"[{channel_id}] ⚠️ Erreur dans fetch_messages: {e}")
        time.sleep(2)

# Nettoyage global cooldowns (dans une thread séparée si besoin, mais simple ici)
def cleanup_checkouts():
    global product_checkouts
    while True:
        now = time.time()
        to_remove = []
        for key in list(product_checkouts.keys()):
            if key.startswith("cooldown_"):
                if now > product_checkouts[key]:
                    to_remove.append(key)
                continue
            if isinstance(product_checkouts[key], list):
                product_checkouts[key] = [entry for entry in product_checkouts[key] if now - entry[0] <= 120]
                if len(product_checkouts[key]) == 0:
                    to_remove.append(key)
        for key in to_remove:
            del product_checkouts[key]
        time.sleep(30)  # Nettoie toutes les 30s

# Serveur Flask pour Railway
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot actif ✅", 200

if __name__ == "__main__":
    # Lancer cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_checkouts, daemon=True)
    cleanup_thread.start()
    
    # Lancer threads channels
    for channel_id in SOURCE_CHANNEL_IDS:
        thread = threading.Thread(target=fetch_messages, args=(channel_id,), daemon=True)
        thread.start()
    
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)
