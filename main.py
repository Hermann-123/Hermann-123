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
from app.services import DixonColesEngine, BasketballEngine, TennisEngine, AIRiskManager, TicketFactory
from app.bot import bot, dp

soccer_engine = DixonColesEngine()
basket_engine = BasketballEngine()
tennis_engine = TennisEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

async def fetch_live_matches(sport_key: str, sport_type: SportType) -> list:
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={settings.API_KEY_ODDS}&regions=eu&markets=h2h"
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                # ⚠️ LE BRIDAGE A ÉTÉ ENLEVÉ ICI : Le bot scanne TOUS les matchs disponibles
                for m in response.json():
                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                        home, away = m['home_team'], m['away_team']
                        if home in cotes and away in cotes:
                            draw = cotes.get('Draw', None)
                            matches.append(MatchData(match_id=m['id'], sport=sport_type, league=m['sport_title'], match_date=datetime.now(), home_team=home, away_team=away, home_odds=cotes[home], draw_odds=draw, away_odds=cotes[away]))
    except Exception as e:
        logger.error(f"Erreur API ({sport_type.value}): {e}")
    return matches

async def run_platform_pipeline():
    logger.info("🔄 Démarrage du Scan Multi-Sports...")
    
    soccer_matches = await fetch_live_matches("soccer_epl", SportType.SOCCER)
    basket_matches = await fetch_live_matches("basketball_nba", SportType.BASKETBALL)
    tennis_matches = await fetch_live_matches("tennis_atp", SportType.TENNIS)
    
    all_matches = soccer_matches + basket_matches + tennis_matches
    
    evaluated = []
    for match in all_matches:
        if match.sport == SportType.SOCCER: sim = soccer_engine.simulate(match)
        elif match.sport == SportType.BASKETBALL: sim = basket_engine.simulate(match)
        elif match.sport == SportType.TENNIS: sim = tennis_engine.simulate(match)
            
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(2)

    core_module.CACHE_PORTFOLIO = ticket_factory.build_portfolio(evaluated)
    
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        for category, tickets in core_module.CACHE_PORTFOLIO.items():
            for ticket in tickets:
                msg = f"🗄️ **ARCHIVE | {category.value}**\n🏅 Sport: {ticket.sport.value.upper()}\n🏟️ Match: {ticket.match_title}\n🎯 Pari: `{ticket.bet_type}`\n📈 Cote: `{ticket.odds}`\n🤖 IA: {ticket.ai_justification}"
                try:
                    await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=msg)
                    await asyncio.sleep(1)
                except Exception as e:
                    pass

    logger.info("✅ Scan Multi-Sports et Archivage terminés !")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    # ⚠️ CHRONO RÉTABLI : Un nouveau scan complet toutes les 30 minutes
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
async def health(): return {"status": "ONLINE", "sports": "Foot, Basket, Tennis"}

if __name__ == "__main__":
    import os
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
