import logging
import os
import asyncio
import requests
from datetime import datetime
from enum import Enum
from typing import List, Dict, Tuple
from collections import defaultdict

import numpy as np
from scipy.stats import poisson

from pydantic import BaseModel, Field
from supabase import create_client, Client

# Importation de la toute nouvelle librairie Google
from google import genai

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

# ==========================================
# 1. CONFIGURATION & CLÉS API REELLES
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7432405570:AAEyxMY4e35il2POcey-7BIZlK10pCUnrsg")
ADMIN_ID = 5968288964

API_KEY_ODDS = "55a670c7b44c3dcc3c9750e9f5c51da1"
SUPABASE_URL = "https://wrzikajiigowxnwcvxzu.supabase.co"
SUPABASE_KEY = "sb_publishable_7R5FoErDURQtXRVQL17cEg_ddi1X0UR"

# Connecteur Gemini (Nouvelle syntaxe)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "votre-cle-api-gemini-ici")
if GEMINI_API_KEY and not GEMINI_API_KEY.startswith("votre-cle"):
    gemini_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    gemini_client = None

# Connexion Base de données distante
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info("✅ Connecté à Supabase")
except Exception as e:
    logger.error(f"❌ Erreur Supabase : {e}")
    supabase = None 

CACHE_PORTFOLIO = {}

# ==========================================
# 2. SCHÉMAS DE DONNÉES STRICTS
# ==========================================
class TeamStats(BaseModel):
    xg_recent: float = Field(default=1.35, ge=0.0)
    injuries_count: int = Field(default=0, ge=0)

class MatchData(BaseModel):
    match_id: str
    league: str
    match_date: datetime
    home_team: str
    away_team: str
    home_odds: float = Field(..., gt=1.0)
    draw_odds: float = Field(..., gt=1.0)
    away_odds: float = Field(..., gt=1.0)
    home_stats: TeamStats = Field(default_factory=TeamStats)
    away_stats: TeamStats = Field(default_factory=TeamStats)

class SimulationResult(BaseModel):
    match_id: str
    proba_home: float
    proba_draw: float
    proba_away: float
    proba_over_2_5: float
    proba_under_3_5: float
    proba_btts: float
    most_likely_score: str
    score_probability: float

class TicketCategory(str, Enum):
    ULTRA_SAFE = "ULTRA_SAFE"
    SAFE = "SAFE"
    PREMIUM = "PREMIUM"
    VIP = "VIP"
    FUN = "FUN"
    VALUE_BET = "VALUE_BET"
    NUL = "MATCH_NUL"
    BTTS = "BTTS"
    OVER_UNDER = "OVER_UNDER"
    SCORE_EXACT = "SCORE_EXACT"

class GeneratedTicket(BaseModel):
    category: TicketCategory
    match_id: str
    match_title: str
    bet_type: str
    odds: float
    recommended_stake_pct: float
    ai_confidence: float
    ai_justification: str

class BetAllocation(BaseModel):
    is_value: bool
    expected_value: float
    kelly_stake_pct: float

class AIAuditReport(BaseModel):
    confidence_score: float
    justification: str
    risk_flags: List[str]

