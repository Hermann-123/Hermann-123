import logging
import os
import asyncio
from datetime import datetime
from enum import Enum
from typing import List, Dict, Tuple

import numpy as np
from scipy.stats import poisson

from pydantic import BaseModel, Field
from sqlalchemy import create_engine, String, Float, Integer, DateTime, ForeignKey, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

from fastapi import FastAPI
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from contextlib import asynccontextmanager

# ==========================================
# CONFIGURATION ET SÉCURITÉ
# ==========================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("WallStreet_OS")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7432405570:AAE9MLdu9A_rhqEwNa9bPjRWJ0BT2UsNqiA")
# Base de données SQLite pour un démarrage immédiat (à remplacer par Supabase/PostgreSQL en prod)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./wallstreet_bot.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ==========================================
# 1. SCHÉMAS (PYDANTIC) - Validation des données
# ==========================================
class TeamStats(BaseModel):
    xg_recent: float = Field(default=1.35, ge=0.0)
    injuries_count: int = Field(default=0, ge=0)
    defense_rating: float = Field(default=1.0)

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
    TOP_OPPORTUNITE = "TOP_OPPORTUNITE"

class GeneratedTicket(BaseModel):
    category: TicketCategory
    match_id: str
    match_title: str
    bet_type: str
    odds: float
    recommended_stake_pct: float
    ai_confidence: float
    ai_justification: str

class DailyPortfolio(BaseModel):
    date_generated: str
    tickets: Dict[TicketCategory, List[GeneratedTicket]]

class BetAllocation(BaseModel):
    is_value: bool
    expected_value: float
    kelly_stake_pct: float

class AIAuditReport(BaseModel):
    confidence_score: float
    justification: str
    risk_flags: List[str]

# ==========================================
# 2. BASE DE DONNÉES (SQLALCHEMY)
# ==========================================
class Base(DeclarativeBase):
    pass

class MatchEntity(Base):
    __tablename__ = "matches"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    league: Mapped[str] = mapped_column(String, index=True)
    match_date: Mapped[datetime] = mapped_column(DateTime)
    home_team: Mapped[str] = mapped_column(String)
    away_team: Mapped[str] = mapped_column(String)
    home_odds: Mapped[float] = mapped_column(Float)
    draw_odds: Mapped[float] = mapped_column(Float)
    away_odds: Mapped[float] = mapped_column(Float)

# Création des tables si elles n'existent pas
Base.metadata.create_all(bind=engine)

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
# 4. INTELLIGENCE ARTIFICIELLE ET GESTION DU RISQUE
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
        
        if b <= 0 or p <= 0:
            return BetAllocation(is_value=False, expected_value=0.0, kelly_stake_pct=0.0)

        f_star = (b * p - q) / b
        if f_star <= 0:
            return BetAllocation(is_value=False, expected_value=expected_value, kelly_stake_pct=0.0)

        raw_stake_pct = (f_star * 100.0) * self.fraction
        return BetAllocation(is_value=True, expected_value=round(expected_value, 3), kelly_stake_pct=round(min(raw_stake_pct, self.max_stake_limit), 2))

class ContextEvaluator:
    def __init__(self, use_llm_api: bool = False):
        self.use_llm_api = use_llm_api

    def evaluate(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        flags = []
        confidence_modifier = 0.0
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)

        if match.home_stats.injuries_count >= 3:
            flags.append("Alerte: Hécatombe infirmerie à domicile.")
            confidence_modifier -= 15.0
        elif match.away_stats.injuries_count >= 3:
            flags.append("Opportunité: L'équipe extérieure est décimée.")
            if sim.proba_home > 50: confidence_modifier += 10.0

        if sim.proba_draw > 30.0 and match.draw_odds > 3.20:
            flags.append("Impasse tactique validée par le facteur Rho.")
            confidence_modifier += 5.0

        final_confidence = max(0.0, min(100.0, base_confidence + confidence_modifier))
        justification = f"Audit complété. {' | '.join(flags) if flags else 'Analyse nominale.'}"

        return AIAuditReport(confidence_score=round(final_confidence, 1), justification=justification, risk_flags=flags)

# ==========================================
# 5. USINE À TICKETS (PORTFOLIO)
# ==========================================
from collections import defaultdict

