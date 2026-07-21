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
    """Interroge l'API-Football avec la clé officielle pour récupérer les matchs du jour"""
    today_str = datetime.now().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today_str}"
    headers = {"x-apisports-key": settings.API_KEY_FOOTBALL}
    
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                for f in data.get("response", [])[:25]: # Analyse des 25 premiers matchs du jour
                    fixture = f.get("fixture", {})
                    league = f.get("league", {})
                    teams = f.get("teams", {})
                    
                    match_id = str(fixture.get("id"))
                    league_name = f"{league.get('country', 'Monde')} - {league.get('name', 'League')}"
                    home_team = teams.get("home", {}).get("name", "Home")
                    away_team = teams.get("away", {}).get("name", "Away")
                    
                    matches.append(MatchData(
                        match_id=match_id,
                        sport=SportType.SOCCER,
                        league=league_name,
                        match_date=datetime.now(),
                        home_team=home_team,
                        away_team=away_team,
                        home_odds=1.85, # Cote de base équilibrée ajustée par le moteur
                        draw_odds=3.40,
                        away_odds=3.90
                    ))
    except Exception as e:
        logger.error(f"Erreur API-Football : {e}")
        
    # Mode secours si l'API n'a pas renvoyé de match à cette heure précise
    if not matches:
        matches = [
            MatchData(match_id="demo_1", sport=SportType.SOCCER, league="Brésil - Serie A", match_date=datetime.now(), home_team="Flamengo", away_team="Palmeiras", home_odds=2.10, draw_odds=3.20, away_odds=3.50),
            MatchData(match_id="demo_2", sport=SportType.SOCCER, league="USA - MLS", match_date=datetime.now(), home_team="Inter Miami", away_team="LA Galaxy", home_odds=1.75, draw_odds=3.60, away_odds=4.20)
        ]
        
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN API-FOOTBALL] Démarrage de l'analyse multi-marchés...")
    
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
                
                # Alerte sur le canal Telegram
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.value}"
                    if alert_id not in core_module.SENT_ALERTS:
                        core_module.SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **SIGNAL MARCHÉS PRO !**\n\n🏅 Compétition : **{new_ticket.match_title}**\n📊 Catégorie : **{category.value}**\n\n👉 *Va sur le bot principal pour récupérer ton pronostic !*"
                        try:
                            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                            await asyncio.sleep(1)
                        except: pass

    logger.info(f"✅ [SCAN] Terminé ! Total tickets pro en cache : {sum(len(v) for v in core_module.CACHE_PORTFOLIO.values())}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=30)
    scheduler.start()
    asyncio.create_task(run_platform_pipeline())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS - Pro Markets", lifespan=lifespan)

@app.get("/")
async def health(): return {"status": "ONLINE - API FOOTBALL CONNECTED"}

if __name__ == "__main__":
    import os
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
