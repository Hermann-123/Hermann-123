import asyncio
import os
import re
import random
import sqlite3
import csv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# ==========================================
# 1. TES CLÉS SECRÈTES
# ==========================================
API_ID = 36539428
API_HASH = 'edf612a165870ac5932ba064c104d47a'

SESSION_STRING = "1BJWap1sBu120WWNRfQ9M4dFus6LsgU1PdkO2z2zFerIePvUk67yz1c9bfGPQFvNY-6iteTFrjn0-Lt4md7kHEjeZkFsvPIaXifXk7KxHgSd7zKOMue8SvqSXxm5J8vAhDMXvAXO6PeaH1jDTqFj6iEnFoB-4CC2dBlDr8T6fxZCbvCdPWBRIlUWIed765ZWy4A8ACmHVMaN-Z810BXxV6DTRZB8a-y2DFgmpbAxF7PIYYcykD4oKayW9eilPAQzvDFl3ii0OYnWCPg9Ff6PqUc78vps-Znf9fLHq_QgcYxA7HAdT5BTv74pr6ZfDR9Jo0xgE2tBltMpvwzaVoT2prTAUg08DrsQ="
BOT_TOKEN = "7432405570:AAGqkeFs72lzzVuW_Ea_N8kKLBXBCIc7bc4"

CANAL_CIBLE = '@statistika_baccara'

# ==========================================
# 2. BASE DE DONNÉES MULTI-JOUEURS
# ==========================================
conn = sqlite3.connect('baccarat_cerveau.db', check_same_thread=False)
cursor = conn.cursor()

# Mémoire globale des jeux (La même pour tout le monde)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS historique (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_jeu INTEGER,
        gagnant TEXT
    )
''')
# Liste des abonnés du bot
cursor.execute('''
    CREATE TABLE IF NOT EXISTS utilisateurs (
        chat_id INTEGER PRIMARY KEY
    )
''')
# Finances individuelles (Chacun son argent)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS finances (
        chat_id INTEGER PRIMARY KEY,
        capital_depart REAL,
        capital_actuel REAL
    )
''')
# Prédictions individuelles (Chacun ses paris)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS predictions (
        chat_id INTEGER,
        numero_jeu INTEGER,
        choix_predit TEXT,
        PRIMARY KEY (chat_id, numero_jeu)
    )