class PortfolioFactory:
    def __init__(self, risk_manager: KellyRiskController):
        self.risk_manager = risk_manager

    def build_daily_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]) -> DailyPortfolio:
        portfolio_dict = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            title = f"{match.home_team} vs {match.away_team} ({match.league})"
            if ai.confidence_score < 40.0: continue

            # Valeur & Safe
            alloc_home = self.risk_manager.calculate_allocation(sim.proba_home, match.home_odds)
            if alloc_home.is_value and alloc_home.expected_value > 1.08:
                portfolio_dict[TicketCategory.VALUE_BET].append(self._create(TicketCategory.VALUE_BET, match, title, f"Victoire {match.home_team}", match.home_odds, alloc_home.kelly_stake_pct, ai))
            if sim.proba_home > 65.0 and ai.confidence_score > 75.0:
                cat = TicketCategory.ULTRA_SAFE if sim.proba_home > 75.0 else TicketCategory.SAFE
                portfolio_dict[cat].append(self._create(cat, match, title, f"Victoire {match.home_team}", match.home_odds, alloc_home.kelly_stake_pct, ai))

            # Nuls & Annexes
            alloc_draw = self.risk_manager.calculate_allocation(sim.proba_draw, match.draw_odds)
            if sim.proba_draw >= 30.0 and alloc_draw.is_value:
                portfolio_dict[TicketCategory.NUL].append(self._create(TicketCategory.NUL, match, title, "Match Nul", match.draw_odds, alloc_draw.kelly_stake_pct, ai))
            
            if sim.score_probability > 11.0:
                portfolio_dict[TicketCategory.SCORE_EXACT].append(self._create(TicketCategory.SCORE_EXACT, match, title, f"Score Exact : {sim.most_likely_score}", 6.50, 0.5, ai))

        return DailyPortfolio(date_generated=datetime.utcnow().isoformat(), tickets=dict(portfolio_dict))

    def _create(self, cat: TicketCategory, match: MatchData, title: str, bet: str, odds: float, stake: float, ai: AIAuditReport) -> GeneratedTicket:
        return GeneratedTicket(category=cat, match_id=match.match_id, match_title=title, bet_type=bet, odds=round(odds, 2), recommended_stake_pct=stake, ai_confidence=ai.confidence_score, ai_justification=ai.justification)

# ==========================================
# 6. INTERFACE TELEGRAM (AIOGRAM)
# ==========================================
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()

# Cache global simple pour la démo
CACHE_TICKETS = {}

def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟️ Voir les Tickets du Jour", callback_data="menu_tickets")],
        [InlineKeyboardButton(text="🏦 Ma Bankroll", callback_data="menu_bankroll")]
    ])

def categories_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛡️ Ultra Safe", callback_data="cat_ULTRA_SAFE"), InlineKeyboardButton(text="💎 VIP", callback_data="cat_VIP")],
        [InlineKeyboardButton(text="🔥 Value Bets", callback_data="cat_VALUE_BET"), InlineKeyboardButton(text="🔙 Menu", callback_data="menu_main")]
    ])

@router.message(CommandStart())
async def command_start(message: Message):
    await message.answer("🤖 **WallStreet Betting OS**\n\nPrêt à afficher les analyses.", reply_markup=main_menu_keyboard(), parse_mode="Markdown")

@router.callback_query(F.data == "menu_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text("Menu Principal :", reply_markup=main_menu_keyboard())

@router.callback_query(F.data == "menu_tickets")
async def show_categories(callback: CallbackQuery):
    await callback.message.edit_text("Sélectionnez la catégorie :", reply_markup=categories_keyboard())

@router.callback_query(F.data.startswith("cat_"))
async def fetch_tickets(callback: CallbackQuery):
    category = callback.data.replace("cat_", "")
    tickets = CACHE_TICKETS.get(TicketCategory(category), [])
    
    if not tickets:
        await callback.message.edit_text(f"📭 Aucun ticket validé pour **{category}** aujourd'hui.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Retour", callback_data="menu_tickets")]]))
        return

    # Affiche le premier ticket en mémoire
    t = tickets[0]
    msg = f"✅ **{category}**\n\n⚽ **{t.match_title}**\n🔹 Pari : {t.bet_type}\n📈 Cote : {t.odds}\n💰 Mise : {t.recommended_stake_pct}% Bankroll\n🧠 IA : {t.ai_confidence}/100\n\n👉 *{t.ai_justification}*"
    await callback.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Retour", callback_data="menu_tickets")]]), parse_mode="Markdown")

dp.include_router(router)

# ==========================================
# 7. ORCHESTRATEUR GLOBAL (FASTAPI & SCHEDULER)
# ==========================================
math_engine = DixonColesEngine()
ai_evaluator = ContextEvaluator()
risk_manager = KellyRiskController()
ticket_factory = PortfolioFactory(risk_manager)

def mock_data_ingestion() -> List[MatchData]:
    """Simulation de données pour déclencher l'algorithme."""
    return [
        MatchData(match_id="M_1001", league="Premier League", match_date=datetime.utcnow(), home_team="Arsenal", away_team="Chelsea", home_odds=1.60, draw_odds=4.00, away_odds=5.50)
    ]

async def run_daily_pipeline():
    global CACHE_TICKETS
    logger.info("Démarrage du Pipeline Quotidien...")
    matches = mock_data_ingestion()
    evaluated = []

    for match in matches:
        sim = math_engine.simulate(match)
        ai = ai_evaluator.evaluate(match, sim)
        evaluated.append((match, sim, ai))

    portfolio = ticket_factory.build_daily_portfolio(evaluated)
    CACHE_TICKETS = portfolio.tickets
    logger.info("Pipeline terminé. Cache mis à jour.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Lancement du Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_daily_pipeline, 'cron', hour=4, minute=0)
    scheduler.start()
    
    # Force un premier run au lancement
    asyncio.create_task(run_daily_pipeline())

    # 2. Lancement du Bot Telegram
    bot_task = asyncio.create_task(dp.start_polling(bot))
    logger.info("Système complet en ligne.")

    yield

    # 3. Arrêt propre
    scheduler.shutdown()
    bot_task.cancel()
    await bot.session.close()

app = FastAPI(title="WallStreet OS", lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "online"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
