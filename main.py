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
    today_str = datetime.now().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today_str}"
    headers = {"x-apisports-key": settings.API_KEY_FOOTBALL}
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=20.0)
            if response.status_code == 200:
                for f in response.json().get("response", [])[:20]:
                    matches.append(MatchData(
                        match_id=str(f.get("fixture", {}).get("id")),
                        sport=SportType.SOCCER,
                        league=f.get("league", {}).get("name", "League"),
                        match_date=datetime.now(),
                        home_team=f.get("teams", {}).get("home", {}).get("name", "Home"),
                        away_team=f.get("teams", {}).get("away", {}).get("name", "Away")
                    ))
    except Exception as e:
        logger.error(f"Erreur API : {e}")
        
    if not matches:
        matches = [MatchData(match_id="demo_1", sport=SportType.SOCCER, league="Demo", match_date=datetime.now(), home_team="Flamengo", away_team="Palmeiras")]
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN API] Démarrage...")
    matches = await fetch_api_football_matches()
    evaluated = []
    
    for match in matches:
        sim = soccer_engine.simulate(match)
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(0.3)

    new_portfolio = ticket_factory.build_portfolio(evaluated)
    
    for category, tickets in new_portfolio.items():
        if category not in core_module.CACHE_PORTFOLIO:
            core_module.CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            existing_ids = [t.match_id for t in core_module.CACHE_PORTFOLIO[category]]
            if new_ticket.match_id not in existing_ids:
                core_module.CACHE_PORTFOLIO[category].append(new_ticket)
                
                # Séquence exacte du bot : Le message t'indique d'aller dans le bot pour choisir la catégorie
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.name}"
                    if alert_id not in core_module.SENT_ALERTS:
                        core_module.SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **NOUVEAU SIGNAL DÉTECTÉ !**\n\n🎯 Catégorie : **{category.value}**\n\n👉 *Va dans le bot principal pour sélectionner la catégorie du signal et obtenir le pronostic !*"
                        try:
                            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                            await asyncio.sleep(1)
                        except: pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=30)
    scheduler.start()
    asyncio.create_task(run_platform_pipeline())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/")
async def health(): return {"status": "ONLINE"}

if __name__ == "__main__":
    import os
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