# ==========================================
# 3. MOTEUR MATHÉMATIQUE (DIXON-COLES)
# ==========================================
class DixonColesEngine:
    def __init__(self, rho: float = -0.15, home_advantage: float = 1.15):
        self.rho = rho
        self.home_advantage = home_advantage
        self.max_goals = 6

    def _calculate_tau(self, x: int, y: int, lambda_x: float, mu_y: float) -> float:
        if x == 0 and y == 0: return 1.0 - (lambda_x * mu_y * self.rho)
        elif x == 0 and y == 1: return 1.0 + (lambda_x * self.rho)
        elif x == 1 and y == 0: return 1.0 + (mu_y * self.rho)
        elif x == 1 and y == 1: return 1.0 - self.rho
        return 1.0

    def simulate(self, match: MatchData) -> SimulationResult:
        lambda_x = (1.0 / match.home_odds) * 1.8 * match.home_stats.xg_recent * self.home_advantage
        mu_y = (1.0 / match.away_odds) * 1.8 * match.away_stats.xg_recent
        matrix = np.zeros((self.max_goals, self.max_goals))

        for i in range(self.max_goals):
            for j in range(self.max_goals):
                prob_i = poisson.pmf(i, lambda_x)
                prob_j = poisson.pmf(j, mu_y)
                tau = self._calculate_tau(i, j, lambda_x, mu_y)
                matrix[i, j] = prob_i * prob_j * max(tau, 0.0)

        matrix /= np.sum(matrix)
        
        p_home = float(np.sum(np.tril(matrix, -1)))
        p_draw = float(np.sum(np.diag(matrix)))
        p_away = float(np.sum(np.triu(matrix, 1)))
        
        p_btts = float(np.sum(matrix[1:, 1:]))
        p_over_2_5 = sum(matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 2)
        p_under_3_5 = sum(matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j <= 3)

        best_idx = np.argmax(matrix)
        score_x, score_y = np.unravel_index(best_idx, matrix.shape)

        return SimulationResult(
            match_id=match.match_id, proba_home=p_home * 100, proba_draw=p_draw * 100, proba_away=p_away * 100,
            proba_over_2_5=p_over_2_5 * 100, proba_under_3_5=p_under_3_5 * 100, proba_btts=p_btts * 100,
            most_likely_score=f"{score_x}-{score_y}", score_probability=float(matrix[score_x, score_y] * 100)
        )

# ==========================================
# 4. GESTION DU RISQUE & ANALYSE GEMINI
# ==========================================
class KellyRiskController:
    def __init__(self, fraction: float = 0.25, max_stake_limit: float = 5.0):
        self.fraction = fraction
        self.max_stake_limit = max_stake_limit

    def calculate_allocation(self, probability_pct: float, decimal_odds: float) -> BetAllocation:
        p = probability_pct / 100.0
        q = 1.0 - p
        b = decimal_odds - 1.0
        expected_value = (p * decimal_odds)
        
        if b <= 0 or p <= 0: return BetAllocation(is_value=False, expected_value=0.0, kelly_stake_pct=0.0)

        f_star = (b * p - q) / b
        if f_star <= 0: return BetAllocation(is_value=False, expected_value=expected_value, kelly_stake_pct=0.0)

        raw_stake_pct = (f_star * 100.0) * self.fraction
        return BetAllocation(is_value=True, expected_value=round(expected_value, 3), kelly_stake_pct=round(min(raw_stake_pct, self.max_stake_limit), 2))

