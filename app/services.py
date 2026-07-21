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

        return SimulationResult(match_id=match.match_id, proba_home=p_home, proba_draw=p_draw, proba_away=p_away, most_likely_score=f"{score_x}-{score_y}")

class BasketballEngine:
    def simulate(self, match: MatchData) -> SimulationResult:
        margin = (1.0 / match.home_odds) + (1.0 / match.away_odds)
        p_home = ((1.0 / match.home_odds) / margin) * 100
        p_away = ((1.0 / match.away_odds) / margin) * 100
        return SimulationResult(match_id=match.match_id, proba_home=p_home, proba_draw=0.0, proba_away=p_away, most_likely_score="112-105")

class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if base_confidence < 60.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO : Confiance insuffisante (< 60%). Risque trop élevé.", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Audit validé par le modèle quantitatif.", is_approved=True)

        # 🧠 LE NOUVEAU CERVEAU DE L'IA : On lui donne un rôle strict d'analyste sportif
        prompt = f"""
        Tu es un Analyste Sportif de classe mondiale et un Expert Tipster professionnel.
        Match à analyser : {match.home_team} vs {match.away_team} ({match.league}).
        L'algorithme quantitatif recommande de parier sur : VICTOIRE DE {match.home_team} (Cote : {match.home_odds}).
        
        CONSIGNES STRICTES :
        1. NE RÉPÈTE PAS les probabilités ou les cotes. C'est inutile.
        2. Fais appel à tes connaissances footballistiques (ou basket) sur ces équipes : contexte, supériorité historique, avantage du terrain, style de jeu.
        3. Si tu penses que ce match est un piège (équipe imprévisible, match nul très probable), commence impérativement ta réponse par "VETO".
        4. Si tu valides, rédige 2 à 3 phrases d'analyse pure et percutante pour m'expliquer POURQUOI {match.home_team} va gagner sur le terrain (aspect sportif).
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
                    # On nettoie les guillemets que l'IA met parfois au début
                    if ans.startswith('"') and ans.endswith('"'): ans = ans[1:-1]
                    
                    is_approved = not ans.upper().startswith("VETO")
                    return AIAuditReport(confidence_score=round(base_confidence + 5, 1), justification=ans, is_approved=is_approved)
        except:
            pass
        return AIAuditReport(confidence_score=base_confidence, justification="Validation quantifiée haut niveau.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: 
                continue
                
            title = f"{match.home_team} vs {match.away_team}"
            
            if match.sport == SportType.SOCCER:
                if sim.proba_home >= 70.0:
                    portfolio[TicketCategory.ULTRA_SAFE].append(self._create(TicketCategory.ULTRA_SAFE, match, title, f"Victoire {match.home_team}", match.home_odds, ai))
                elif sim.proba_home >= 62.0:
                    portfolio[TicketCategory.VIP].append(self._create(TicketCategory.VIP, match, title, f"Victoire {match.home_team}", match.home_odds, ai))
                elif match.home_odds >= 1.70 and sim.proba_home >= 58.0:
                    portfolio[TicketCategory.VALUE].append(self._create(TicketCategory.VALUE, match, title, f"Value Bet {match.home_team}", match.home_odds, ai))
            elif match.sport == SportType.BASKETBALL and sim.proba_home >= 65.0:
                portfolio[TicketCategory.SAFE].append(self._create(TicketCategory.SAFE, match, title, f"Victoire {match.home_team}", match.home_odds, ai))
                
        return dict(portfolio)

    def _create(self, cat, match, title, bet, odds, ai):
        return GeneratedTicket(category=cat, match_id=match.match_id, sport=match.sport, match_title=title, bet_type=bet, odds=round(odds, 2), ai_confidence=ai.confidence_score, ai_justification=ai.justification)
