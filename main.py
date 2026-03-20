import asyncio
from playwright.async_api import async_playwright
from telegram import Bot

# Tes informations d'accès
TOKEN = "7432405570:AAGqkeFs72lzzVuW_Ea_N8kKLBXBCIc7bc4"
CHAT_ID = "5968288964"

async def recuperer_scores_fifa():
    async with async_playwright() as p:
        # Lancement du navigateur invisible
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # On va sur la page API avec les bons paramètres
        url = "https://1xbet.ci/service-api/LiveFeed/Get1x2_VZip?sports=40&count=50&mode=4&lng=fr"
        
        print("⚡️ Tentative d'accès aux scores FIFA...")
        try:
            await page.goto(url, wait_until="networkidle")
            # On récupère le contenu de la page (JSON)
            content = await page.inner_text("body")
            import json
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
            print(f"Erreur : {e}")
            await browser.close()
            return []

async def main():
    bot = Bot(token=TOKEN)
    print("🤖 Bot en ligne sur Render...")
    
    while True:
        scores = await recuperer_scores_fifa()
        
        if scores:
            message = "⚽️ **SCORES FIFA EN DIRECT** ⚽️\n\n" + "\n".join(scores)
            await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
        
        # Attend 5 minutes avant la prochaine mise à jour pour ne pas être banni
        await asyncio.sleep(300)

if __name__ == "__main__":
    asyncio.run(main())
          
