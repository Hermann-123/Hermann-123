from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from typing import List, Optional

class SportType(str, Enum):
    SOCCER = "soccer"
    BASKETBALL = "basketball"
    TENNIS = "tennis"

class TicketCategory(str, Enum):
    ULTRA_SAFE = "ULTRA_SAFE"
    SAFE = "SAFE"
    VIP = "VIP"
    VALUE_BET = "VALUE_BET"
    NUL = "MATCH_NUL"

class TeamStats(BaseModel):
    xg_recent: float = Field(default=1.35, ge=0.0)
    injuries_count: int = Field(default=0, ge=0)

class MatchData(BaseModel):
    match_id: str
    sport: SportType
    league: str
    match_date: datetime
    home_team: str
    away_team: str
    home_odds: float = Field(..., gt=1.0)
    draw_odds: Optional[float] = None # Optionnel car pas de nul au Tennis/Basket
    away_odds: float = Field(..., gt=1.0)
    home_stats: TeamStats = Field(default_factory=TeamStats)
    away_stats: TeamStats = Field(default_factory=TeamStats)

class SimulationResult(BaseModel):
    match_id: str
    proba_home: float
    proba_draw: float
    proba_away: float
    proba_over_2_5: float = 0.0
    proba_under_3_5: float = 0.0
    proba_btts: float = 0.0
    most_likely_score: str = ""
    score_probability: float = 0.0

class AIAuditReport(BaseModel):
    confidence_score: float
    justification: str
    risk_flags: List[str]
    is_approved: bool = True # Le fameux "Droit de veto" de l'IA

class GeneratedTicket(BaseModel):
    category: TicketCategory
    match_id: str
    sport: SportType
    match_title: str
    bet_type: str
    odds: float
    recommended_stake_pct: float
    ai_confidence: float
    ai_justification: str
