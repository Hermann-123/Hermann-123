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

CHAT_ID = 5968288964
CANAL_CIBLE = '@statistika_baccara'

# ==========================================
# 2. BASE DE DONNÉES & MÉMOIRE
# ==========================================
conn = sqlite3.connect('baccarat_cerveau.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS historique (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero_jeu INTEGER,
        gagnant TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS finances (
        id INTEGER PRIMARY KEY,
        capital_depart REAL,
        capital_actuel REAL
    )
''')
# Initialisation des finances si vide
cursor.execute("SELECT COUNT(*) FROM finances")
if cursor.fetchone()[0] == 0:
    cursor.execute("INSERT INTO finances (id, capital_depart, capital_actuel) VALUES (1, 10000, 10000)")
conn.commit()

memoire_tendance = {
    "dernier_gagnant": None,
    "serie_en_cours": 0
}

espion = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
bot_officiel = TelegramClient(StringSession(""), API_ID, API_HASH)

# ==========================================
# 3. LE FAUX SERVEUR WEB (Pour Render)
# ==========================================
async def handle_client(reader, writer):
    writer.write(b'HTTP/1.0 200 OK\r\n\r\nMachine Hedge Fund Active !')
    await writer.drain()
    writer.close()

async def start_dummy_server():
    port = int(os.environ.get('PORT', 10000))
    server = await asyncio.start_server(handle_client, '0.0.0.0', port)
    async with server:
        await server.serve_forever()

# ==========================================
# 4. TÊTE 1 : L'ESPION (Archivage)
# ==========================================
@espion.on(events.NewMessage(chats=CANAL_CIBLE))
async def handler_baccarat(event):
    texte_recu = event.message.text
    match = re.search(r'#N(\d+)\.\s*(\d+)\((.*?)\)\s*-\s*(?:▶️\s*)?(\d+)\((.*?)\)', texte_recu)
    
    if match:
        partie = match.group(1)
        score_joueur = int(match.group(2))
        cartes_joueur = match.group(3)
        score_banque = int(match.group(4))
        cartes_banque = match.group(5)

        if score_joueur > score_banque: gagnant_actuel = "🔵 JOUEUR"
        elif score_banque > score_joueur: gagnant_actuel = "🔴 BANQUE"
        else: gagnant_actuel = "🟢 ÉGALITÉ"

        cursor.execute("INSERT INTO historique (numero_jeu, gagnant) VALUES (?, ?)", (int(partie), gagnant_actuel))
        conn.commit()

        global memoire_tendance
        if gagnant_actuel == memoire_tendance["dernier_gagnant"] and gagnant_actuel != "🟢 ÉGALITÉ":
            memoire_tendance["serie_en_cours"] += 1
        else:
            if gagnant_actuel != "🟢 ÉGALITÉ":
                memoire_tendance["dernier_gagnant"] = gagnant_actuel
                memoire_tendance["serie_en_cours"] = 1

        message = f"🎰 **BACCARAT - Partie #{partie}**\n\n"
        message += f"🔵 **Joueur :** {score_joueur}  *(Cartes: {cartes_joueur})*\n"
        message += f"🔴 **Banque :** {score_banque}  *(Cartes: {cartes_banque})*\n\n"
        message += f"🏆 **Résultat : {gagnant_actuel}**\n"

        if memoire_tendance["serie_en_cours"] >= 3:
            message += f"🔥 **SÉRIE EN COURS :** Le {gagnant_actuel} a gagné **{memoire_tendance['serie_en_cours']} fois** de suite !\n"

        cursor.execute("SELECT COUNT(*) FROM historique")
        message += f"\n📊 *Mémoire : {cursor.fetchone()[0]} parties.*"

        prochain_jeu = int(partie) + 1
        bouton_secret = f"analyse_{prochain_jeu}".encode('utf-8')

        try:
            await bot_officiel.send_message(CHAT_ID, message, buttons=[Button.inline(f'📊 Prédire le jeu #{prochain_jeu}', data=bouton_secret)])
        except Exception as e:
            print(f"⚠️ Erreur Bot : {e}")

# ==========================================
# 5. TÊTE 2 : COMMANDES FINANCIÈRES & BOUTON
# ==========================================
@bot_officiel.on(events.NewMessage(pattern=r'^/capital\s+(\d+)'))
async def set_capital(event):
    montant = float(event.pattern_match.group(1))
    cursor.execute("UPDATE finances SET capital_depart = ?, capital_actuel = ? WHERE id = 1", (montant, montant))
    conn.commit()
    await event.reply(f"🏦 **Capital de départ enregistré :** {montant} FCFA.\nObjectif de gain : +20%. Limite de perte : -15%.")

@bot_officiel.on(events.NewMessage(pattern=r'^/solde\s+(\d+)'))
async def set_solde(event):
    nouveau_solde = float(event.pattern_match.group(1))
    cursor.execute("UPDATE finances SET capital_actuel = ? WHERE id = 1", (nouveau_solde,))
    conn.commit()
    
    cursor.execute("SELECT capital_depart FROM finances WHERE id = 1")
    depart = cursor.fetchone()[0]
    evolution = ((nouveau_solde - depart) / depart) * 100
    
    reponse = f"💼 **Nouveau solde :** {nouveau_solde} FCFA.\n📈 **Évolution :** {evolution:+.2f}%\n"
    
    if evolution <= -15.0:
        reponse += "\n🛑 **ALERTE STOP-LOSS !** Tu as perdu 15% de ton capital. Arrête de jouer immédiatement pour protéger ton portefeuille."
    elif evolution >= 20.0:
        reponse += "\n🎯 **TAKE-PROFIT ATTEINT !** Tu as gagné 20%. Retire tes gains de 1xBet tout de suite !"
        
    await event.reply(reponse)

@bot_officiel.on(events.NewMessage(pattern=r'^/bilan'))
async def export_bilan(event):
    cursor.execute("SELECT numero_jeu, gagnant FROM historique ORDER BY id ASC")
    donnees = cursor.fetchall()
    
    if not donnees:
        await event.reply("📂 La base de données est vide pour le moment.")
        return
        
    nom_fichier = "bilan_baccarat.csv"
    with open(nom_fichier, mode='w', newline='', encoding='utf-8') as fichier_csv:
        writer = csv.writer(fichier_csv)
        writer.writerow(['Numero_Jeu', 'Gagnant'])
        writer.writerows(donnees)
        
    await bot_officiel.send_file(event.chat_id, nom_fichier, caption="📊 Voici ton fichier Excel (CSV) récapitulatif !")
    os.remove(nom_fichier) # On nettoie le serveur après l'envoi

@bot_officiel.on(events.CallbackQuery(pattern=b'^analyse_'))
async def handler_bouton(event):
    global memoire_tendance
    await event.answer("Analyse en cours... ⏳")
    
    numero_cible = event.data.decode('utf-8').split('_')[1]
    COTE_MOYENNE = 1.90
    
    # Vérification des finances et du Stop-Loss
    cursor.execute("SELECT capital_depart, capital_actuel FROM finances WHERE id = 1")
    finances = cursor.fetchone()
    depart = finances[0]
    actuel = finances[1]
    evolution = ((actuel - depart) / depart) * 100
    
    if evolution <= -15.0:
        await bot_officiel.send_message(event.chat_id, "🛑 **ANALYSES BLOQUÉES.** Le Stop-Loss de -15% est atteint. Le bot te protège contre toi-même. Reviens demain et utilise `/capital` pour recommencer.", reply_to=event.message.id)
        return

    # LECTURE DE LA BASE DE DONNÉES
    cursor.execute("SELECT COUNT(*) FROM historique")
    total_parties = cursor.fetchone()[0]
    
    if total_parties > 10:
        cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🔴 BANQUE'")
        victoires_b = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM historique WHERE gagnant = '🔵 JOUEUR'")
        victoires_j = cursor.fetchone()[0]
        prob_banque = max((victoires_b / total_parties) * 100, 40.0)
        prob_joueur = max((victoires_j / total_parties) * 100, 40.0)
        texte_intelligence = f"Algorithme ajusté sur {total_parties} parties réelles."
    else:
        prob_banque = 45.86
        prob_joueur = 44.62
        texte_intelligence = "Utilisation des probabilités théoriques."

    serie = memoire_tendance.get("serie_en_cours", 0)
    dernier = memoire_tendance.get("dernier_gagnant", "Inconnu")
    
    if dernier == "🔴 BANQUE" and serie >= 3:
        prob_joueur += (serie * 1.5)
        prob_banque -= (serie * 1.5)
    elif dernier == "🔵 JOUEUR" and serie >= 3:
        prob_banque += (serie * 1.5)
        prob_joueur -= (serie * 1.5)

    victoires_banque_mc = 0
    victoires_joueur_mc = 0
    for _ in range(10000):
        tirage = random.uniform(0, 100)
        if tirage < prob_banque: victoires_banque_mc += 1
        elif tirage < (prob_banque + prob_joueur): victoires_joueur_mc += 1

    taux_banque = (victoires_banque_mc / 10000) * 100
    taux_joueur = (victoires_joueur_mc / 10000) * 100

    if taux_banque > taux_joueur:
        choix_final = "🔴 BANQUE"
        p_win = taux_banque / 100
    else:
        choix_final = "🔵 JOUEUR"
        p_win = taux_joueur / 100

    # CRITÈRE DE KELLY BASÉ SUR LE VRAI CAPITAL
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
    rapport += f"🧠 **MÉMOIRE** : _{texte_intelligence}_\n\n"
    rapport += "🎲 **SIMULATION MONTE-CARLO** :\n"
    rapport += f"• Victoire Banque : {taux_banque:.1f}%\n"
    rapport += f"• Victoire Joueur : {taux_joueur:.1f}%\n\n"
    rapport += f"💡 **LE CHOIX : {choix_final}**\n\n"
    rapport += "🛡️ **GESTION DU RISQUE (Kelly)** :\n"
    rapport += f"• Solde Déclaré : {actuel} FCFA\n"
    rapport += f"• {alerte_risque}"

    try:
        await bot_officiel.send_message(event.chat_id, rapport, reply_to=event.message.id)
    except Exception as e:
        print(f"Erreur d'envoi : {e}")

# ==========================================
# 6. LANCEMENT
# ==========================================
async def main():
    print("🤖 Démarrage de la Machine Hedge Fund...")
    await espion.start()
    await bot_officiel.start(bot_token=BOT_TOKEN)
    asyncio.create_task(start_dummy_server())
    print("🎧 Opérationnel. En attente des ordres du Général.")
    
    await asyncio.gather(
        espion.run_until_disconnected(),
        bot_officiel.run_until_disconnected()
    )

if __name__ == '__main__':
    asyncio.run(main())
