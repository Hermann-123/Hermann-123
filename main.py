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
                for m in response.json():
                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                        home, away = m['home_team'], m['away_team']
                        if home in cotes and away in cotes:
                            draw = cotes.get('Draw', None)
                            matches.append(MatchData(match_id=m['id'], sport=sport_type, league=m['sport_title'], match_date=datetime.now(), home_team=home, away_team=away, home_odds=cotes[home], draw_odds=draw, away_odds=cotes[away]))
    except Exception as e: pass
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Démarrage du scan international multi-ligues...")
    
    # 🌍 ÉLARGISSEMENT : On scanne plusieurs championnats mondiaux actifs simultanément
    mls_matches = await fetch_live_matches("soccer_usa_mls", SportType.SOCCER)
    brazil_matches = await fetch_live_matches("soccer_brazil_campeonato", SportType.SOCCER)
    sweden_matches = await fetch_live_matches("soccer_sweden_allsvenskan", SportType.SOCCER)
    norway_matches = await fetch_live_matches("soccer_norway_eliteserien", SportType.SOCCER)
    
    all_matches = mls_matches + brazil_matches + sweden_matches + norway_matches
    
    evaluated = []
    for match in all_matches:
        sim = soccer_engine.simulate(match)
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(0.5)

    new_portfolio = ticket_factory.build_portfolio(evaluated)
    
    # Enregistrement intelligent dans la mémoire permanente du bot
    for category, tickets in new_portfolio.items():
        if category not in core_module.CACHE_PORTFOLIO:
            core_module.CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            existing_ids = [t.match_id for t in core_module.CACHE_PORTFOLIO[category]]
            if new_ticket.match_id not in existing_ids:
                core_module.CACHE_PORTFOLIO[category].append(new_ticket)
                
                # Envoi du signal d'alerte sur le canal
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.value}"
                    if alert_id not in core_module.SENT_ALERTS:
                        core_module.SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **SIGNAL HAUTE CONFIANCE !**\n\n🏅 Sport : **{new_ticket.sport.value.upper()}**\n📊 Catégorie : **{category.value}**\n\n👉 *Va sur le bot principal pour récupérer ce pronostic validé par l'IA !*"
                        try:
                            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                            await asyncio.sleep(1)
                        except: pass

    logger.info(f"✅ [SCAN] Terminé ! Total tickets de haute qualité en cache : {sum(len(v) for v in core_module.CACHE_PORTFOLIO.values())}")

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

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/")
async def health(): return {"status": "ONLINE"}

if __name__ == "__main__":
    import os
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
