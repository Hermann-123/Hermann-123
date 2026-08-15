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

# IMPORTATION DU NOUVEAU PIPELINE QUANTITATIF
from app.services import pipeline
from app.bot import bot, dp

# 🔑 TES CLÉS API
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"
# Remplace ceci par ta clé API-Football (API-Sports)
API_KEY_FOOTBALL = "TA_CLE_API_FOOTBALL_ICI" 

# ============================================================
# MODULE DE RENSEIGNEMENT : API-FOOTBALL
# ============================================================
async def fetch_recent_stats(team_name: str, client: httpx.AsyncClient) -> tuple:
    """Cherche les 5 derniers matchs d'une équipe et renvoie (buts_marqués, buts_encaissés)"""
    default_stats = ([1.0]*5, [1.0]*5)
    
    if API_KEY_FOOTBALL == "TA_CLE_API_FOOTBALL_ICI":
        return default_stats

    headers = {"x-apisports-key": API_KEY_FOOTBALL}
    
    try:
        # 1. Trouver l'ID de l'équipe
        search_url = f"https://v3.football.api-sports.io/teams?search={team_name}"
        search_resp = await client.get(search_url, headers=headers, timeout=10.0)
        
        if search_resp.status_code == 200:
            search_data = search_resp.json()
            if not search_data.get('response'):
                return default_stats # Équipe non trouvée
                
            team_id = search_data['response'][0]['team']['id']
            
            # 2. Récupérer les 5 derniers matchs
            fixtures_url = f"https://v3.football.api-sports.io/fixtures?team={team_id}&last=5"
            fixtures_resp = await client.get(fixtures_url, headers=headers, timeout=10.0)
            
            if fixtures_resp.status_code == 200:
                fixtures_data = fixtures_resp.json()
                matches = fixtures_data.get('response', [])
                
                if not matches:
                    return default_stats
                    
                scores = []
                conceded = []
                
                for m in matches:
                    goals = m.get('goals', {})
                    home_goals = goals.get('home')
                    away_goals = goals.get('away')
                    
                    if home_goals is None or away_goals is None:
                        continue
                        
                    if str(m['teams']['home']['id']) == str(team_id):
                        scores.append(float(home_goals))
                        conceded.append(float(away_goals))
                    else:
                        scores.append(float(away_goals))
                        conceded.append(float(home_goals))
                
                # Si on a récupéré des stats, on les renvoie, sinon par défaut
                if scores and conceded:
                    return (scores, conceded)
                    
    except Exception as e:
        logger.warning(f"⚠️ Impossible de récupérer les stats de {team_name} : {e}")
        
    return default_stats

# ============================================================
# MODULE DE COLLECTE PRINCIPAL
# ============================================================
async def fetch_real_odds_matches() -> list:
    url_odds = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h,totals"
    matches_and_odds = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        async with httpx.AsyncClient() as client:
            # Récupération des cotes
            response = await client.get(url_odds, timeout=20.0)
            if response.status_code != 200:
                logger.error(f"❌ Erreur API Bookmaker : {response.status_code}")
                return []
                
            data = response.json()
            logger.info(f"✅ API Bookmaker connectée. {len(data)} matchs trouvés. Analyse en cours...")
            
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
                        
                        # 🧠 NOUVEAU : Récupération asynchrone des statistiques réelles
                        logger.info(f"📊 Extraction des stats pour : {home_team} vs {away_team}")
                        home_scores, home_conceded = await fetch_recent_stats(home_team, client)
                        away_scores, away_conceded = await fetch_recent_stats(away_team, client)
                        
                        # Respect des limites d'API
                        await asyncio.sleep(0.5)

                        match_data = MatchData(
                            match_id=m['id'], sport=SportType.SOCCER, league=m['sport_title'],
                            match_date=datetime.now(), home_team=home_team, away_team=away_team,
                            home_odds=bookmaker_odds["1"], draw_odds=bookmaker_odds["X"], away_odds=bookmaker_odds["2"],
                            # Intégration des performances récentes
                            home_recent_scores=home_scores, home_recent_conceded=home_conceded,
                            away_recent_scores=away_scores, away_recent_conceded=away_conceded
                        )
                        matches_and_odds.append((match_data, bookmaker_odds))
                        
    except Exception as e:
        logger.error(f"❌ Erreur critique connexion API : {e}")
        
    return matches_and_odds

# ============================================================
# L'ORCHESTRATEUR
# ============================================================
async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Lancement du Pipeline Quantitatif PRO (Cotes + Stats)...")
    
    matches_and_odds = await fetch_real_odds_matches()
    if not matches_and_odds: 
        logger.info("❌ Aucun match analysable n'a été trouvé.")
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
                        await asyncio.sleep(1)
                    except: pass

    if tickets_generes > 0:
        logger.info(f"✅ {tickets_generes} nouveaux TICKETS enregistrés dans le cache.")
    else:
        logger.info("⏳ Fin du scan : Aucun Edge détecté avec l'historique récent.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try: await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text="🟢 **WALLSTREET OS : MOTEUR STATISTIQUE EN LIGNE !**")
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

@app.get("/")
async def health(): return {"status": "ONLINE - DATA MINING ACTIF"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
