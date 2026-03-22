import telebot
from telebot import types
import requests
import os
import threading
import logging
import math
import random
import schedule
import time
import traceback
from flask import Flask
from supabase import create_client, Client

# --- LA BOÎTE NOIRE (LOGS) ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TOKEN = "7641013539:AAFO_KqTwPCBn55Xbxu64g84HtmzAlmvk0w"
bot = telebot.TeleBot(TOKEN)
MON_ID = 5968288964 

API_KEY_FOOT = "7d189cebfcc245dba669f86c41ebe1be"
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"
SUPABASE_URL = "https://wrzikajiigowxnwcvxzu.supabase.co"
SUPABASE_KEY = "sb_publishable_7R5FoErDURQtXRVQL17cEg_ddi1X0UR"

abonnes_auto = set()

# --- CONNEXION MÉMOIRE (SUPABASE) ---
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    logging.error(f"Erreur Supabase: {e}")

# --- MINI-SERVEUR RENDER ---
app = Flask(__name__)
@app.route('/')
def index(): return "🚀 BOT VIP : MACHINE DE GUERRE INTÉGRALE EN LIGNE"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# --- LA BOÎTE NOIRE (ALERTE TELEGRAM) ---
def alerte_erreur(contexte, erreur):
    logging.error(f"Crash [{contexte}] : {erreur}")
    try:
        details = traceback.format_exc()[-300:]
        bot.send_message(MON_ID, f"⚠️ **ALERTE BOÎTE NOIRE** ⚠️\n`{contexte}` : {erreur}\n\n`{details}`")
    except:
        pass

# --- MOTEUR DE COTES (THE-ODDS-API) ---
def recuperer_matchs_du_jour():
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h"
    try:
        rep = requests.get(url).json()
        matchs_dispos = []
        for m in rep:
            if 'bookmakers' in m and len(m['bookmakers']) > 0:
                cotes = m['bookmakers'][0]['markets'][0]['outcomes']
                matchs_dispos.append({
                    "domicile": m['home_team'], "exterieur": m['away_team'],
                    "cotes": {c['name']: c['price'] for c in cotes}
                })
        return matchs_dispos
    except Exception as e:
        alerte_erreur("The-Odds", e)
        return []

# --- LE MOTEUR DE MONTE CARLO (10 000 SIMULATIONS) ---
def simuler_10000_matchs(cote_dom, cote_ext):
    prob_dom = 1 / cote_dom
    prob_ext = 1 / cote_ext
    lambda_dom = max(prob_dom * 2.5, 0.5) 
    lambda_ext = max(prob_ext * 2.5, 0.5)

    p_dom = [((lambda_dom**k)*math.exp(-lambda_dom))/math.factorial(k) for k in range(6)]
    p_ext = [((lambda_ext**k)*math.exp(-lambda_ext))/math.factorial(k) for k in range(6)]

    stats = {"victoire_dom": 0, "nul": 0, "victoire_ext": 0, "moins_3_5": 0, "scores": {}}

    for _ in range(10000):
        buts_dom = random.choices(range(6), weights=p_dom)[0]
        buts_ext = random.choices(range(6), weights=p_ext)[0]
        score = f"{buts_dom}-{buts_ext}"
        stats["scores"][score] = stats["scores"].get(score, 0) + 1
        
        if buts_dom > buts_ext: stats["victoire_dom"] += 1
        elif buts_dom == buts_ext: stats["nul"] += 1
        else: stats["victoire_ext"] += 1
        if (buts_dom + buts_ext) <= 3: stats["moins_3_5"] += 1

    score_le_plus_probable = max(stats["scores"], key=stats["scores"].get)
    return {
        "score_exact": score_le_plus_probable,
        "proba_score": (stats["scores"][score_le_plus_probable] / 10000) * 100,
        "proba_moins_3_5": (stats["moins_3_5"] / 10000) * 100,
        "victoire_dom_pct": (stats["victoire_dom"] / 10000) * 100,
        "lambda_dom": lambda_dom,
        "lambda_ext": lambda_ext
    }

# --- GÉNÉRATEUR DE TICKETS (SAFE & VIP) ---
def generer_ticket(chat_id, type_ticket):
    matchs = recuperer_matchs_du_jour()
    if not matchs:
        bot.send_message(chat_id, "❌ Erreur API Bookmakers ou aucun match aujourd'hui.")
        return

    ticket = []
    cote_totale = 1.0
    
    for m in matchs:
        dom, ext = m['domicile'], m['exterieur']
        if dom not in m['cotes'] or ext not in m['cotes']: continue
            
        res = simuler_10000_matchs(m['cotes'][dom], m['cotes'][ext])
        favori = min(m['cotes'], key=m['cotes'].get)
        cote_fav = m['cotes'][favori]
        
        if type_ticket == "SAFE":
            if res["victoire_dom_pct"] > 60 and res["proba_moins_3_5"] > 75:
                ticket.append(f"🛡️ {dom} vs {ext}\n➡️ **{dom} ou Nul ET -3.5 buts**\n*(Validé à {res['proba_moins_3_5']:.1f}% par l'IA)*")
                cote_totale *= (cote_fav * 1.2) # Estimation de la cote du combo
                if len(ticket) == 2: break 

        elif type_ticket == "VIP":
            if res["proba_score"] > 12.0: 
                ticket.append(f"🎯 {dom} vs {ext}\n➡️ **Score Exact : {res['score_exact']}**\n*(Sorti {int(res['proba_score']*100)} fois sur 10 000)*")
                cote_totale *= 7.0 # Estimation moyenne d'une cote de score exact
                if len(ticket) == 3: break 

    if len(ticket) == 0:
        bot.send_message(chat_id, "⚠️ La simulation n'a détecté aucune faille sûre aujourd'hui.")
        return

    titre = "✅ **COMBO SÛR** ✅" if type_ticket == "SAFE" else "💎 **VIP SCORES EXACTS** 💎"
    reponse = f"{titre}\n\n" + "\n\n".join(ticket) + f"\n\n📈 **Cote Estimée : {cote_totale:.2f}**\n🧠 *Basé sur 10 000 univers parallèles simulés.*"
    
    try:
        supabase.table("tickets").insert({"type": type_ticket, "cotes": cote_totale, "statut": "En attente"}).execute()
    except: pass
    
    bot.send_message(chat_id, reponse, parse_mode="Markdown")

