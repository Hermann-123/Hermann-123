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

# --- 1. FONCTION DE SCAN DES COTES (Création des Signaux) ---
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
    logger.info("🔄 [SCAN] Démarrage de la recherche d'opportunités...")
    
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
    
    # 🚨 ENVOI DU SIGNAL (L'Appât)
    if settings.ARCHIVE_CHANNEL_ID and settings.ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
        for category, tickets in core_module.CACHE_PORTFOLIO.items():
            for ticket in tickets:
                alert_id = f"alert_{ticket.match_id}"
                if alert_id not in core_module.SENT_ALERTS:
                    core_module.SENT_ALERTS.add(alert_id)
                    alert_msg = f"🚨 **NOUVEAU SIGNAL DÉTECTÉ !**\n\n🏅 Sport : **{ticket.sport.value.upper()}**\n📊 Catégorie : **{category.value}**\n\n👉 *Allez sur le bot principal et cliquez sur la catégorie pour obtenir le pronostic.*"
                    try:
                        await bot.send_message(chat_id=settings.ARCHIVE_CHANNEL_ID, text=alert_msg)
                        await asyncio.sleep(1)
                    except: pass
    logger.info("✅ [SCAN] Terminé !")

# --- 2. FONCTION DE VÉRIFICATION DES SCORES (Le Juge) ---
async def check_match_results():
    if not core_module.PENDING_TICKETS: return
    logger.info("⚖️ [JUGE] Vérification des résultats en cours...")
    
    # On télécharge les scores terminés des 3 derniers jours via The Odds API
    url = f"https://api.the-odds-api.com/v4/sports/soccer_epl/scores/?apiKey={settings.API_KEY_ODDS}&daysFrom=3"
    # Note : Pour le prototype, on fait le test sur le foot. En production complète, il faudrait boucler sur chaque sport.
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=15.0)
            if response.status_code == 200:
                finished_matches = {m['id']: m for m in response.json() if m['completed']}
                
                # On regarde nos tickets en attente
                tickets_to_remove = []
                for match_id, ticket in core_module.PENDING_TICKETS.items():
                    if match_id in finished_matches:
                        match_data = finished_matches[match_id]
                        scores = match_data.get('scores', [])
                        
                        if len(scores) >= 2:
                            # Analyse basique du résultat
                            home_score = int(scores[0]['score'])
                            away_score = int(scores[1]['score'])
                            
                            is_won = False
                            if "Victoire" in ticket.bet_type and ticket.home_team in ticket.bet_type and home_score > away_score:
                                is_won = True
                            elif "Victoire" in ticket.bet_type and ticket.away_team in ticket.bet_type and away_score > home_score:
                                is_won = True
                            # Ajouter d'autres règles selon les types de paris...
                            
                            # Mise à jour du message Telegram
                            if ticket.telegram_msg_id and settings.ARCHIVE_CHANNEL_ID:
                                ticket.status = "WON" if is_won else "LOST"
                                profit = (ticket.recommended_stake * ticket.odds) - ticket.recommended_stake if is_won else -ticket.recommended_stake
                                
                                emoji = "✅ **GAGNÉ**" if is_won else "❌ **PERDU**"
                                profit_text = f"+{profit:.2f}€ 📈" if is_won else f"{profit:.2f}€ 📉"
                                
                                new_text = f"🗄️ **TICKET OFFICIEL | {ticket.category.value}**\n🏅 Sport: {ticket.sport.value.upper()}\n🏟️ Match: {ticket.match_title}\n🎯 Pari: `{ticket.bet_type}`\n📈 Cote: `{ticket.odds}`\n💰 Mise Validée: `{ticket.recommended_stake}€`\n\n{emoji} | Profit: **{profit_text}**\n*(Score final: {home_score} - {away_score})*"
                                
                                try:
                                    await bot.edit_message_text(chat_id=settings.ARCHIVE_CHANNEL_ID, message_id=ticket.telegram_msg_id, text=new_text)
                                except: pass
                            
                            tickets_to_remove.append(match_id)
                
                # Nettoyage de la mémoire
                for mid in tickets_to_remove:
                    del core_module.PENDING_TICKETS[mid]
                    
    except Exception as e:
        logger.error(f"Erreur Vérification Score : {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_platform_pipeline, 'interval', minutes=30)
    scheduler.add_job(check_match_results, 'interval', hours=1) # Vérifie les scores toutes les heures
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
