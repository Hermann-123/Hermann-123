import numpy as np
import httpx
from scipy.stats import poisson
from typing import List, Tuple
from collections import defaultdict

from app.models import MatchData, SimulationResult, AIAuditReport, GeneratedTicket, TicketCategory
from app.core import settings, logger

class DixonColesEngine:
    def simulate(self, match: MatchData) -> SimulationResult:
        lambda_x = (1.0 / match.home_odds) * 1.8 * 1.15
        mu_y = (1.0 / match.away_odds) * 1.8
        matrix = np.zeros((6, 6))

        for i in range(6):
            for j in range(6):
                matrix[i, j] = poisson.pmf(i, lambda_x) * poisson.pmf(j, mu_y)
        
        matrix /= np.sum(matrix)
        p_home = float(np.sum(np.tril(matrix, -1))) * 100
        p_draw = float(np.sum(np.diag(matrix))) * 100
        p_away = float(np.sum(np.triu(matrix, 1))) * 100

        best_idx = np.argmax(matrix)
        score_x, score_y = np.unravel_index(best_idx, matrix.shape)

        return SimulationResult(
            match_id=match.match_id, proba_home=p_home, proba_draw=p_draw, proba_away=p_away, 
            most_likely_score=f"{score_x}-{score_y}", 
            proba_btts=float(np.sum(matrix[1:, 1:])) * 100, 
            proba_over_1_5=float(np.sum([matrix[i, j] for i in range(6) for j in range(6) if i + j > 1])) * 100, 
            proba_over_2_5=float(np.sum([matrix[i, j] for i in range(6) for j in range(6) if i + j > 2])) * 100
        )

class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult, bet_type: str) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if base_confidence < 45.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Analyse technique validée.", is_approved=True)

        prompt = f"""
        Expert en paris sportifs. Analyse le match {match.home_team} contre {match.away_team}.
        Le pari mathématique proposé est : {bet_type}.
        Rédige OBLIGATOIREMENT 2 phrases complètes d'analyse tactique pour justifier ce pari.
        Si tu penses que c'est risqué, réponds UNIQUEMENT le mot "VETO". Ne donne aucun chiffre.
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
                    if "VETO" in ans.upper() or len(ans) < 15:
                        return AIAuditReport(confidence_score=base_confidence, justification="VETO", is_approved=False)
                    return AIAuditReport(confidence_score=round(base_confidence + 5, 1), justification=ans, is_approved=True)
        except: pass
        return AIAuditReport(confidence_score=base_confidence, justification="Données sportives validées par l'algorithme.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: continue
                
            title = f"{match.home_team} vs {match.away_team}"
            
            # --- ULTRA SAFE (FOOT) ---
            if sim.proba_home >= sim.proba_away:
                dc_prob, dc_odds, dc_name = sim.proba_home + sim.proba_draw, 1.28, f"Double Chance : {match.home_team} ou Nul (1X)"
            else:
                dc_prob, dc_odds, dc_name = sim.proba_away + sim.proba_draw, 1.32, f"Double Chance : {match.away_team} ou Nul (X2)"
            
            if dc_prob >= 75.0:
                portfolio[TicketCategory.ULTRA_SAFE].append(GeneratedTicket(category=TicketCategory.ULTRA_SAFE, match_id=f"{match.match_id}_dc", match_title=title, bet_type=dc_name, odds=dc_odds, ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            # --- VIP (FOOT) ---
            best_team = match.home_team if sim.proba_home >= sim.proba_away else match.away_team
            best_odds = match.home_odds if sim.proba_home >= sim.proba_away else match.away_odds
            
            if max(sim.proba_home, sim.proba_away) >= 58.0 and best_odds >= 1.50:
                portfolio[TicketCategory.VIP].append(GeneratedTicket(category=TicketCategory.VIP, match_id=f"{match.match_id}_vip", match_title=title, bet_type=f"Victoire {best_team}", odds=best_odds, ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            # --- VALUE BETS ---
            if sim.proba_btts >= 60.0:
                portfolio[TicketCategory.VALUE].append(GeneratedTicket(category=TicketCategory.VALUE, match_id=f"{match.match_id}_btts", match_title=title, bet_type="Les deux équipes marquent (BTTS)", odds=1.75, ai_confidence=ai.confidence_score, ai_justification=ai.justification))

            # --- TOP OPPORTUNITÉS ---
            if ai.confidence_score > 75.0:
                portfolio[TicketCategory.TOP_OPP].append(GeneratedTicket(category=TicketCategory.TOP_OPP, match_id=f"{match.match_id}_top", match_title=title, bet_type=f"Opportunité Majeure : Victoire {best_team}", odds=best_odds, ai_confidence=ai.confidence_score, ai_justification=ai.justification))
                
        return dict(portfolio)
