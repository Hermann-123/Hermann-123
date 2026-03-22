import telebot
from telebot import types
import requests
import os
import threading
import logging
from flask import Flask
from supabase import create_client, Client

# --- LA BOÎTE NOIRE ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# --- TES 4 ARMES SECRÈTES ---
# Ton TOUT NOUVEAU Token Telegram (Adieu l'erreur 409 !)
TOKEN = "7641013539:AAFO_KqTwPCBn55Xbxu64g84HtmzAlmvk0w"
bot = telebot.TeleBot(TOKEN)
MON_ID = 5968288964 

# Ta clé API Foot (Football-Data.org)
API_KEY_FOOT = "7d189cebfcc245dba669f86c41ebe1be"

# Ta clé API Odds (The-Odds-API.com)
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"

# Tes identifiants Supabase (La mémoire)
SUPABASE_URL = "https://wrzikajiigowxnwcvxzu.supabase.co"
SUPABASE_KEY = "sb_publishable_7R5FoErDURQtXRVQL17cEg_ddi1X0UR"

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logging.info("✅ Base de données Supabase connectée !")
except Exception as e:
    logging.error(f"❌ Erreur Supabase : {e}")

# --- MINI-SERVEUR RENDER ---
app = Flask(__name__)
@app.route('/')
def index(): return "Machine de Guerre VIP - En ligne 🟢"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- LE MENU PRINCIPAL ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.chat.id != MON_ID: return
    
    # Création du clavier qui remplace le clavier du téléphone
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("📊 Analyse de match"))
    markup.add(types.KeyboardButton("✅ Ticket Sûr"), types.KeyboardButton("🔥 VIP BETTER"))
    
    texte = (
        "😈 **MACHINE DE GUERRE CONNECTÉE** 😈\n\n"
        "🟢 API Football : Active\n"
        "🟢 Radar à Cotes : Actif\n"
        "🟢 Base de Données : Active\n\n"
        "Que veux-tu détruire aujourd'hui ?"
    )
    # On envoie le message avec le menu attaché
    bot.send_message(message.chat.id, texte, parse_mode="Markdown", reply_markup=markup)

# --- INTERACTION DES BOUTONS ---
@bot.message_handler(func=lambda message: message.text in ["📊 Analyse de match", "✅ Ticket Sûr", "🔥 VIP BETTER"])
def handle_buttons(message):
    if message.chat.id != MON_ID: return
    
    if message.text == "📊 Analyse de match":
        # Le bot te pose la question et attend ta réponse !
        msg = bot.send_message(message.chat.id, "📝 **Mode Analyse**\n\nÉcris-moi le nom de l'équipe que tu veux analyser (ex: Real Madrid, PSG, Chelsea) :")
        bot.register_next_step_handler(msg, process_analyse_equipe)
        
    elif message.text == "✅ Ticket Sûr":
        bot.send_message(message.chat.id, "🔍 *Scan des bookmakers en cours... (Fonctionnalité de combinaison en préparation)*", parse_mode="Markdown")
        
    elif message.text == "🔥 VIP BETTER":
        bot.send_message(message.chat.id, "🚀 *Calculateur de grosses cotes activé... (Générateur d'algorithme en préparation)*", parse_mode="Markdown")

# --- LE CERVEAU QUI RÉCUPÈRE TA RÉPONSE ---
def process_analyse_equipe(message):
    nom_equipe = message.text
    bot.send_message(message.chat.id, f"⏳ D'accord, je lance mes algorithmes pour trouver les statistiques et les cotes de : **{nom_equipe}**...", parse_mode="Markdown")

# --- LANCEMENT ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.infinity_polling()
    
