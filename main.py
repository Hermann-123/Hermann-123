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
from app.services import DixonColesEngine, BasketballEngine, AIRiskManager, TicketFactory
from app.bot import bot, dp

# Instanciation des services métiers
soccer_engine = DixonColesEngine()
basket_engine = BasketballEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

async def fetch_live_matches(sport_key: str, sport_type: SportType) -> list:
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={settings.API_KEY_ODDS}&regions=eu&markets=h2h"
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                for m in response.json()[:8]: # Scan limité pour la vitesse
                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                        home, away = m['home_team'], m['away_team']
                        if home in cotes and away in cotes:
                            draw_odds = cotes.get('Draw', None)
                            matches.append(MatchData(
                                match_id=m['id'], sport=sport_type, league=m['sport_title'],
                                match_date=datetime.now(), home_team=home, away_team=away,
                                home_odds=cotes[home], draw_odds=draw_odds, away_odds=cotes[away]
                            ))
    except Exception as e:
        logger.error(f"Erreur The Odds API ({sport_type.value}): {e}")
    return matches

async def run_platform_pipeline():
    logger.info("🔄 Démarrage du Scan Multi-Sports...")
    
    soccer_matches = await fetch_live_matches("soccer_epl", SportType.SOCCER)
    basket_matches = await fetch_live_matches("basketball_nba", SportType.BASKETBALL)
    all_matches = soccer_matches + basket_matches
    
    evaluated = []
    for match in all_matches:
        if match.sport == SportType.SOCCER:
            sim = soccer_engine.simulate(match)
        else:
            sim = basket_engine.simulate(match)
            
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(2) # Pause Groq

    # Construction des Portefeuilles
    core_module.CACHE_PORTFOLIO = ticket_factory.build_portfolio(evaluated)
    
    # 🗄️ ARCHIVAGE DANS LE CANAL TELEGRAM
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        for category, tickets in core_module.CACHE_PORTFOLIO.items():
            for ticket in tickets:
                message_text = (
                    f"🗄️ **ARCHIVE | {category.value}**\n"
                    f"🏅 Sport: {ticket.sport.value.upper()}\n"
                    f"⚽ Match: {ticket.match_title}\n"
                    f"🎯 Pari: `{ticket.bet_type}`\n"
                    f"📈 Cote: `{ticket.odds}`\n"
                    f"🤖 Avis IA: {ticket.ai_justification}"
                )
                try:
                    await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=message_text)
                    await asyncio.sleep(1) # Éviter le spam Telegram
                except Exception as e:
                    logger.error(f"Erreur envoi archive Telegram: {e}")

    logger.info("✅ Scan Multi-Sports et Archivage terminés !")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', hours=4)
    scheduler.start()
    
    asyncio.create_task(run_platform_pipeline())

    bot_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("🚀 WallStreet OS est EN LIGNE.")
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS - AI Betting Platform", lifespan=lifespan)

@app.get("/")
async def health():
    return {"status": "ONLINE", "architecture": "Multi-Sports (Foot & Basket)"}

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
