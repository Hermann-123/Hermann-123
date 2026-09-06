import asyncio
import httpx
import os
from datetime import datetime, timezone  # 🟢 IMPORT CORRIGÉ : timezone est présent
from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

from app.core import settings, logger
import app.core as core_module
from app.models import MatchData, SportType
from app.services import DixonColesEngine, AdversarialEngine, TicketFactory
from app.bot import bot, dp

# Instanciation des services
soccer_engine = DixonColesEngine()
ai_manager = AdversarialEngine()
ticket_factory = TicketFactory()

API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"

async def fetch_real_odds_matches() -> list:
    url = f"https://api.the-odds-api.com/v4/sports/upcoming/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h"
    matches = []
    
    now_utc = datetime.now(timezone.utc)
    today_date_str = now_utc.strftime("%Y-%m-%d")
    logger.info(f"📅 [FILTRE TEMPOREL] Heure UTC : {now_utc.strftime('%Y-%m-%d %H:%M:%S')} | Recherche des matchs futurs du jour : {today_date_str}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=20.0)
            logger.info(f"📡 Réponse API Odds Code : {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📊 Événements bruts reçus : {len(data)}")
                
                for m in data:
                    sport_key = m.get('sport_key', '')
                    if not sport_key.startswith('soccer'):
                        continue
                    
                    commence_time_str = m.get('commence_time', '')
                    if not commence_time_str:
                        continue

                    try:
                        match_datetime = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
                    except Exception:
                        continue
                        
                    # 🛑 FILTRE 1 : Le match doit avoir lieu aujourd'hui
                    if not commence_time_str.startswith(today_date_str):
                        continue

                    # 🛑 FILTRE 2 : Le match ne doit PAS être déjà commencé ou passé
                    if match_datetime <= now_utc:
                        continue

                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        for bm in m['bookmakers']:
                            if 'markets' in bm and len(bm['markets']) > 0:
                                outcomes = bm['markets'][0].get('outcomes', [])
                                cotes = {c['name']: c['price'] for c in outcomes}
                                home, away = m.get('home_team'), m.get('away_team')
                                
                                if home in cotes and away in cotes and 'Draw' in cotes:
                                    matches.append(MatchData(
                                        match_id=m['id'],
                                        sport=SportType.SOCCER,
                                        league=m.get('sport_title', 'Football'),
                                        match_date=match_datetime,
                                        home_team=home,
                                        away_team=away,
                                        home_odds=float(cotes[home]),
                                        draw_odds=float(cotes['Draw']),
                                        away_odds=float(cotes['Away'])
                                    ))
                                    break 
                                    
                    if len(matches) >= 100:
                        break
            else:
                logger.error(f"❌ Erreur API Odds ({response.status_code}) : {response.text}")
    except Exception as e:
        logger.error(f"❌ Exception lors de la requête API Odds : {e}")
        
    logger.info(f"⚽ Matchs futurs retenus pour aujourd'hui : {len(matches)}")
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Lancement du pipeline d'analyse...")
    
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    
    # Purge automatique des clés périmées des jours précédents
    anciens_elements = [k for k in core_module.SENT_ALERTS if not k.endswith(today_str)]
    for k in anciens_elements:
        core_module.SENT_ALERTS.remove(k)

    matches = await fetch_real_odds_matches()
    
    if not matches: 
        logger.warning("⚠️ Aucun match valide à venir trouvé pour le reste de la journée.")
        return

    evaluated = []
    for match in matches:
        sim = soccer_engine.simulate(match)
        ai_report = await ai_manager.audit_and_refine(match, sim)
        
        if ai_report.is_approved:
            logger.info(f"✅ Match {match.home_team} vs {match.away_team} VALIDÉ")
            evaluated.append((match, sim, ai_report))
        else:
            logger.info(f"🚫 Match {match.home_team} vs {match.away_team} REJETÉ par Moteur 2")
            
        await asyncio.sleep(0.3)

    new_portfolio = ticket_factory.build_portfolio(evaluated)
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
                    titre_canal = "🌟 COMBINÉ DU JOUR" if category.name == "ULTRA_SAFE" else "💎 COMBINÉ VIP" if category.name == "VIP" else "🚀 VALUE BET"
                    alert_msg = f"🚨 **NOUVEAU {titre_canal} !**\n\n📈 **Cote totale : {new_ticket.odds}**\n🎯 **Confiance de l'IA : {new_ticket.ai_confidence}%**\n\nConsultez vos pronostics pour aujourd'hui !"
                    try:
                        await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Erreur envoi Telegram : {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text="🟢 **SERVEUR EN LIGNE !**\nLancement de l'analyse immédiate des matchs de la journée...")
        except Exception:
            pass

    # 🚀 Lancement du premier scan immédiatement au démarrage du serveur
    asyncio.create_task(run_platform_pipeline())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=10) # Reprise des scans toutes les 10 mins
    scheduler.start()
    
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/")
async def health(): 
    return {"status": "ONLINE"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
