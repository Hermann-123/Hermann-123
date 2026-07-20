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
    most_likely_score: str = ""

class AIAuditReport(BaseModel):
    confidence_score: float
    justification: str
    is_approved: bool = True  # Le droit de veto de l'IA

class GeneratedTicket(BaseModel):
    category: TicketCategory
    match_id: str
    sport: SportType
    match_title: str
    bet_type: str
    odds: float
    ai_confidence: float
    ai_justification: str
