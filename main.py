import asyncio
import httpx
import os
from datetime import datetime
from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

from app.core import settings, logger
import app.core as core_module
from app.models import MatchData, SportType

from app.services import pipeline
from app.bot import bot, dp

# 🔑 TA CLÉ THE ODDS (Laisse la tienne ici)
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"

async def fetch_real_odds_matches() -> list:
    url_odds = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h,totals"
    matches_and_odds = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url_odds, timeout=20.0)
            if response.status_code != 200:
                logger.error(f"❌ Erreur API Bookmaker : {response.status_code}")
                return []
                
            data = response.json()
            logger.info(f"✅ API Bookmaker connectée. {len(data)} matchs trouvés pour aujourd'hui.")
            
            for m in data:
                if not m.get('commence_time', '').startswith(today_str): 
                    continue
                    
                if 'bookmakers' in m and len(m['bookmakers']) > 0:
                    home_team, away_team = m['home_team'], m['away_team']
                    bookmaker_odds = {}
                    
                    for market in m['bookmakers'][0]['markets']:
                        m_key = market['key']
                        for outcome in market['outcomes']:
                            name = outcome['name']
                            price = outcome['price']
                            if m_key == 'h2h':
                                if name == home_team: bookmaker_odds["1"] = price
                                elif name == away_team: bookmaker_odds["2"] = price
                                elif name == 'Draw': bookmaker_odds["X"] = price
                            elif m_key == 'totals':
                                pt = outcome.get('point')
                                if name == 'Over' and pt == 1.5: bookmaker_odds["O1.5"] = price
                                if name == 'Over' and pt == 2.5: bookmaker_odds["O2.5"] = price
                                elif name == 'Under' and pt == 2.5: bookmaker_odds["U2.5"] = price

                    if "1" in bookmaker_odds and "X" in bookmaker_odds and "2" in bookmaker_odds:
                        match_data = MatchData(
                            match_id=m['id'], sport=SportType.SOCCER, league=m['sport_title'],
                            match_date=datetime.now(), home_team=home_team, away_team=away_team,
                            home_odds=bookmaker_odds["1"], draw_odds=bookmaker_odds["X"], away_odds=bookmaker_odds["2"]
                        )
                        matches_and_odds.append((match_data, bookmaker_odds))
                        
    except Exception as e:
        logger.error(f"❌ Erreur critique connexion API : {e}")
        
    return matches_and_odds

async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Lancement du Pipeline Quantitatif PRO...")
    
    matches_and_odds = await fetch_real_odds_matches()
    if not matches_and_odds: 
        logger.info("❌ Aucun match analysable n'a été trouvé à cette heure-ci.")
        return

    new_portfolio = await pipeline.build_daily_portfolio(matches_and_odds)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    tickets_generes = 0
    
    for category, tickets in new_portfolio.items():
        if category not in core_module.CACHE_PORTFOLIO: 
            core_module.CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            daily_alert_key = f"alert_{category.name}_{today_str}"
            
            if daily_alert_key not in core_module.SENT_ALERTS:
                core_module.CACHE_PORTFOLIO[category] = [new_ticket] 
                core_module.SENT_ALERTS.add(daily_alert_key)
                tickets_generes += 1
                
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_msg = f"🚨 **NOUVEAU TICKET VALUE BET !**\n\n📈 Cote : {new_ticket.odds}\n\n👉 *Ouvre le bot pour voir l'analyse.*"
                    try: 
                        await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                    except: pass

    if tickets_generes > 0:
        logger.info(f"✅ {tickets_generes} nouveaux TICKETS enregistrés.")
    else:
        logger.info("⏳ Fin du scan : L'IA a posé son VETO ou l'Edge était insuffisant.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logger.warning(f"⚠️ Impossible de supprimer le webhook (Ignoré)")

    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try: await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text="🟢 **MOTEUR EN LIGNE !**")
        except: pass

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=45) 
    scheduler.start()
    
    asyncio.create_task(run_platform_pipeline())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
