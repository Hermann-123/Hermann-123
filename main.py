import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

from app.core import settings, logger
import app.core as core_module
from app.models import MatchData, SportType
from app.services import DixonColesEngine, AIRiskManager, TicketFactory
from app.bot import bot, dp

soccer_engine = DixonColesEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

async def fetch_api_football_matches() -> list:
    # 🌟 LE SECRET EST ICI : On demande les 50 PROCHAINS matchs à venir, peu importe l'heure !
    url = "https://v3.football.api-sports.io/fixtures?next=50"
    headers = {"x-apisports-key": settings.API_KEY_FOOTBALL}
    matches = []
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=20.0)
            if response.status_code == 200:
                for f in response.json().get("response", []): 
                    fixture = f.get("fixture", {})
                    
                    # Plus besoin de filtrer l'heure, l'API "next=50" ne donne QUE des matchs non commencés
                    matches.append(MatchData(
                        match_id=str(fixture.get("id")),
                        sport=SportType.SOCCER,
                        league=f.get("league", {}).get("name", "League"),
                        match_date=datetime.now(),
                        home_team=f.get("teams", {}).get("home", {}).get("name", "Home"),
                        away_team=f.get("teams", {}).get("away", {}).get("name", "Away")
                    ))
    except Exception as e:
        logger.error(f"Erreur API : {e}")
        
    # 🛟 MODE SECOURS : Si l'API bug un jour, il t'enverra quand même des matchs de démonstration pour ne jamais te laisser face à un bot vide.
    if not matches:
        matches = [
            MatchData(match_id="secours_1", sport=SportType.SOCCER, league="Test Bot", match_date=datetime.now(), home_team="Real Madrid", away_team="Barcelone"),
            MatchData(match_id="secours_2", sport=SportType.SOCCER, league="Test Bot", match_date=datetime.now(), home_team="Arsenal", away_team="Chelsea")
        ]
        
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN ACTIF] Analyse des 50 prochains matchs en cours...")
    matches = await fetch_api_football_matches()
    evaluated = []
    
    for match in matches:
        sim = soccer_engine.simulate(match)
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(0.3)

    new_portfolio = ticket_factory.build_portfolio(evaluated)
    
    tickets_generes = 0
    for category, tickets in new_portfolio.items():
        if category not in core_module.CACHE_PORTFOLIO:
            core_module.CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            existing_ids = [t.match_id for t in core_module.CACHE_PORTFOLIO[category]]
            if new_ticket.match_id not in existing_ids:
                core_module.CACHE_PORTFOLIO[category].append(new_ticket)
                tickets_generes += 1
                
                # Envoi du signal un par un (comme l'ancien bot)
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.name}"
                    if alert_id not in core_module.SENT_ALERTS:
                        core_module.SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **NOUVEAU SIGNAL !**\n\n🎯 Catégorie : **{category.value}**\n\n👉 *Ouvre le bot principal pour obtenir ce ticket et son analyse !*"
                        try:
                            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                            await asyncio.sleep(1)
                        except: pass

    # Message de confirmation si des tickets ont été trouvés
    if tickets_generes > 0 and settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=f"✅ **MISE À JOUR TERMINÉE**\n{tickets_generes} nouveaux pronostics sont disponibles dans le bot !")
        except: pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 🟢 MESSAGE DE RÉASSURANCE IMMÉDIAT AU DÉMARRAGE
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text="🟢 **SERVEUR EN LIGNE !**\nLe bot est réveillé. L'IA scanne les 50 prochains matchs mondiaux...")
        except: pass

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=30)
    scheduler.start()
    
    # Lancement immédiat au démarrage
    asyncio.create_task(run_platform_pipeline())
    
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/")
async def health(): return {"status": "ONLINE - NEXT 50 MATCHES ACTIVE"}

if __name__ == "__main__":
    import os
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