''')
conn.commit()

memoire_tendance = {"dernier_gagnant": None, "serie_en_cours": 0}

espion = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
bot_officiel = TelegramClient(StringSession(""), API_ID, API_HASH)

# ==========================================
# 3. LE SERVEUR DE MAINTIEN (Render)
# ==========================================
async def handle_client(reader, writer):
    writer.write(b'HTTP/1.0 200 OK\r\n\r\nMachine Hedge Fund MULTI-JOUEURS Active !')
    await writer.drain()
    writer.close()

async def start_dummy_server():
    port = int(os.environ.get('PORT', 10000))
    server = await asyncio.start_server(handle_client, '0.0.0.0', port)
    async with server:
        await server.serve_forever()

# ==========================================
# 4. TÊTE 1 : L'ESPION (Enregistrement + Broadcast global)
# ==========================================
@espion.on(events.NewMessage(chats=CANAL_CIBLE))
async def handler_baccarat(event):
    texte_recu = event.message.text
    
    match = re.search(r'#?N?\s*(\d+)[\.\s]+(\d+)\s*\((.*?)\)[\s\-\>▶️]*(\d+)\s*\((.*?)\)', texte_recu, re.IGNORECASE)
    
    if match:
        partie = match.group(1)
        score_joueur = int(match.group(2))
        cartes_joueur = match.group(3)
        score_banque = int(match.group(4))
        cartes_banque = match.group(5)

        if score_joueur > score_banque: gagnant_actuel = "🔵 JOUEUR"
        elif score_banque > score_joueur: gagnant_actuel = "🔴 BANQUE"
        else: gagnant_actuel = "🟢 ÉGALITÉ"

        # 1. Sauvegarde Globale
        cursor.execute("INSERT INTO historique (numero_jeu, gagnant) VALUES (?, ?)", (int(partie), gagnant_actuel))
        conn.commit()

        # 2. Le Jugement MULTI-JOUEURS (Vérifie les paris de TOUS les utilisateurs)
        try:
            cursor.execute("SELECT chat_id, choix_predit FROM predictions WHERE numero_jeu = ?", (int(partie),))
            toutes_les_predictions = cursor.fetchall()
            
            for pred in toutes_les_predictions:
                client_id = pred[0]
                choix_du_bot = pred[1]
                
                if choix_du_bot == gagnant_actuel:
                    verdict = f"✅ **BINGO ! PRÉDICTION GAGNANTE !**\nLe jeu #{partie} est passé."
                else:
                    verdict = f"❌ **PRÉDICTION PERDUE.**\nLe résultat du jeu #{partie} était {gagnant_actuel}."
                
                try:
                    await bot_officiel.send_message(client_id, verdict)
                except:
                    pass # Si l'utilisateur a bloqué le bot, on ignore
        except Exception as e:
            print(f"Erreur Jugement : {e}")

        # 3. Calcul des tendances
        global memoire_tendance
        if gagnant_actuel == memoire_tendance["dernier_gagnant"] and gagnant_actuel != "🟢 ÉGALITÉ":
            memoire_tendance["serie_en_cours"] += 1
        else:
            if gagnant_actuel != "🟢 ÉGALITÉ":
                memoire_tendance["dernier_gagnant"] = gagnant_actuel
                memoire_tendance["serie_en_cours"] = 1

        # 4. Le Mégaphone : Envoi de l'alerte à TOUTE LA LISTE D'ABONNÉS
        message = f"🎰 **BACCARAT - Partie #{partie}**\n\n"
        message += f"🔵 **Joueur :** {score_joueur}  *(Cartes: {cartes_joueur})*\n"
        message += f"🔴 **Banque :** {score_banque}  *(Cartes: {cartes_banque})*\n\n"
        message += f"🏆 **Résultat : {gagnant_actuel}**\n"

        if memoire_tendance["serie_en_cours"] >= 3:
            message += f"🔥 **SÉRIE EN COURS :** Le {gagnant_actuel} a gagné **{memoire_tendance['serie_en_cours']} fois** de suite !\n"

        prochain_jeu = int(partie) + 1
        bouton_data = f"analyse_{prochain_jeu}".encode('utf-8')

        cursor.execute("SELECT chat_id FROM utilisateurs")
        tous_les_clients = cursor.fetchall()

        for client in tous_les_clients:
            client_id = client[0]
            try:
                await bot_officiel.send_message(client_id, message, buttons=[Button.inline(f'📊 Analyser Jeu #{prochain_jeu}', data=bouton_data)])
            except:
                pass

# ==========================================
# 5. TÊTE 2 : COMMANDES ET ANALYSES INDIVIDUELLES
# ==========================================
@bot_officiel.on(events.NewMessage(pattern=r'^/start'))
async def start_cmd(event):
    user_id = event.chat_id
    # Enregistre le nouvel utilisateur s'il n'existe pas
    cursor.execute("INSERT OR IGNORE INTO utilisateurs (chat_id) VALUES (?)", (user_id,))
    # Lui crée un compte bancaire virtuel par défaut s'il n'en a pas
    cursor.execute("INSERT OR IGNORE INTO finances (chat_id, capital_depart, capital_actuel) VALUES (?, 10000, 10000)", (user_id,))
    conn.commit()
    
    bienvenue = "👋 **Bienvenue dans le Bot Hedge Fund Baccarat !**\n\n"
    bienvenue += "Je suis connecté au réseau d'analyse. Tu vas bientôt recevoir les prochains tirages.\n\n"
    bienvenue += "💰 **Important :** Tape `/capital 10000` (remplace 10000 par ta vraie bankroll 1xBet) pour que je calcule tes mises sans te ruiner !"
    await event.reply(bienvenue)

@bot_officiel.on(events.NewMessage(pattern=r'^/stats'))
async def get_stats(event):
    cursor.execute("SELECT COUNT(*) FROM historique")
    total = cursor.fetchone()[0]
    
    if total == 0:
        await event.reply("📂 La mémoire est vide. En attente de tirages...")
        return

    cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🔴 BANQUE'")
    vic_b = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🔵 JOUEUR'")
    vic_j = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🟢 ÉGALITÉ'")
    vic_e = cursor.fetchone()[0]

    reponse = "🖥️ **TABLEAU DE BORD DU BOT** 🖥️\n\n"
    reponse += f"📊 **Mémoire Totale :** {total} parties\n"
    reponse += f"🔴 **Victoires Banque :** {vic_b} ({ (vic_b/total)*100:.1f}%)\n"
    reponse += f"🔵 **Victoires Joueur :** {vic_j} ({ (vic_j/total)*100:.1f}%)\n"
    reponse += f"🟢 **Égalités :** {vic_e} ({ (vic_e/total)*100:.1f}%)\n\n"
    
    etat_ia = "🚀 ACTIVE" if total >= 10 else "⏳ APPRENTISSAGE"
    reponse += f"🧠 **Statut IA :** {etat_ia}"
    
    await event.reply(reponse)

@bot_officiel.on(events.NewMessage(pattern=r'^/capital\s+(\d+)'))
async def set_capital(event):
    user_id = event.chat_id
    montant = float(event.pattern_match.group(1))
    cursor.execute("UPDATE finances SET capital_depart = ?, capital_actuel = ? WHERE chat_id = ?", (montant, montant, user_id))
    conn.commit()
    await event.reply(f"🏦 Ton capital personnel est enregistré : {montant} FCFA.")

@bot_officiel.on(events.CallbackQuery(pattern=b'^analyse_'))
async def handler_bouton(event):
    try:
        user_id = event.chat_id
        await event.answer("Calcul IA... ⏳")
        numero_cible = event.data.decode('utf-8').split('_')[1]
        
        # Le bot regarde les finances personnelles de CE joueur précis
        cursor.execute("SELECT capital_actuel FROM finances WHERE chat_id = ?", (user_id,))
        finance_data = cursor.fetchone()
        
        if not finance_data:
            await bot_officiel.send_message(user_id, "⚠️ **ERREUR :** Compte non initialisé. Tape `/start` puis `/capital 10000`.")
            return
            
        actuel = finance_data[0]
        
        cursor.execute("SELECT COUNT(*) FROM historique")
        total_p = cursor.fetchone()[0]

        if total_p > 10:
            cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🔴 BANQUE'")
            p_b = max((cursor.fetchone()[0] / total_p) * 100, 40.0)
            cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🔵 JOUEUR'")
            p_j = max((cursor.fetchone()[0] / total_p) * 100, 40.0)
            texte_memoire = f"Algorithme ajusté sur {total_p} parties."
        else:
            p_b, p_j = 45.86, 44.62
            texte_memoire = "Probabilités théoriques (Apprentissage...)."

        victoires_banque_mc = 0
        victoires_joueur_mc = 0
        for _ in range(10000):
            tirage = random.uniform(0, 100)
            if tirage < p_b: victoires_banque_mc += 1
            elif tirage < (p_b + p_j): victoires_joueur_mc += 1

        taux_banque = (victoires_banque_mc / 10000) * 100
        taux_joueur = (victoires_joueur_mc / 10000) * 100

        choix_final = "🔴 BANQUE" if taux_banque > taux_joueur else "🔵 JOUEUR"
        p_win = (taux_banque / 100) if taux_banque > taux_joueur else (taux_joueur / 100)
        
        # 🚨 SAUVEGARDE DE LA PRÉDICTION INDIVIDUELLE
        cursor.execute("INSERT OR REPLACE INTO predictions (chat_id, numero_jeu, choix_predit) VALUES (?, ?, ?)", (user_id, int(numero_cible), choix_final))
        conn.commit()

        # Kelly Criterion
        COTE_MOYENNE = 1.90
        b = COTE_MOYENNE - 1.0 
        q = 1.0 - p_win         
        fraction_kelly = ( (p_win * b) - q ) / b
        fraction_kelly = fraction_kelly / 2 
        
        if fraction_kelly <= 0:
            alerte_risque = "🛑 RISQUE ÉLEVÉ : Ne joue pas ce tour."
        else:
            fraction_kelly = min(fraction_kelly, 0.05) 
            mise_conseillee = int(actuel * fraction_kelly)
            alerte_risque = f"✅ FEU VERT : Miser {mise_conseillee} FCFA"

        rapport = f"🎯 **PRÉDICTION JEU #{numero_cible}** 🎯\n\n"
        rapport += f"🧠 **MÉMOIRE** : _{texte_memoire}_\n\n"
        rapport += "🎲 **SIMULATION MONTE-CARLO** :\n"
        rapport += f"• Victoire Banque : {taux_banque:.1f}%\n"
        rapport += f"• Victoire Joueur : {taux_joueur:.1f}%\n\n"
        rapport += f"💡 **LE CHOIX : {choix_final}**\n\n"
        rapport += "🛡️ **GESTION DU RISQUE (Kelly)** :\n"
        rapport += f"• Ton Solde : {actuel} FCFA\n"
        rapport += f"• {alerte_risque}"
        
        await bot_officiel.send_message(user_id, rapport)
    except Exception as e:
        await bot_officiel.send_message(user_id, f"❌ Erreur Bouton : {e}")

# ==========================================
# 6. LANCEMENT
# ==========================================
async def main():
    await espion.start()
    await bot_officiel.start(bot_token=BOT_TOKEN)
    asyncio.create_task(start_dummy_server())
    await asyncio.gather(espion.run_until_disconnected(), bot_officiel.run_until_disconnected())

if __name__ == '__main__':
    asyncio.run(main())
