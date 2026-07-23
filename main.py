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
from app.services import DixonColesEngine, AIRiskManager, TicketFactory
from app.bot import bot, dp

soccer_engine = DixonColesEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

# 🔑 TA CLÉ POUR AVOIR LES VRAIES COTES EN DIRECT
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"

async def fetch_real_odds_matches() -> list:
    """Utilise The Odds API pour obtenir les matchs et les VRAIES cotes en une seule requête."""
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h"
    matches = []
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                # On prend les 40 prochains gros matchs
                for m in data[:40]:
                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                        home, away = m['home_team'], m['away_team']
                        
                        # Si les cotes existent, on crée le match avec ses vraies valeurs
                        if home in cotes and away in cotes and 'Draw' in cotes:
                            matches.append(MatchData(
                                match_id=m['id'],
                                sport=SportType.SOCCER,
                                league=m['sport_title'],
                                match_date=datetime.now(),
                                home_team=home,
                                away_team=away,
                                home_odds=cotes[home],
                                draw_odds=cotes['Draw'],
                                away_odds=cotes[away]
                            ))
    except Exception as e:
        logger.error(f"Erreur API Cotes : {e}")
        
    # MODE SECOURS (Pour garantir un ticket de test)
    if not matches:
        matches = [
            MatchData(match_id="test_1", sport=SportType.SOCCER, league="Test", match_date=datetime.now(), home_team="Real Madrid", away_team="Valence", home_odds=1.45, draw_odds=4.50, away_odds=6.50)
        ]
        
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Analyse des vraies cotes avec l'IA Groq...")
    matches = await fetch_real_odds_matches()
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
                
                # ENVOI SUR LE CANAL
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.name}"
                    if alert_id not in core_module.SENT_ALERTS:
                        core_module.SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **NOUVEAU SIGNAL RENTABLE !**\n\n🎯 Catégorie : **{category.value}**\n\n👉 *Ouvre le bot principal pour obtenir ce ticket et son analyse détaillée !*"
                        try:
                            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                            await asyncio.sleep(1)
                        except: pass

    # MESSAGE DE SYNTHÈSE
    if tickets_generes > 0 and settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=f"✅ {tickets_generes} nouveaux pronostics validés par l'IA viennent d'être ajoutés !")
        except: pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    
    # 🟢 LE BOT TE PARLE DIRECTEMENT AU DÉMARRAGE
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text="🟢 **SERVEUR EN LIGNE !**\nL'IA lit les vraies cotes du marché. Recherche de pépites en cours...")
        except: pass

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
async def health(): return {"status": "ONLINE - ODDS API (VRAIES COTES)"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
