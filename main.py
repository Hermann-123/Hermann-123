import asyncio
import os
import json
from playwright.async_api import async_playwright
from telegram import Bot

# Tes informations d'accès
TOKEN = "7432405570:AAGqkeFs72lzzVuW_Ea_N8kKLBXBCIc7bc4"
CHAT_ID = "5968288964"

# ==========================================
# LE FAUX SERVEUR WEB (Pour tromper Render)
# ==========================================
async def handle_client(reader, writer):
    # Quand Render vérifie si le site est en vie, on lui répond un simple "OK"
    response = 'HTTP/1.0 200 OK\n\nBot Telegram Actif !'
    writer.write(response.encode('utf8'))
    await writer.drain()
    writer.close()

async def start_dummy_server():
    # Render donne automatiquement un numéro de "PORT" secret
    port = int(os.environ.get('PORT', 10000))
    server = await asyncio.start_server(handle_client, '0.0.0.0', port)
    print(f"🌐 Faux serveur web démarré sur le port {port} (Render est content)")
    async with server:
        await server.serve_forever()

# ==========================================
# LE COEUR DU BOT (L'Aspirateur 1xBet)
# ==========================================
async def recuperer_scores_fifa():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        url = "https://1xbet.ci/service-api/LiveFeed/Get1x2_VZip?sports=40&count=50&mode=4&lng=fr"
        
        print("⚡️ Tentative d'accès aux scores FIFA...")
        try:
            await page.goto(url, wait_until="networkidle")
            content = await page.inner_text("body")
            data = json.loads(content)
            
            matchs = data.get("Value", [])
            resultats = []
            
            for m in matchs:
                equipe1 = m.get("O1E", "Equipe 1")
                equipe2 = m.get("O2E", "Equipe 2")
                score = f"{m.get('SC', {}).get('FS', {}).get('S1', 0)} - {m.get('SC', {}).get('FS', {}).get('S2', 0)}"
                resultats.append(f"🎮 {equipe1} {score} {equipe2}")
            
            await browser.close()
            return resultats
        except Exception as e:
            print(f"❌ Erreur d'extraction : {e}")
            await browser.close()
            return []

# ==========================================
# LANCEMENT PRINCIPAL
# ==========================================
async def main():
    # 1. On lance le faux serveur en arrière-plan
    asyncio.create_task(start_dummy_server())
    
    # 2. On lance le bot
    bot = Bot(token=TOKEN)
    print("🤖 Bot en ligne ! L'aspirateur démarre...")
    
    while True:
        scores = await recuperer_scores_fifa()
        
        if scores:
            message = "⚽️ **SCORES FIFA EN DIRECT** ⚽️\n\n" + "\n".join(scores)
            try:
                await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
                print("✅ Message envoyé sur Telegram !")
            except Exception as e:
                print(f"⚠️ Erreur Telegram : {e}")
        else:
            print("💤 Aucun match FIFA trouvé pour le moment.")
            
        # Attend 5 minutes (300 secondes) avant le prochain scan
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
    
