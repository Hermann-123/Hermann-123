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

# ⚠️ TRÈS IMPORTANT : Colle ta longue clé secrète (1BJW...) entre ces guillemets !
SESSION_STRING = "COLLE_TA_CLE_DE_SESSION_ICI"

CHAT_ID = 5968288964
CANAL_CIBLE = 'baccaratstat' # La cible russe officielle

# ==========================================
# 2. MÉMOIRE DU BOT
# ==========================================
memoire_tendance = {
    "dernier_gagnant": None,
    "serie_en_cours": 0
}

# Initialisation du client Telethon
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# ==========================================
# 3. LE FAUX SERVEUR WEB (Pour Render)
# ==========================================
async def handle_client(reader, writer):
    writer.write(b'HTTP/1.0 200 OK\r\n\r\nMachine de Guerre Baccarat Active !')
    await writer.drain()
    writer.close()

async def start_dummy_server():
    port = int(os.environ.get('PORT', 10000))
    server = await asyncio.start_server(handle_client, '0.0.0.0', port)
    print(f"🌐 Faux serveur OK sur le port {port}")
    async with server:
        await server.serve_forever()

# ==========================================
# 4. L'ESPION & L'ANALYSE EN DIRECT
# ==========================================
@client.on(events.NewMessage(chats=CANAL_CIBLE))
async def handler_baccarat(event):
    texte_recu = event.message.text
    print(f"📥 Nouveau tirage détecté : {texte_recu}")
    
    match = re.search(r'#N(\d+)\.\s*(\d+)\((.*?)\)\s*-\s*(?:▶️\s*)?(\d+)\((.*?)\)', texte_recu)
    
    if match:
        partie = match.group(1)
        score_joueur = int(match.group(2))
        cartes_joueur = match.group(3)
        score_banque = int(match.group(4))
        cartes_banque = match.group(5)

        # Détermination du gagnant
        if score_joueur > score_banque:
            gagnant_actuel = "🔵 JOUEUR"
        elif score_banque > score_joueur:
            gagnant_actuel = "🔴 BANQUE"
        else:
            gagnant_actuel = "🟢 ÉGALITÉ"

        # Mise à jour de la mémoire (Streak)
        global memoire_tendance
        if gagnant_actuel == memoire_tendance["dernier_gagnant"] and gagnant_actuel != "🟢 ÉGALITÉ":
            memoire_tendance["serie_en_cours"] += 1
        else:
            if gagnant_actuel != "🟢 ÉGALITÉ":
                memoire_tendance["dernier_gagnant"] = gagnant_actuel
                memoire_tendance["serie_en_cours"] = 1

        # Création du message d'alerte
        message = f"🎰 **BACCARAT - Partie #{partie}**\n\n"
        message += f"🔵 **Joueur :** {score_joueur}  *(Cartes: {cartes_joueur})*\n"
        message += f"🔴 **Banque :** {score_banque}  *(Cartes: {cartes_banque})*\n\n"
        message += f"🏆 **Résultat : {gagnant_actuel}**\n"

        if memoire_tendance["serie_en_cours"] >= 3:
            message += f"🔥 **SÉRIE EN COURS :** Le {gagnant_actuel} a gagné **{memoire_tendance['serie_en_cours']} fois** de suite !\n"

        # Calcul du prochain jeu pour tatouer le bouton
        prochain_jeu = int(partie) + 1
        bouton_secret = f"analyse_{prochain_jeu}".encode('utf-8')

        # Envoi sur Telegram avec le bouton tatoué
        try:
            await client.send_message(
                CHAT_ID, 
                message, 
                buttons=[Button.inline(f'📊 Prédire le jeu #{prochain_jeu}', data=bouton_secret)]
            )
        except Exception as e:
            print(f"⚠️ Erreur d'envoi : {e}")

# ==========================================
# 5. L'ALGORITHME DE PRÉDICTION (MONTE-CARLO & KELLY)
# ==========================================
@client.on(events.CallbackQuery(pattern=b'^analyse_'))
async def handler_bouton(event):
    global memoire_tendance
    
    # Extraction du numéro de jeu
    data_recue = event.data.decode('utf-8')
    numero_cible = data_recue.split('_')[1]
    
    # Paramètres financiers
    CAPITAL_ACTUEL = 10000  # Capital virtuel en FCFA
    COTE_MOYENNE = 1.90
    
    # 1. SIMULATION DE MONTE-CARLO
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

    # 2. CRITÈRE DE KELLY
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

    # 3. RÉDACTION DU RAPPORT
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
# 6. LANCEMENT PRINCIPAL
# ==========================================
async def main():
    print("🤖 Machine de Guerre Baccarat en ligne !")
    await client.start()
    asyncio.create_task(start_dummy_server())
    print(f"🎧 Écoute silencieuse du canal : {CANAL_CIBLE}...")
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
