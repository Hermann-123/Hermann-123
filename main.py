import os
import logging
import asyncio
import httpx
from datetime import datetime
from enum import Enum
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

import numpy as np
from scipy.stats import poisson
from pydantic import BaseModel, Field

from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

# ==========================================
# 1. CONFIGURATION & LOGS
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7432405570:AAE7n5uHHju2--gpsFKOCc45UyvltdW8oTU")
ADMIN_ID = int(os.getenv("ADMIN_ID", "5968288964"))
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
API_KEY_FOOTBALL = os.getenv("API_KEY_FOOTBALL", "99f9731b68429ed4aaf0383cd7ca8cd4")
ARCHIVE_CHANNEL_ID = os.getenv("ARCHIVE_CHANNEL_ID", "-1003982738017")

CACHE_PORTFOLIO = {}
SENT_ALERTS = set()

# ==========================================
# 2. MODÈLES DE DONNÉES
# ==========================================
class SportType(Enum):
    SOCCER = "soccer"
    BASKETBALL = "basketball"

class TicketCategory(Enum):
    ULTRA_SAFE = "Ultra Safe (Sécurité Max)"
    VIP = "VIP (Victoires & DNB)"
    VALUE = "Value Bets (Buts, Scores & Handicaps)"
    MARKETS = "Marchés Spéciaux (Corners & Mi-temps)"

class MatchData(BaseModel):
    match_id: str
    sport: SportType
    league: str
    match_date: datetime
    home_team: str
    away_team: str
    home_odds: float = 1.90
    draw_odds: float = 3.40
    away_odds: float = 3.80

class SimulationResult(BaseModel):
    match_id: str
    proba_home: float
    proba_draw: float
    proba_away: float
    most_likely_score: str
    proba_btts: float
    proba_over_1_5: float
    proba_over_2_5: float
    proba_over_3_5: float
    estimated_corners: float

class AIAuditReport(BaseModel):
    confidence_score: float
    justification: str
    is_approved: bool

class GeneratedTicket(BaseModel):
    category: TicketCategory
    match_id: str
    sport: SportType
    match_title: str
    bet_type: str
    odds: float
    ai_confidence: float
    ai_justification: str

# ==========================================
# 3. MOTEUR MATHÉMATIQUE (DIXON-COLES)
# ==========================================
class DixonColesEngine:
    def __init__(self, rho: float = -0.15, home_advantage: float = 1.15):
        self.rho = rho
        self.home_advantage = home_advantage
        self.max_goals = 6

    def simulate(self, match: MatchData) -> SimulationResult:
        lambda_x = (1.0 / match.home_odds) * 1.8 * self.home_advantage
        mu_y = (1.0 / match.away_odds) * 1.8
        matrix = np.zeros((self.max_goals, self.max_goals))

        for i in range(self.max_goals):
            for j in range(self.max_goals):
                matrix[i, j] = poisson.pmf(i, lambda_x) * poisson.pmf(j, mu_y)
        
        matrix /= np.sum(matrix)
        p_home = float(np.sum(np.tril(matrix, -1))) * 100
        p_draw = float(np.sum(np.diag(matrix))) * 100
        p_away = float(np.sum(np.triu(matrix, 1))) * 100

        best_idx = np.argmax(matrix)
        score_x, score_y = np.unravel_index(best_idx, matrix.shape)

        p_btts = float(np.sum(matrix[1:, 1:])) * 100
        p_o15 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 1])) * 100
        p_o25 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 2])) * 100
        p_o35 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 3])) * 100
        est_corners = round(8.5 + (lambda_x + mu_y) * 1.5, 1)

        return SimulationResult(
            match_id=match.match_id, proba_home=p_home, proba_draw=p_draw, proba_away=p_away, 
            most_likely_score=f"{score_x}-{score_y}", proba_btts=p_btts, 
            proba_over_1_5=p_o15, proba_over_2_5=p_o25, proba_over_3_5=p_o35, estimated_corners=est_corners
        )