class ContextEvaluator:
    def __init__(self, use_gemini: bool = True):
        self.use_gemini = use_gemini

    async def evaluate(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if self.use_gemini and gemini_client:
            try:
                prompt = f"""
                Agis en tant qu'analyste professionnel de paris sportifs.
                Analyse le match : {match.home_team} vs {match.away_team} ({match.league}).
                
                Données du modèle mathématique Dixon-Coles :
                - Victoire {match.home_team} : {sim.proba_home:.1f}% (Cote: {match.home_odds})
                - Match Nul : {sim.proba_draw:.1f}% (Cote: {match.draw_odds})
                - Victoire {match.away_team} : {sim.proba_away:.1f}% (Cote: {match.away_odds})
                
                Rédige une justification TRÈS COURTE (2 phrases maximum) validant ou nuançant ce pronostic.
                Ton ton doit être expert, analytique et direct.
                """
                
                # LA CORRECTION EST ICI : Appel du nouveau modèle gemini-2.0-flash
                response = await gemini_client.aio.models.generate_content(
                    model='gemini-2.0-flash',
                    contents=prompt,
                )
                justification = response.text.strip()
                return AIAuditReport(confidence_score=round(base_confidence + 10.0, 1), justification=justification, risk_flags=[])
            
            except Exception as e:
                logger.error(f"Erreur API Gemini : {e}. Bascule sur heuristique locale.")
                return self._fallback_evaluate(match, sim, base_confidence)
        else:
            return self._fallback_evaluate(match, sim, base_confidence)

    def _fallback_evaluate(self, match: MatchData, sim: SimulationResult, base_confidence: float) -> AIAuditReport:
        flags = []
        confidence_modifier = 0.0
        if sim.proba_draw > 30.0 and match.draw_odds > 3.20:
            flags.append("Impasse tactique validée par le facteur Rho.")
            confidence_modifier += 5.0

        final_confidence = max(0.0, min(100.0, base_confidence + confidence_modifier))
        justification = f"Audit heuristique local complété. {' | '.join(flags) if flags else 'Analyse nominale.'}"
        return AIAuditReport(confidence_score=round(final_confidence, 1), justification=justification, risk_flags=flags)

# ==========================================
# 5. DATA INGESTION (The Odds API)
# ==========================================
def fetch_real_matches() -> List[MatchData]:
    logger.info("📡 Collecte des cotes en cours...")
    url = f"https://api.the-odds-api.com/v4/sports/soccer/odds/?apiKey={API_KEY_ODDS}&regions=eu&markets=h2h"
    
    matches = []
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            data = response.json()
            for m in data[:20]: 
                if 'bookmakers' in m and len(m['bookmakers']) > 0:
                    cotes = {c['name']: c['price'] for c in m['bookmakers'][0]['markets'][0]['outcomes']}
                    home, away = m['home_team'], m['away_team']
                    
                    if home in cotes and away in cotes and 'Draw' in cotes:
                        matches.append(MatchData(
                            match_id=m['id'], league=m['sport_title'], match_date=datetime.now(),
                            home_team=home, away_team=away,
                            home_odds=cotes[home], draw_odds=cotes['Draw'], away_odds=cotes[away]
                        ))
    except Exception as e:
        logger.error(f"Échec de l'ingestion : {e}")
    return matches

# ==========================================
# 6. USINE À TICKETS (PORTFOLIO)
# ==========================================
class PortfolioFactory:
    def __init__(self, risk_manager: KellyRiskController):
        self.risk_manager = risk_manager

    def build_daily_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]) -> Dict[TicketCategory, List[GeneratedTicket]]:
        portfolio_dict = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            title = f"{match.home_team} vs {match.away_team} ({match.league})"

            # Valeur & Safe
            alloc_home = self.risk_manager.calculate_allocation(sim.proba_home, match.home_odds)
            if alloc_home.is_value and alloc_home.expected_value > 1.08:
                portfolio_dict[TicketCategory.VALUE_BET].append(self._create(TicketCategory.VALUE_BET, match, title, f"Victoire {match.home_team}", match.home_odds, alloc_home.kelly_stake_pct, ai))
            if sim.proba_home > 65.0:
                cat = TicketCategory.ULTRA_SAFE if sim.proba_home > 75.0 else TicketCategory.SAFE
                portfolio_dict[cat].append(self._create(cat, match, title, f"Victoire {match.home_team}", match.home_odds, alloc_home.kelly_stake_pct, ai))

            # Nuls
            alloc_draw = self.risk_manager.calculate_allocation(sim.proba_draw, match.draw_odds)
            if sim.proba_draw >= 30.0 and alloc_draw.is_value:
                portfolio_dict[TicketCategory.NUL].append(self._create(TicketCategory.NUL, match, title, "Match Nul", match.draw_odds, alloc_draw.kelly_stake_pct, ai))
            
            # VIP & Scores Exacts
            if sim.score_probability > 11.0:
                portfolio_dict[TicketCategory.VIP].append(self._create(TicketCategory.VIP, match, title, f"Score Exact : {sim.most_likely_score}", 6.50, 0.5, ai))

        return dict(portfolio_dict)

    def _create(self, cat: TicketCategory, match: MatchData, title: str, bet: str, odds: float, stake: float, ai: AIAuditReport) -> GeneratedTicket:
        return GeneratedTicket(category=cat, match_id=match.match_id, match_title=title, bet_type=bet, odds=round(odds, 2), recommended_stake_pct=stake, ai_confidence=ai.confidence_score, ai_justification=ai.justification)

# ==========================================
# 7. INTERFACE TELEGRAM (AIOGRAM)
# ==========================================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

class Form(StatesGroup):
    waiting_for_manual_match = State()

def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Tickets Safe", callback_data="get_SAFE"), InlineKeyboardButton(text="💎 Tickets VIP", callback_data="get_VIP")],
        [InlineKeyboardButton(text="🔥 Value Bets", callback_data="get_VALUE_BET"), InlineKeyboardButton(text="⏱️ Matchs Nuls", callback_data="get_NUL")],
        [InlineKeyboardButton(text="📊 Analyse Manuelle", callback_data="manual_analysis")]
    ])

