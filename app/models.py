from enum import Enum
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class SportType(Enum):
    SOCCER = "soccer"
    BASKETBALL = "basketball"
    TENNIS = "tennis"

class TicketCategory(Enum):
    ULTRA_SAFE = "Ultra Safe"
    SAFE = "Safe"
    VIP = "VIP"
    VALUE = "Value"

class MatchData(BaseModel):
    match_id: str
    sport: SportType
    league: str
    match_date: datetime
    home_team: str
    away_team: str
    home_odds: float
    draw_odds: Optional[float] = None
    away_odds: float

class SimulationResult(BaseModel):
    match_id: str
    proba_home: float
    proba_draw: float
    proba_away: float
    most_likely_score: str

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
    # 🧠 NOUVEAU : Statut et informations du message Telegram
    status: str = "PENDING"  # PENDING, WON, LOST
    telegram_msg_id: Optional[int] = None
    recommended_stake: float = 0.0
