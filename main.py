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
# 🟢 INTEGRATION DU MOTEUR 2 : AdversarialEngine
from app.services import DixonColesEngine, AdversarialEngine, TicketFactory
from app.bot import bot, dp

# Instanciation des services avec le Système à 2 Moteurs
soccer_engine = DixonColesEngine()   # Moteur 1 : Calculs statistiques bruts
ai_manager = AdversarialEngine()      # Moteur 2 : Auditeur & Chasseur de failles
ticket_factory = TicketFactory()      # Usine à coupons (Anti-doublons & Cotes filtrées)

# TA CLÉ THE ODDS API
API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"

async def fetch_real_odds_matches() -> list:
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h"
    matches = []
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                for m in data:
                    commence_time = m.get('commence_time', '')
                    if not commence_time.startswith(today_str):
                        continue
                        
                    if 'bookmakers' in m and len(m['bookmakers']) > 0:
                        cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                        home, away = m['home_team'], m['away_team']
                        
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
                            if len(matches) >= 100:
                                break
    except Exception as e:
        logger.error(f"Erreur API : {e}")
        
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Recherche de nouveaux combinés via le système à 2 Moteurs...")
    matches = await fetch_real_odds_matches()
    
    if not matches: 
        logger.warning("⚠️ Aucun match valide récupéré depuis l'API Odds.")
        return

    evaluated = []
    for match in matches:
        # ÉTape 1 : Simulation statistique par le Moteur 1
        sim = soccer_engine.simulate(match)
        
        # ÉTape 2 : Audit de sécurité & recherche de failles par le Moteur 2
        ai_report = await ai_manager.audit_and_refine(match, sim)
        
        if not ai_report.is_approved:
            logger.info(f"🚫 Match {match.home_team} vs {match.away_team} REJETÉ par Moteur 2 : {ai_report.justification}")
        else:
            logger.info(f"✅ Match {match.home_team} vs {match.away_team} VALIDÉ par Moteur 2")
            
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(0.3)

    # ÉTape 3 : Construction du portefeuille filtré (Anti-doublons inter-coupons)
    new_portfolio = ticket_factory.build_portfolio(evaluated)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    tickets_generes = 0
    
    for category, tickets in new_portfolio.items():
        if category not in core_module.CACHE_PORTFOLIO:
            core_module.CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            # 🛑 ANTI-SPAM : Clé unique par catégorie et par jour
            daily_alert_key = f"alert_{category.name}_{today_str}"
            
            if daily_alert_key not in core_module.SENT_ALERTS:
                core_module.CACHE_PORTFOLIO[category] = [new_ticket] # Mise en cache du meilleur ticket verrouillé
                core_module.SENT_ALERTS.add(daily_alert_key)
                tickets_generes += 1
                
                if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    titre_canal = "🌟 COMBINÉ DU JOUR" if category.name == "ULTRA_SAFE" else "💎 COMBINÉ VIP" if category.name == "VIP" else "🚀 VALUE BET"
                    alert_msg = f"🚨 **NOUVEAU {titre_canal} DÉTECTÉ ET ENREGISTRÉ !**\n\n📈 **Cote atteinte : {new_ticket.odds}**\n🎯 **Confiance validée par Moteur 2 : {new_ticket.ai_confidence}%**\n\n👉 *Ouvre le bot principal pour consulter ce ticket verrouillé pour aujourd'hui !*"
                    try:
                        await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Erreur d'envoi Telegram : {e}")

    if tickets_generes > 0 and settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=f"✅ {tickets_generes} nouveaux TICKETS ont été verrouillés. Fini le scan pour ces catégories aujourd'hui, bon gain !")
        except Exception as e:
            logger.error(f"Erreur notification finale Telegram : {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await bot.delete_webhook(drop_pending_updates=True)
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        try:
            await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text="🟢 **SERVEUR EN LIGNE !**\nSystème Anti-Spam & Analyse 2 Moteurs activés. L'IA verrouillera un seul ticket ultra-solide par catégorie par jour.")
        except: pass

    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=45) # Scan toutes les 45 mins
    scheduler.start()
    
    asyncio.create_task(run_platform_pipeline())
    bot_task = asyncio.create_task(dp.start_polling(bot))
    yield
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/")
async def health(): 
    return {"status": "ONLINE - SYSTEME 2 MOTEURS & ANTI-SPAM ACTIF"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), reload=False)