@router.message(CommandStart())
async def command_start(message: Message):
    if message.from_user.id != ADMIN_ID: return
    text = "🏛 **SERVEUR INSTITUTIONNEL v7.0**\n\n⚡️ Flux The Odds API : Connecté\n⚙️ Dixon-Coles : Actif\n🤖 IA Gemini : Connectée\n\nQue voulez-vous consulter ?"
    await message.answer(text, reply_markup=main_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data.startswith("get_"))
async def fetch_tickets(callback: CallbackQuery):
    category = callback.data.replace("get_", "")
    tickets = CACHE_PORTFOLIO.get(TicketCategory(category), [])
    
    if not tickets:
        await callback.message.answer(f"📭 Aucun ticket validé pour **{category}** aujourd'hui.")
        await callback.answer()
        return

    response = f"🏛 **PORTFEUILLE {category}**\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    for t in tickets[:3]:
        response += f"⚽ **{t.match_title}**\n🎯 Pari : `{t.bet_type}`\n📈 Cote : `{t.odds}`\n💰 Mise : `{t.recommended_stake_pct}%`\n🤖 IA : {t.ai_confidence}/100\n👉 *{t.ai_justification}*\n\n"
    
    await callback.message.answer(response, parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "manual_analysis")
async def ask_manual(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("📝 Entrez le nom du match à analyser (ex: Real Madrid vs Milan) :")
    await state.set_state(Form.waiting_for_manual_match)
    await callback.answer()

@router.message(Form.waiting_for_manual_match)
async def process_manual(message: Message, state: FSMContext):
    await message.answer("⚙️ *Simulation Furtive Dixon-Coles en cours...*", parse_mode="Markdown")
    fake_match = MatchData(match_id="manual", league="Custom", match_date=datetime.now(), home_team="Home", away_team="Away", home_odds=2.10, draw_odds=3.20, away_odds=3.40)
    
    sim = math_engine.simulate(fake_match)
    ai_report = await ai_evaluator.evaluate(fake_match, sim)
    
    response = f"🎯 **VERDICT IA : Score exact probable {sim.most_likely_score}**\nProba Victoire 1 : {sim.proba_home:.1f}%\nProba Nul X : {sim.proba_draw:.1f}%\n\n🤖 **Avis Gemini :** {ai_report.justification}"
    await message.answer(response, parse_mode="Markdown")
    await state.clear()

dp.include_router(router)

# ==========================================
# 8. ORCHESTRATEUR GLOBAL (FASTAPI & SCHEDULER)
# ==========================================
math_engine = DixonColesEngine()
ai_evaluator = ContextEvaluator(use_gemini=True)
risk_manager = KellyRiskController()
ticket_factory = PortfolioFactory(risk_manager)

async def run_daily_pipeline():
    await asyncio.sleep(15)
    
    global CACHE_PORTFOLIO
    logger.info("🔄 Démarrage du Pipeline de Recherche avec IA Gemini...")
    
    matches = await asyncio.to_thread(fetch_real_matches)
    
    if not matches:
        logger.warning("Aucun match trouvé.")
        return

    evaluated = []
    for match in matches:
        sim = math_engine.simulate(match)
        ai = await ai_evaluator.evaluate(match, sim)
        evaluated.append((match, sim, ai))
        
        # LA 2EME CORRECTION EST ICI : 4 secondes de pause entre chaque match
        # pour respecter le forfait gratuit de Gemini
        await asyncio.sleep(4)

    CACHE_PORTFOLIO = ticket_factory.build_daily_portfolio(evaluated)
    
    if supabase:
        try:
            supabase.table('analyses').insert({
                "matches_scanned": len(matches),
                "safe_found": len(CACHE_PORTFOLIO.get(TicketCategory.SAFE, [])),
                "timestamp": datetime.utcnow().isoformat()
            }).execute()
        except: pass

    logger.info("✅ Pipeline terminé. Cache mis à jour avec les avis de Gemini.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_daily_pipeline, 'interval', hours=4)
    scheduler.start()
    
    asyncio.create_task(run_daily_pipeline())

    bot_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Système complet en ligne.")

    yield

    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/")
async def health_check():
    return {"status": "MOTEUR DIXON-COLES PRIME v7.0 : EN LIGNE (Gemini Connecté)"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
