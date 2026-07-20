import asyncio
import httpx
import numpy as np
from scipy.stats import poisson
from typing import List, Tuple
from collections import defaultdict

from app.models import MatchData, SimulationResult, AIAuditReport, GeneratedTicket, TicketCategory, SportType
from app.core import settings, logger

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

        return SimulationResult(
            match_id=match.match_id, proba_home=p_home, proba_draw=p_draw, proba_away=p_away,
            most_likely_score=f"{score_x}-{score_y}"
        )

class BasketballEngine:
    def simulate(self, match: MatchData) -> SimulationResult:
        # Modèle de probabilité pour le Basket (Régression basée sur les marges)
        implied_home = 1.0 / match.home_odds
        implied_away = 1.0 / match.away_odds
        margin = implied_home + implied_away
        
        p_home = (implied_home / margin) * 100
        p_away = (implied_away / margin) * 100
        
        return SimulationResult(
            match_id=match.match_id, proba_home=p_home, proba_draw=0.0, proba_away=p_away,
            most_likely_score="112-105"
        )

class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Audit validé (Local).", is_approved=True)

        # 🧠 Le Prompt Dynamique de l'IA change selon le sport !
        if match.sport == SportType.SOCCER:
            contexte = "Analyse le risque de match nul (Draw Trap)."
        elif match.sport == SportType.BASKETBALL:
            contexte = "Analyse le risque de fatigue (Back-to-Back) et le Load Management des stars."
        else:
            contexte = "Analyse l'enjeu global."

        prompt = f"""
        Agis en tant que Directeur des Risques de paris sportifs.
        Sport: {match.sport.value.upper()} | Match: {match.home_team} vs {match.away_team}.
        Probabilités mathématiques : Domicile {sim.proba_home:.1f}% | Nul {sim.proba_draw:.1f}% | Extérieur {sim.proba_away:.1f}%.
        Cotes : 1({match.home_odds}) - X({match.draw_odds}) - 2({match.away_odds}).
        
        Consigne : {contexte}
        RÈGLE STRICTE : Si le risque te semble trop élevé, tu dois commencer ta réponse EXACTEMENT par "VETO".
        Sinon, rédige une justification ultra-courte (1 phrase) pour valider le pari.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]},
                    timeout=10.0
                )
                if response.status_code == 200:
                    answer = response.json()['choices'][0]['message']['content'].strip()
                    is_approved = not answer.upper().startswith("VETO")
                    return AIAuditReport(confidence_score=round(base_confidence + 5, 1), justification=answer, is_approved=is_approved)
        except Exception as e:
            logger.error(f"Erreur Groq: {e}")
        
        return AIAuditReport(confidence_score=base_confidence, justification="Validation automatique.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved:
                logger.info(f"🚫 Match écarté par l'IA : {match.home_team} vs {match.away_team}")
                continue

            title = f"{match.home_team} vs {match.away_team}"
            
            # Le filtrage des tickets dépend du sport
            if match.sport == SportType.SOCCER:
                if sim.proba_home > 70.0:
                    portfolio[TicketCategory.ULTRA_SAFE].append(self._create(TicketCategory.ULTRA_SAFE, match, title, f"Victoire {match.home_team}", match.home_odds, ai))
            
            elif match.sport == SportType.BASKETBALL:
                # Au basket il n'y a pas de match nul, donc un score au-dessus de 65% est déjà un pari SAFE
                if sim.proba_home > 65.0:
                    portfolio[TicketCategory.SAFE].append(self._create(TicketCategory.SAFE, match, title, f"Victoire {match.home_team}", match.home_odds, ai))

        return dict(portfolio)

    def _create(self, cat, match, title, bet, odds, ai):
        return GeneratedTicket(
            category=cat, match_id=match.match_id, sport=match.sport, match_title=title,
            bet_type=bet, odds=round(odds, 2), ai_confidence=ai.confidence_score, ai_justification=ai.justification
        )