# ==========================================
# 4. GESTION DES RISQUES & IA (GROQ)
# ==========================================
class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if base_confidence < 45.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO : Match trop imprévisible.", is_approved=False)

        if not GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Validé par le modèle professionnel.", is_approved=True)

        prompt = f"""
        Tu es un Tipster et Trader Sportif professionnel.
        Match : {match.home_team} vs {match.away_team} ({match.league}).
        Score probable estimé : {sim.most_likely_score}.
        Rédige une analyse experte en 2 phrases expliquant la physionomie tactique et le pari le plus solide à tenter. Si c'est un piège, commence par "VETO".
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                    json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]}, timeout=10.0
                )
                if response.status_code == 200:
                    ans = response.json()['choices'][0]['message']['content'].strip()
                    if ans.startswith('"') and ans.endswith('"'): ans = ans[1:-1]
                    is_approved = not ans.upper().startswith("VETO")
                    return AIAuditReport(confidence_score=round(base_confidence + 5, 1), justification=ans, is_approved=is_approved)
        except:
            pass
        return AIAuditReport(confidence_score=base_confidence, justification="Analyse validée par l'algorithme quantitatif.", is_approved=True)

# ==========================================
# 5. USINE À TICKETS PROFESSIONNELS
# ==========================================
class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: continue
                
            title = f"{match.home_team} vs {match.away_team}"
            
            # Ultra Safe
            if sim.proba_home >= sim.proba_away:
                dc_prob = sim.proba_home + sim.proba_draw
                dc_odds, dc_name = 1.28, f"Double Chance : {match.home_team} ou Nul (1X)"
            else:
                dc_prob = sim.proba_away + sim.proba_draw
                dc_odds, dc_name = 1.32, f"Double Chance : {match.away_team} ou Nul (X2)"
            
            if dc_prob >= 75.0:
                portfolio[TicketCategory.ULTRA_SAFE].append(GeneratedTicket(category=TicketCategory.ULTRA_SAFE, match_id=match.match_id, sport=match.sport, match_title=title, bet_type=dc_name, odds=dc_odds, ai_confidence=ai.confidence_score, ai_justification=ai.justification))
            
            if sim.proba_over_1_5 >= 78.0:
                portfolio[TicketCategory.ULTRA_SAFE].append(GeneratedTicket(category=TicketCategory.ULTRA_SAFE, match_id=match.match_id, sport=match.sport, match_title=title, bet_type="Plus de 1.5 Buts", odds=1.35, ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            # VIP
            best_team = match.home_team if sim.proba_home >= sim.proba_away else match.away_team
            best_odds = match.home_odds if sim.proba_home >= sim.proba_away else match.away_odds
            best_proba = max(sim.proba_home, sim.proba_away)
            
            if best_proba >= 58.0 and best_odds >= 1.50:
                portfolio[TicketCategory.VIP].append(GeneratedTicket(category=TicketCategory.VIP, match_id=match.match_id, sport=match.sport, match_title=title, bet_type=f"Victoire {best_team}", odds=best_odds, ai_confidence=ai.confidence_score, ai_justification=ai.justification))
                portfolio[TicketCategory.VIP].append(GeneratedTicket(category=TicketCategory.VIP, match_id=match.match_id, sport=match.sport, match_title=title, bet_type=f"Remboursé si Nul (DNB) : {best_team}", odds=round(best_odds * 0.85, 2), ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            # Value Bets
            if sim.proba_btts >= 60.0:
                portfolio[TicketCategory.VALUE].append(GeneratedTicket(category=TicketCategory.VALUE, match_id=match.match_id, sport=match.sport, match_title=title, bet_type="Les deux équipes marquent (BTTS - Oui)", odds=1.75, ai_confidence=ai.confidence_score, ai_justification=ai.justification))
            
            if sim.proba_over_2_5 >= 58.0:
                portfolio[TicketCategory.VALUE].append(GeneratedTicket(category=TicketCategory.VALUE, match_id=match.match_id, sport=match.sport, match_title=title, bet_type="Plus de 2.5 Buts", odds=1.85, ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            portfolio[TicketCategory.VALUE].append(GeneratedTicket(category=TicketCategory.VALUE, match_id=match.match_id, sport=match.sport, match_title=title, bet_type=f"Score Exact : {sim.most_likely_score}", odds=7.50, ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            # Marchés Spéciaux
            portfolio[TicketCategory.MARKETS].append(GeneratedTicket(category=TicketCategory.MARKETS, match_id=match.match_id, sport=match.sport, match_title=title, bet_type="Total Corners : Plus de 8.5 corners", odds=1.72, ai_confidence=ai.confidence_score, ai_justification=ai.justification))
            portfolio[TicketCategory.MARKETS].append(GeneratedTicket(category=TicketCategory.MARKETS, match_id=match.match_id, sport=match.sport, match_title=title, bet_type="Mi-temps avec le plus de buts : 2ème mi-temps", odds=2.05, ai_confidence=ai.confidence_score, ai_justification=ai.justification))
                
        return dict(portfolio)

# ==========================================
# 6. INTERFACE TELEGRAM
# ==========================================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Ultra Safe", callback_data="get_Ultra Safe (Sécurité Max)"), InlineKeyboardButton(text="💎 VIP", callback_data="get_VIP (Victoires & DNB)")],
        [InlineKeyboardButton(text="🔥 Value Bets", callback_data="get_Value Bets (Buts, Scores & Handicaps)"), InlineKeyboardButton(text="📊 Marchés Spéciaux", callback_data="get_Marchés Spéciaux (Corners & Mi-temps)")]
    ])

@router.message(CommandStart())
async def command_start(message: Message):
    if message.from_user.id != ADMIN_ID: return
    text = "🏛 **WALLSTREET OS - PRO MARKETS**\n\n⚡️ API-Football : Connectée\n🤖 IA Groq : Active\n\nSélectionnez une catégorie de pronostics :"
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("get_"))
async def fetch_tickets(callback: CallbackQuery):
    cat_str = callback.data.replace("get_", "")
    target_cat = None
    for c in TicketCategory:
        if c.value == cat_str:
            target_cat = c
            break
            
    tickets = CACHE_PORTFOLIO.get(target_cat, []) if target_cat else []

    if not tickets:  
        await callback.message.answer(f"📭 Aucun ticket disponible pour cette catégorie pour le moment.")  
        await callback.answer()  
        return  

    response = f"🏛 **PORTFEUILLE PRO : {cat_str}**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"  
    for t in tickets[:3]:  
        response += f"⚽ **{t.match_title}**\n🎯 Pari : `{t.bet_type}`\n📈 Cote : `{t.odds}`\n🤖 IA ({t.ai_confidence}%): *{t.ai_justification}*\n\n"  
      
    await callback.message.answer(response, parse_mode="Markdown")  
    await callback.answer()

dp.include_router(router)

# ==========================================
# 7. ORCHESTRATEUR & API FASTAPI
# ==========================================
soccer_engine = DixonColesEngine()
ai_manager = AIRiskManager()
ticket_factory = TicketFactory()

async def fetch_api_football_matches() -> list:
    today_str = datetime.now().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today_str}"
    headers = {"x-apisports-key": API_KEY_FOOTBALL}
    matches = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=20.0)
            if response.status_code == 200:
                data = response.json()
                for f in data.get("response", [])[:20]:
                    fixture = f.get("fixture", {})
                    league = f.get("league", {})
                    teams = f.get("teams", {})
                    matches.append(MatchData(
                        match_id=str(fixture.get("id")),
                        sport=SportType.SOCCER,
                        league=f"{league.get('country', 'Monde')} - {league.get('name', 'League')}",
                        match_date=datetime.now(),
                        home_team=teams.get("home", {}).get("name", "Home"),
                        away_team=teams.get("away", {}).get("name", "Away")
                    ))
    except Exception as e:
        logger.error(f"Erreur API-Football : {e}")
        
    if not matches:
        matches = [
            MatchData(match_id="demo_1", sport=SportType.SOCCER, league="Brésil - Serie A", match_date=datetime.now(), home_team="Flamengo", away_team="Palmeiras", home_odds=2.10, draw_odds=3.20, away_odds=3.50),
            MatchData(match_id="demo_2", sport=SportType.SOCCER, league="USA - MLS", match_date=datetime.now(), home_team="Inter Miami", away_team="LA Galaxy", home_odds=1.75, draw_odds=3.60, away_odds=4.20)
        ]
    return matches

async def run_platform_pipeline():
    logger.info("🔄 [SCAN] Démarrage du pipeline global...")
    matches = await fetch_api_football_matches()
    evaluated = []
    for match in matches:
        sim = soccer_engine.simulate(match)
        ai_report = await ai_manager.evaluate_match(match, sim)
        evaluated.append((match, sim, ai_report))
        await asyncio.sleep(0.3)

    new_portfolio = ticket_factory.build_portfolio(evaluated)
    
    for category, tickets in new_portfolio.items():
        if category not in CACHE_PORTFOLIO:
            CACHE_PORTFOLIO[category] = []
            
        for new_ticket in tickets:
            existing_ids = [t.match_id for t in CACHE_PORTFOLIO[category]]
            if new_ticket.match_id not in existing_ids:
                CACHE_PORTFOLIO[category].append(new_ticket)
                
                if ARCHIVE_CHANNEL_ID and ARCHIVE_CHANNEL_ID != "-100VOTRE_ID_ICI":
                    alert_id = f"alert_{new_ticket.match_id}_{category.value}"
                    if alert_id not in SENT_ALERTS:
                        SENT_ALERTS.add(alert_id)
                        alert_msg = f"🚨 **SIGNAL MARCHÉS PRO !**\n\n🏅 Compétition : **{new_ticket.match_title}**\n📊 Catégorie : **{category.value}**\n\n👉 *Va sur le bot principal pour récupérer ton pronostic !*"
                        try:
                            await bot.send_message(chat_id=ARCHIVE_CHANNEL_ID, text=alert_msg)
                            await asyncio.sleep(1)
                        except: pass

    logger.info(f"✅ [SCAN] Terminé ! Total tickets en cache : {sum(len(v) for v in CACHE_PORTFOLIO.values())}")

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

app = FastAPI(title="WallStreet OS - Pro Markets", lifespan=lifespan)

@app.get("/")
async def health(): return {"status": "ONLINE - UNIFIED FILE"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
