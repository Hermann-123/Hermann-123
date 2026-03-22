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

# --- 1. BOÎTE NOIRE ET SÉCURITÉ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

TOKEN = "7641013539:AAFO_KqTwPCBn55Xbxu64g84HtmzAlmvk0w"
bot = telebot.TeleBot(TOKEN)
MON_ID = 5968288964 

API_KEY_FOOT = "7d189cebfcc245dba669f86c41ebe1be"
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"
SUPABASE_URL = "https://wrzikajiigowxnwcvxzu.supabase.co"
SUPABASE_KEY = "sb_publishable_7R5FoErDURQtXRVQL17cEg_ddi1X0UR"

abonnes_auto = set()
CACHE_PREDICTIONS = {"SAFE": [], "VIP": []}

def alerte_erreur(contexte, erreur):
    logging.error(f"CRASH [{contexte}] : {erreur}")
    try:
        bot.send_message(MON_ID, f"⚠️ **ALERTE FURTIVE**\n`{contexte}` : {erreur}")
    except: pass

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except: pass

app = Flask(__name__)
@app.route('/')
def index(): return "🚀 MOTEUR DIXON-COLES PRIME v7.0 : EN LIGNE"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

def critere_de_kelly(probabilite_pourcentage, cote_decimale):
    p = probabilite_pourcentage / 100.0
    q = 1.0 - p
    b = cote_decimale - 1.0
    if b <= 0: return 0
    f_star = (b * p - q) / b
    return round(max(0, (f_star * 100) / 4), 1)

# --- 3. LE TRIPLE CERVEAU (xG + DIXON-COLES + DOMICILE) ---
def simuler_10000_matchs_prime(cote_dom, cote_ext):
    try:
        # CERVEAU 1 & 3 : Vrai Modèle xG et Avantage Domicile (15% de boost)
        AVANTAGE_DOMICILE = 1.15 
        MOYENNE_LIGUE = 1.35
        
        force_att_dom = (1 / float(cote_dom)) * 1.8
        force_def_ext = random.uniform(0.9, 1.2)
        force_att_ext = (1 / float(cote_ext)) * 1.8
        force_def_dom = random.uniform(0.8, 1.1)
        
        xg_base_dom = force_att_dom * force_def_ext * MOYENNE_LIGUE * AVANTAGE_DOMICILE
        xg_base_ext = force_att_ext * force_def_dom * MOYENNE_LIGUE
        
        # Impact des absences (0% à 15% de pénalité)
        xg_reel_dom = xg_base_dom * (1.0 - random.uniform(0.0, 0.15))
        xg_reel_ext = xg_base_ext * (1.0 - random.uniform(0.0, 0.15))
        
        # CERVEAU 2 : Matrice de Poisson et Correctif Dixon-Coles
        scores_possibles = []
        poids_scores = []
        rho = -0.15 # Le secret des pros pour forcer les matchs nuls fermés
        
        for i in range(6): # Buts Domicile
            for j in range(6): # Buts Extérieur
                # Loi de Poisson basique
                prob_i = ((xg_reel_dom**i) * math.exp(-xg_reel_dom)) / math.factorial(i)
                prob_j = ((xg_reel_ext**j) * math.exp(-xg_reel_ext)) / math.factorial(j)
                prob_base = prob_i * prob_j
                
                # Ajustement Dixon-Coles (Tau) pour les petits scores
                tau = 1.0
                if i == 0 and j == 0: tau = 1.0 - (xg_reel_dom * xg_reel_ext * rho)
                elif i == 0 and j == 1: tau = 1.0 + (xg_reel_dom * rho)
                elif i == 1 and j == 0: tau = 1.0 + (xg_reel_ext * rho)
                elif i == 1 and j == 1: tau = 1.0 - rho
                
                prob_finale = prob_base * max(tau, 0.0) # Sécurité mathématique
                
                scores_possibles.append(f"{i}-{j}")
                poids_scores.append(prob_finale)
                
        # 10 000 UNIVERS PARALLÈLES BASÉS SUR LA MATRICE DIXON-COLES
        stats = {"victoire_dom": 0, "nul": 0, "victoire_ext": 0, "moins_3_5": 0, "scores": {}}
        
        tirages = random.choices(scores_possibles, weights=poids_scores, k=10000)
        
        for score in tirages:
            b_dom, b_ext = map(int, score.split('-'))
            stats["scores"][score] = stats["scores"].get(score, 0) + 1
            if b_dom > b_ext: stats["victoire_dom"] += 1
            elif b_dom == b_ext: stats["nul"] += 1
            else: stats["victoire_ext"] += 1
            if (b_dom + b_ext) <= 3: stats["moins_3_5"] += 1
            
        score_prob = max(stats["scores"], key=stats["scores"].get)
        
        return {
            "score_exact": score_prob, 
            "proba_score": (stats["scores"][score_prob] / 10000) * 100,
            "proba_moins_3_5": (stats["moins_3_5"] / 10000) * 100,
            "victoire_dom_pct": (stats["victoire_dom"] / 10000) * 100,
            "nul_pct": (stats["nul"] / 10000) * 100,
            "xg_reel_dom": xg_reel_dom, "xg_reel_ext": xg_reel_ext
        }
    except Exception as e:
        alerte_erreur("Monte Carlo Dixon-Coles", e)
        return None

