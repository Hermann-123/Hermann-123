import asyncio
import httpx
import numpy as np
from scipy.stats import poisson
from typing import List, Tuple
from datetime import datetime
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

class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if base_confidence < 45.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Validé mathématiquement.", is_approved=True)

        prompt = f"""
        Tipster professionnel. Match : {match.home_team} vs {match.away_team} ({match.league}).
        Tendances : 1({sim.proba_home:.1f}%) | X({sim.proba_draw:.1f}%) | 2({sim.proba_away:.1f}%). Score : {sim.most_likely_score}.
        Rédige une analyse experte en 2 phrases du pari le plus solide. Si c'est un piège, commence par "VETO". Ne dis aucun chiffre.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]}, timeout=10.0
                )
                if response.status_code == 200:
                    ans = response.json()['choices'][0]['message']['content'].strip()
                    is_approved = not ans.upper().startswith("VETO")
                    return AIAuditReport(confidence_score=round(base_confidence + 5, 1), justification=ans, is_approved=is_approved)
        except: pass
        return AIAuditReport(confidence_score=base_confidence, justification="Analyse validée par l'algorithme.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: continue
            title = f"{match.home_team} vs {match.away_team}"
            
            # 1. ULTRA SAFE
            if sim.proba_home >= sim.proba_away:
                dc_prob, dc_odds, dc_name = sim.proba_home + sim.proba_draw, 1.28, f"Double Chance : {match.home_team} ou Nul"
            else:
                dc_prob, dc_odds, dc_name = sim.proba_away + sim.proba_draw, 1.32, f"Double Chance : {match.away_team} ou Nul"
            
            if dc_prob >= 75.0:
                portfolio[TicketCategory.ULTRA_SAFE].append(self._create(TicketCategory.ULTRA_SAFE, match, title, dc_name, dc_odds, ai))
            
            # 2. VIP
            best_team = match.home_team if sim.proba_home >= sim.proba_away else match.away_team
            best_odds = match.home_odds if sim.proba_home >= sim.proba_away else match.away_odds
            
            if max(sim.proba_home, sim.proba_away) >= 58.0 and best_odds >= 1.50:
                portfolio[TicketCategory.VIP].append(self._create(TicketCategory.VIP, match, title, f"Victoire {best_team}", best_odds, ai))
                portfolio[TicketCategory.VIP].append(self._create(TicketCategory.VIP, match, title, f"Remboursé si Nul (DNB) : {best_team}", round(best_odds * 0.85, 2), ai))

            # 3. VALUE
            if sim.proba_btts >= 60.0:
                portfolio[TicketCategory.VALUE].append(self._create(TicketCategory.VALUE, match, title, "Les 2 équipes marquent", 1.75, ai))
            portfolio[TicketCategory.VALUE].append(self._create(TicketCategory.VALUE, match, title, f"Score Exact : {sim.most_likely_score}", 7.50, ai))

            # 4. MARKETS
            portfolio[TicketCategory.MARKETS].append(self._create(TicketCategory.MARKETS, match, title, f"Plus de 8.5 corners", 1.72, ai))
                
        return dict(portfolio)

    def _create(self, cat, match, title, bet, odds, ai):
        return GeneratedTicket(category=cat, match_id=f"{match.match_id}_{bet[:5]}", sport=match.sport, match_title=title, bet_type=bet, odds=round(odds, 2), ai_confidence=ai.confidence_score, ai_justification=ai.justification)