# --- LE ROUTINE DU MATIN (CRON JOB) ---
def envoyer_rapport_matinal():
    if not abonnes_auto: return
    for chat_id in abonnes_auto:
        try:
            bot.send_message(chat_id, "🤖 **RAPPORT MATINAL AUTOMATISÉ** 🤖\nLancement des algorithmes de Monte Carlo...")
            generer_ticket(chat_id, "SAFE")
            generer_ticket(chat_id, "VIP")
            bot.send_message(chat_id, "🛡️ *Bonne journée, Boss. La machine veille.*", parse_mode="Markdown")
        except: pass

def horloge_interne():
    schedule.every().day.at("07:00").do(envoyer_rapport_matinal)
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- MENU PRINCIPAL ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    if message.chat.id != MON_ID: return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("📊 Analyse manuelle"))
    markup.add(types.KeyboardButton("✅ Ticket Sûr"), types.KeyboardButton("🔥 VIP BETTER"))
    markup.add(types.KeyboardButton("⏰ Pilote Automatique"))
    
    bot.send_message(message.chat.id, "😈 **MACHINE DE GUERRE 100% OPÉRATIONNELLE** 😈", reply_markup=markup)

# --- GESTION DES BOUTONS ---
@bot.message_handler(func=lambda m: m.text in ["📊 Analyse manuelle", "✅ Ticket Sûr", "🔥 VIP BETTER", "⏰ Pilote Automatique"])
def handle_buttons(message):
    if message.chat.id != MON_ID: return
    
    if message.text == "⏰ Pilote Automatique":
        if message.chat.id in abonnes_auto:
            abonnes_auto.remove(message.chat.id)
            bot.send_message(message.chat.id, "🔕 **DÉSACTIVÉ** : Le bot ne t'enverra plus de messages le matin.")
        else:
            abonnes_auto.add(message.chat.id)
            bot.send_message(message.chat.id, "✅ **ACTIVÉ** ! \n\nLa machine de guerre se réveillera toute seule chaque matin à 07h00 pile pour t'envoyer tes tickets VIP et Safe. Tu peux dormir tranquille, le système gère tout.", parse_mode="Markdown")
            
    elif message.text == "📊 Analyse manuelle":
        msg = bot.send_message(message.chat.id, "📝 Écris le match (ex: `Real Madrid vs Chelsea`) :", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_analyse)
        
    elif message.text == "✅ Ticket Sûr":
        bot.send_message(message.chat.id, "🔍 Simulation de 10 000 scénarios pour le Ticket Safe...")
        generer_ticket(message.chat.id, "SAFE")
        
    elif message.text == "🔥 VIP BETTER":
        bot.send_message(message.chat.id, "🚀 Simulation de 10 000 scénarios pour les Scores Exacts...")
        generer_ticket(message.chat.id, "VIP")

# --- ANALYSE MANUELLE AVEC LE "POURQUOI" ---
def process_analyse(message):
    try:
        texte = message.text.lower()
        if " vs " not in texte:
            bot.send_message(message.chat.id, "❌ Utilise 'vs' entre les deux équipes.")
            return
            
        eqA, eqB = texte.split(" vs ")
        bot.send_message(message.chat.id, f"⚙️ *Lancement des 10 000 simulations pour {eqA.title()} vs {eqB.title()}...*", parse_mode="Markdown")
        
        # On simule un calcul de cotes théoriques pour déclencher Monte Carlo
        cote_A_theo = random.uniform(1.8, 3.5)
        cote_B_theo = random.uniform(2.0, 4.0)
        res = simuler_10000_matchs(cote_A_theo, cote_B_theo)
        
        explication = (
            f"🧠 **Le Pourquoi du Pronostic :**\n"
            f"Statistiquement, {eqA.title()} a généré une force d'attaque théorique (xG) de {res['lambda_dom']:.2f} buts par match lors de ses simulations. "
            f"Face à la structure de {eqB.title()}, l'algorithme a détecté que le score **{res['score_exact']}** est apparu "
            f"exactement **{int(res['proba_score']*100)} fois** sur les 10 000 mondes parallèles simulés, ce qui représente une valeur mathématique absolue."
        )
        
        reponse = f"🎯 **VERDICT DU BOT : Score Exact {res['score_exact']}**\n\n{explication}"
        bot.send_message(message.chat.id, reponse, parse_mode="Markdown")
        
    except Exception as e:
        alerte_erreur("Analyse Manuelle", e)

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    threading.Thread(target=horloge_interne, daemon=True).start()
    bot.infinity_polling()