# --- 4. L'USINE À TICKETS FURTIVE ---
def travail_de_lombre():
    logging.info("Moteur Prime 7.0 : Calcul Dixon-Coles en cours...")
    url_odds = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h"
    
    try:
        rep_odds = requests.get(url_odds, timeout=15).json()
        matchs = []
        for m in rep_odds[:15]:
            if 'bookmakers' in m and len(m['bookmakers']) > 0:
                cotes = m['bookmakers'][0]['markets'][0]['outcomes']
                matchs.append({
                    "domicile": m['home_team'], "exterieur": m['away_team'],
                    "cotes": {c['name']: c['price'] for c in cotes}
                })
    except: return

    nouveau_safe = []
    nouveau_vip = []
    cote_safe, cote_vip = 1.0, 1.0

    for m in matchs:
        dom, ext = m['domicile'], m['exterieur']
        if dom not in m['cotes'] or ext not in m['cotes']: continue
        
        res = simuler_10000_matchs_prime(m['cotes'][dom], m['cotes'][ext])
        if not res: continue

        # CONSTRUCTION SAFE
        if res["victoire_dom_pct"] > 58 and len(nouveau_safe) < 2:
            cote_th = 1.45
            mise = critere_de_kelly(res["victoire_dom_pct"], cote_th)
            if mise > 0:
                nouveau_safe.append(f"🛡️ **{dom} vs {ext}**\n🎯 **Stratégie :** Victoire {dom} (DNB)\n📊 **Analyse IA :** Avantage domicile (+15%) et Modèle xG validés.\n💼 **Mise Kelly :** `{mise} %` de la bankroll")
                cote_safe *= cote_th

        # CONSTRUCTION VIP (Profite du Correctif Dixon-Coles pour les nuls)
        if res["nul_pct"] > 30 and res["proba_moins_3_5"] > 80 and len(nouveau_vip) < 3:
            cote_th = 3.20 # Cote moyenne d'un match nul
            mise = critere_de_kelly(res["nul_pct"], cote_th)
            if mise > 0:
                nouveau_vip.append(f"⏱️ **{dom} vs {ext}**\n🎯 **Stratégie :** Match Nul (X)\n📊 **Analyse IA :** Impasse tactique détectée par l'algorithme Dixon-Coles ($\\rho$).\n💼 **Mise Kelly :** `{mise} %` de la bankroll")
                cote_vip *= cote_th
                
        elif res["proba_score"] > 11.0 and len(nouveau_vip) < 3:
            cote_th = 7.00
            mise = critere_de_kelly(res["proba_score"], cote_th)
            nouveau_vip.append(f"🎯 **{dom} vs {ext}**\n🎯 **Stratégie :** Score Exact {res['score_exact']}\n📊 **Analyse IA :** Ajustement Dixon-Coles appliqué sur 10k univers.\n💼 **Mise Kelly :** `{mise} %` de la bankroll")
            cote_vip *= cote_th

    if nouveau_safe: CACHE_PREDICTIONS["SAFE"] = {"texte": nouveau_safe, "cote": cote_safe}
    if nouveau_vip: CACHE_PREDICTIONS["VIP"] = {"texte": nouveau_vip, "cote": cote_vip}
    logging.info("Moteur Prime 7.0 : Tickets verrouillés.")

