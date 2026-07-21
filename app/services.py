import os
import asyncio
import httpx
from datetime import datetime
from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

from app.core import settings, logger, CACHE_PORTFOLIO, SENT_ALERTS
from app.models import MatchData, SportType
from app.services import DixonColesEngine, AIRiskManager, TicketFactory
from app.bot import bot, dp

soccer_engine = DixonColesEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

async def fetch_matches() -> list:
    today_str = datetime.now().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today_str}"
    headers = {"x-apisports-key": settings.API_KEY_FOOTBALL}
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=20.0)
            if response.status_code == 200:
                for f in response.json().get("response", [])[:20]:
                    teams = f.get("teams", {})
                    matches.append(MatchData(
                        match_id=str(f.get("fixture", {}).get("id")),
                        sport=SportType.SOCCER,
                        league=f.get("league", {}).get("name", "League"),
                        match_date=datetime.now(),
                        home_team=teams.get("home", {}).get("name", "Home"),
                        away_team=teams.get("away", {}).get("name", "Away")
                    ))
    except Exception as e:
        logger.error(f"Erreur API-Football : {e}")
        
    if not matches:
        matches = [MatchData(match_id="demo_1", sport=SportType.SOCCER, league="Brasileirao", match_date=datetime.now(), home_team="Flamengo", away_team="Palmeiras", home_odds=2.10, draw_odds=3.20, away_odds=3.50)]
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN API-FOOTBALL] Démarrage du pipeline global...")
    matches = await fetch_matches()
    evaluated = []
    
    for match in matches:
        sim = soccer_engine.simulate(match)
        best_bet = f"Victoire {match.home_team}" if sim.proba_home >= sim.proba_away else f"Victoire {match.away_team}"
        ai_report = await ai_manager.evaluate_match(match, sim, best_bet)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(0.5)

    new_portfolio = ticket_factory.build_portfolio(evaluated)
    
    for category, tickets in new_portfolio.items():
        if category not in CACHE_PORTFOLIO:
            CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            existing_ids = [t.match_id for t in CACHE_PORTFOLIO[category]]
            if new_ticket.match_id not in existing_ids:
                CACHE_PORTFOLIO[category].append(new_ticket)
                
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.name}"
                    if alert_id not in SENT_ALERTS:
                        SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **NOUVEAU SIGNAL DÉTECTÉ !**\n\n🎯 Catégorie : **{category.value}**\n\n👉 *Va sur le bot principal pour obtenir ton pronostic !*"
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
async def health(): return {"status": "ONLINE - CLEAN ARCHITECTURE"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
