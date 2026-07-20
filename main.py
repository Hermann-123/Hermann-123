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

# Instanciation des services métiers
math_engine = DixonColesEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

async def fetch_live_matches():
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={settings.API_KEY_ODDS}&regions=eu&markets=h2h"
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                for m in response.json()[:10]:
                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                        home, away = m['home_team'], m['away_team']
                        if home in cotes and away in cotes and 'Draw' in cotes:
                            matches.append(MatchData(
                                match_id=m['id'], sport=SportType.SOCCER, league=m['sport_title'],
                                match_date=datetime.now(), home_team=home, away_team=away,
                                home_odds=cotes[home], draw_odds=cotes['Draw'], away_odds=cotes[away]
                            ))
    except Exception as e:
        logger.error(f"Erreur The Odds API: {e}")
    return matches

async def run_platform_pipeline():
    logger.info("🔄 Démarrage du Scan Institutionnel (Data + Maths + IA Groq)...")
    matches = await fetch_live_matches()
    
    evaluated = []
    for match in matches:
        sim = math_engine.simulate(match)
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(2) # Pause Groq

    # Mise à jour du cache global partagé
    core_module.CACHE_PORTFOLIO = ticket_factory.build_portfolio(evaluated)
    logger.info("✅ Portefeuilles mis à jour ! Filtre IA appliqué.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Démarrage des tâches de fond
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', hours=4)
    scheduler.start()
    asyncio.create_task(run_platform_pipeline())

    # Démarrage de Telegram
    bot_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("🚀 WallStreet OS est EN LIGNE.")
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS - AI Betting Platform", lifespan=lifespan)

@app.get("/")
async def health():
    return {"status": "ONLINE", "architecture": "Modulaire", "ai": "Groq Llama 3"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