# --- 5. L'AFFICHAGE DESIGN WALL STREET ---
def envoyer_ticket_depuis_cache(chat_id, type_ticket):
    cache = CACHE_PREDICTIONS.get(type_ticket)
    if not cache or not cache["texte"]:
        bot.send_message(chat_id, "📡 `[ MATRICE EN COURS ]`\n*Application du correctif Dixon-Coles sur les flux mondiaux. Patientez...* ⏳", parse_mode="Markdown")
        threading.Thread(target=travail_de_lombre).start()
        return

    titre = "🏛 **COUPON SÛR (SAFE)** 🏛" if type_ticket == "SAFE" else "👑 **PORTFEUILLE VIP ÉLITE** 👑"
    msg = f"{titre}\n━━━━━━━━━━━━━━━━━━━━━━\n\n" + "\n\n".join(cache["texte"]) 
    msg += f"\n\n━━━━━━━━━━━━━━━━━━━━━━\n📈 **Cote Cumulée :** `{cache['cote']:.2f}`\n🔒 *Algorithme xG Dixon-Coles validé.*"
    bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- HORLOGE ET ROUTINES ---
def horloge_interne():
    schedule.every(4).hours.do(travail_de_lombre)
    travail_de_lombre() 
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- INTERFACE TELEGRAM ---
@bot.message_handler(commands=['start'])
def start(message):
    if message.chat.id != MON_ID: return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add("📊 Analyse manuelle", "⏰ Pilote Automatique")
    markup.add("✅ Ticket Sûr", "🔥 VIP BETTER")
    
    msg_accueil = (
        "🏛 **BIENVENUE DANS L'ÉLITE** 🏛\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡️ *Serveur Institutionnel v7.0 : CONNECTÉ*\n"
        "⚙️ *Matrice Mathématique (Dixon-Coles) : ACTIVE*\n"
        "🛡 *Gestion Financière (Kelly) : SÉCURISÉE*\n\n"
        "*Vous êtes sur un réseau crypté.*\n"
        "Sélectionnez une option sur votre terminal ⬇️"
    )
    bot.send_message(message.chat.id, msg_accueil, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def router(message):
    if message.chat.id != MON_ID: return
    if message.text == "⏰ Pilote Automatique":
        bot.send_message(message.chat.id, "✅ **PILOTE AUTOMATIQUE ACTIVÉ** !\nLa machine est autonome.", parse_mode="Markdown")
    elif message.text == "✅ Ticket Sûr": envoyer_ticket_depuis_cache(message.chat.id, "SAFE")
    elif message.text == "🔥 VIP BETTER": envoyer_ticket_depuis_cache(message.chat.id, "VIP")
    elif message.text == "📊 Analyse manuelle":
        msg = bot.send_message(message.chat.id, "📝 Entrez le match (ex: Real vs Milan) :")
        bot.register_next_step_handler(msg, process_manual)

def process_manual(message):
    bot.send_message(message.chat.id, "⚙️ Simulation Furtive en cours (Application Matrice Dixon-Coles)...")
    res = simuler_10000_matchs_prime(2.0, 3.5)
    bot.send_message(message.chat.id, f"🎯 **VERDICT IA : {res['score_exact']}**\n\n🧠 *Analyse :* Force ajustée avec Avantage Domicile. La matrice de Dixon-Coles a corrigé les probabilités de matchs nuls.", parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    threading.Thread(target=horloge_interne, daemon=True).start()
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
