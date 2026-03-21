import asyncio
import os
import re
import random
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession

# ==========================================
# 1. TES CLÉS SECRÈTES
# ==========================================
API_ID = 36539428
API_HASH = 'edf612a165870ac5932ba064c104d47a'

# Ta clé de session (L'ESPION invisible) :
SESSION_STRING = "1BJWap1sBu120WWNRfQ9M4dFus6LsgU1PdkO2z2zFerIePvUk67yz1c9bfGPQFvNY-6iteTFrjn0-Lt4md7kHEjeZkFsvPIaXifXk7KxHgSd7zKOMue8SvqSXxm5J8vAhDMXvAXO6PeaH1jDTqFj6iEnFoB-4CC2dBlDr8T6fxZCbvCdPWBRIlUWIed765ZWy4A8ACmHVMaN-Z810BXxV6DTRZB8a-y2DFgmpbAxF7PIYYcykD4oKayW9eilPAQzvDFl3ii0OYnWCPg9Ff6PqUc78vps-Znf9fLHq_QgcYxA7HAdT5BTv74pr6ZfDR9Jo0xgE2tBltMpvwzaVoT2prTAUg08DrsQ="

# Le TOKEN de ton vrai bot (Le PORTE-PAROLE) :
BOT_TOKEN = "7432405570:AAGqkeFs72lzzVuW_Ea_N8kKLBXBCIc7bc4"

CHAT_ID = 5968288964
CANAL_CIBLE = 'baccaratstat'

# ==========================================
# 2. MÉMOIRE GLOBALE
# ==========================================
memoire_tendance = {
    "dernier_gagnant": None,
    "serie_en_cours": 0
}

# Initialisation des DEUX têtes
espion = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
bot_officiel = TelegramClient(StringSession(""), API_ID, API_HASH)

# ==========================================
# 3. LE FAUX SERVEUR WEB (Pour Render)
# ==========================================
async def handle_client(reader, writer):
    writer.write(b'HTTP/1.0 200 OK\r\n\r\nMachine a 2 Tetes Active !')
    await writer.drain()
    writer.close()

async def start_dummy_server():
    port = int(os.environ.get('PORT', 10000))
    server = await asyncio.start_server(handle_client, '0.0.0.0', port)
    async with server:
        await server.serve_forever()

# ==========================================
# 4. TÊTE 1 : L'ESPION (Écoute le Russe)
# ==========================================
@espion.on(events.NewMessage(chats=CANAL_CIBLE))
async def handler_baccarat(event):
    texte_recu = event.message.text
    print(f"📥 Espion a détecté : {texte_recu}")
    
    match = re.search(r'#N(\d+)\.\s*(\d+)\((.*?)\)\s*-\s*(?:▶️\s*)?(\d+)\((.*?)\)', texte_recu)
    
    if match:
        partie = match.group(1)
        score_joueur = int(match.group(2))
        cartes_joueur = match.group(3)
        score_banque = int(match.group(4))
        cartes_banque = match.group(5)

        if score_joueur > score_banque:
            gagnant_actuel = "🔵 JOUEUR"
        elif score_banque > score_joueur:
            gagnant_actuel = "🔴 BANQUE"
        else:
            gagnant_actuel = "🟢 ÉGALITÉ"

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

        prochain_jeu = int(partie) + 1
        bouton_secret = f"analyse_{prochain_jeu}".encode('utf-8')

        # L'Espion donne l'ordre au Bot Officiel de t'envoyer le message !
        try:
            await bot_officiel.send_message(
                CHAT_ID, 
                message, 
                buttons=[Button.inline(f'📊 Prédire le jeu #{prochain_jeu}', data=bouton_secret)]
            )
        except Exception as e:
            print(f"⚠️ Erreur du Bot Officiel : {e}")

# ==========================================
# 5. TÊTE 2 : LE BOT OFFICIEL (Te répond quand tu cliques)
# ==========================================
@bot_officiel.on(events.CallbackQuery(pattern=b'^analyse_'))
async def handler_bouton(event):
    global memoire_tendance
    
    data_recue = event.data.decode('utf-8')
    numero_cible = data_recue.split('_')[1]
    
    CAPITAL_ACTUEL = 10000 
    COTE_MOYENNE = 1.90
    
    serie = memoire_tendance.get("serie_en_cours", 0)
    dernier = memoire_tendance.get("dernier_gagnant", "Inconnu")
    
    prob_banque = 45.86
    prob_joueur = 44.62
    
    if dernier == "🔴 BANQUE" and serie >= 3:
        prob_joueur += (serie * 1.5)
        prob_banque -= (serie * 1.5)
    elif dernier == "🔵 JOUEUR" and serie >= 3:
        prob_banque += (serie * 1.5)
        prob_joueur -= (serie * 1.5)

    victoires_banque = 0
    victoires_joueur = 0
    
    for _ in range(10000):
        tirage = random.uniform(0, 100)
        if tirage < prob_banque:
            victoires_banque += 1
        elif tirage < (prob_banque + prob_joueur):
            victoires_joueur += 1

    taux_banque = (victoires_banque / 10000) * 100
    taux_joueur = (victoires_joueur / 10000) * 100

    if taux_banque > taux_joueur:
        choix_final = "🔴 BANQUE"
        p_win = taux_banque / 100
    else:
        choix_final = "🔵 JOUEUR"
        p_win = taux_joueur / 100

    b = COTE_MOYENNE - 1.0 
    q = 1.0 - p_win         
    
    fraction_kelly = ( (p_win * b) - q ) / b
    fraction_kelly = fraction_kelly / 2 
    
    if fraction_kelly <= 0:
        alerte_risque = "🛑 RISQUE ÉLEVÉ : Ne joue pas ce tour."
    else:
        fraction_kelly = min(fraction_kelly, 0.05) 
        mise_conseillee = int(CAPITAL_ACTUEL * fraction_kelly)
        alerte_risque = f"✅ FEU VERT : Miser {mise_conseillee} FCFA"

    rapport = f"🎯 PRÉDICTION JEU #{numero_cible} 🎯\n\n"
    rapport += "🎲 SIMULATION MONTE-CARLO (10k) :\n"
    rapport += f"Victoire Banque : {taux_banque:.1f}%\n"
    rapport += f"Victoire Joueur : {taux_joueur:.1f}%\n\n"
    rapport += f"💡 LE CHOIX : {choix_final}\n\n"
    rapport += "🛡️ GESTION DU RISQUE (Kelly) :\n"
    rapport += f"Capital : {CAPITAL_ACTUEL} FCFA\n"
    rapport += f"{alerte_risque}"

    await event.answer(rapport, alert=True)

# ==========================================
# 6. LANCEMENT SYNCHRONISÉ
# ==========================================
async def main():
    print("🤖 Démarrage de la Machine à Deux Têtes...")
    await espion.start()
    await bot_officiel.start(bot_token=BOT_TOKEN)
    asyncio.create_task(start_dummy_server())
    print("🎧 Espion connecté. Bot Officiel prêt à transmettre.")
    
    await asyncio.gather(
        espion.run_until_disconnected(),
        bot_officiel.run_until_disconnected()
    )

if __name__ == '__main__':
    asyncio.run(main())
