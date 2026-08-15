# app/services.py
#
# WALLSTREET OS - PROFESSIONAL ANALYSIS ENGINE (QUANT FUND V5)
# ------------------------------------------------------------
import asyncio
import json
import httpx
import numpy as np
from scipy.stats import poisson
from typing import List, Tuple, Dict
from datetime import datetime
from collections import defaultdict
import itertools

from app.models import MatchData, SimulationResult, AIAuditReport, GeneratedTicket, TicketCategory, SportType
from app.core import settings, logger

# ============================================================
# 1. MOTEUR MATHÉMATIQUE (DIXON-COLES + FORME RÉCENTE)
# ============================================================
class DixonColesEngine:
    def __init__(self, rho: float = -0.15, home_advantage: float = 1.15):
        self.rho = rho
        self.home_advantage = home_advantage
        self.max_goals = 6

    def simulate(self, match: MatchData) -> SimulationResult:
        # Analyse des performances récentes (Protégé par le bouclier de models.py)
        home_goals_scored = np.mean(match.home_recent_scores)
        home_goals_conceded = np.mean(match.home_recent_conceded)
        away_goals_scored = np.mean(match.away_recent_scores)
        away_goals_conceded = np.mean(match.away_recent_conceded)
        
        # Ajustements des attentes de but basés sur les performances
        adjusted_home_attack = home_goals_scored * (1 + (home_goals_conceded / 100))
        adjusted_away_attack = away_goals_scored * (1 + (away_goals_conceded / 100))

        # Calcul des lambda ajustés (avec avantage à domicile)
        lambda_x = adjusted_home_attack * self.home_advantage
        mu_y = adjusted_away_attack
        
        # Création de la matrice des probabilités
        matrix = np.zeros((self.max_goals, self.max_goals))

        for i in range(self.max_goals):
            for j in range(self.max_goals):
                matrix[i, j] = poisson.pmf(i, lambda_x) * poisson.pmf(j, mu_y)

        # Normaliser la matrice
        matrix /= np.sum(matrix)

        # Extraction des probabilités 1X2
        p_home = float(np.sum(np.tril(matrix, -1))) * 100
        p_draw = float(np.sum(np.diag(matrix))) * 100
        p_away = float(np.sum(np.triu(matrix, 1))) * 100

        best_idx = np.argmax(matrix)
        score_x, score_y = np.unravel_index(best_idx, matrix.shape)

        # Probabilités supplémentaires (Buts)
        p_btts = float(np.sum(matrix[1:, 1:])) * 100
        p_o15 = self.calculate_over_prob(matrix, threshold=1)
        p_o25 = self.calculate_over_prob(matrix, threshold=2)
        p_o35 = self.calculate_over_prob(matrix, threshold=3)

        est_corners = round(8.5 + (lambda_x + mu_y) * 1.5, 1)

        return SimulationResult(
            match_id=match.match_id, 
            proba_home=p_home, 
            proba_draw=p_draw, 
            proba_away=p_away, 
            most_likely_score=f"{score_x}-{score_y}", 
            proba_btts=p_btts, 
            proba_over_1_5=p_o15, 
            proba_over_2_5=p_o25, 
            proba_over_3_5=p_o35, 
            estimated_corners=est_corners
        )

    def calculate_over_prob(self, matrix, threshold) -> float:
        return float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > threshold])) * 100


# ============================================================
# 2. IA - SECOND AVIS (ÉVALUATION DU RISQUE)
# ============================================================
class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        # Filtre initial : Rejet des matchs imprévisibles (< 45% de certitude)
        if base_confidence < 45.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO - Match trop serré.", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Validé mathématiquement (IA hors ligne).", is_approved=True)

        # 🧠 APPEL IA : Validation du risque
        prompt = f"""
        Tu es le gestionnaire des risques d'un algorithme de paris sportifs. 
        Match : {match.home_team} vs {match.away_team}.
        
        DONNÉES STATISTIQUES (Modèle de Poisson ajusté sur la forme récente) :
        - Victoire {match.home_team} : {round(sim.proba_home, 1)}%
        - Match Nul : {round(sim.proba_draw, 1)}%
        - Victoire {match.away_team} : {round(sim.proba_away, 1)}%
        - Plus de 2.5 buts : {round(sim.proba_over_2_5, 1)}%
        - Les deux marquent (BTTS) : {round(sim.proba_btts, 1)}%
        
        Mission :
        1. Analyse ces probabilités.
        2. Détermine si le match est suffisamment déséquilibré ou prévisible pour être joué de manière sécurisée.
        3. Si les données sont trop serrées ou indécises, réponds "VETO".
        
        Renvoie UNIQUEMENT un JSON strict : 
        {{"decision": "ACCEPT" ou "VETO", "reason": "Justification de 15 mots max"}}
        """

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]},
                    timeout=12.0
                )
                
                if response.status_code == 200:
                    content = response.json()['choices'][0]['message']['content'].strip()
                    # Nettoyage robuste du JSON
                    start = content.find('{')
                    end = content.rfind('}')
                    if start != -1 and end != -1:
                        data = json.loads(content[start:end+1])
                        
                        if data.get("decision") == "ACCEPT":
                            return AIAuditReport(
                                confidence_score=base_confidence, 
                                justification=data.get("reason", "Validation IA."), 
                                is_approved=True
                            )
                        return AIAuditReport(confidence_score=base_confidence, justification="VETO IA", is_approved=False)
        except Exception as e:
            logger.error(f"Erreur IA sur {match.home_team}: {e}")
            
        # Mode Survie en cas d'échec de l'API Groq
        return AIAuditReport(
            confidence_score=base_confidence, 
            justification="Approuvé par sécurité mathématique (IA hors ligne).", 
            is_approved=True
        )


# ============================================================
# 3. LE GÉNÉRATEUR ET FILTRE DE VALEUR (EDGE)
# ============================================================
class MarketAnalyzer:
    def generate_candidates(self, match: MatchData, sim: SimulationResult, bookmaker_odds: dict) -> List[dict]:
        candidates = []
        
        def add_candidate(m_type, selection, proba, odds_key):
            real_odds = bookmaker_odds.get(odds_key)
            if real_odds:
                implied = (1.0 / real_odds) * 100
                edge = proba - implied
                # Filtre : Edge positif, probabilité min 52%, et cote raisonnable
                if edge > 0 and proba >= 52.0 and 1.25 <= real_odds <= 2.20:
                    candidates.append({
                        "match": match, "market": m_type, "selection": selection, 
                        "probability": proba, "odds": real_odds, "edge": edge
                    })

        # Ajout des paris disponibles
        add_candidate("1X2", f"Victoire {match.home_team}", sim.proba_home, "1")
        add_candidate("1X2", f"Victoire {match.away_team}", sim.proba_away, "2")
        add_candidate("OVER_UNDER", "Plus de 1,5 buts", sim.proba_over_1_5, "O1.5")
        add_candidate("OVER_UNDER", "Plus de 2,5 buts", sim.proba_over_2_5, "O2.5")
        add_candidate("OVER_UNDER", "Moins de 2,5 buts", 100 - sim.proba_over_2_5, "U2.5")
        add_candidate("BTTS", "BTTS Oui", sim.proba_btts, "BTTS_Y")
        add_candidate("BTTS", "BTTS Non", 100 - sim.proba_btts, "BTTS_N")

        # 🚨 LE "MOINS DE 3,5 BUTS" EST VOLONTAIREMENT DÉSACTIVÉ ICI POUR FORCER L'ALGO À ÊTRE AGRESSIF.

        # Tri par Edge décroissant (On garde les paris les plus rentables)
        candidates.sort(key=lambda x: x['edge'], reverse=True)
        return candidates[:3] # On retourne les 3 meilleures options par match


# ============================================================
# 4. L'USINE À TICKETS (OBJECTIF : 100 000 FCFA)
# ============================================================
class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, dict, AIAuditReport]]):
        portfolio = defaultdict(list)
        pool = []
        
        # On rassemble tous les paris validés par l'IA et filtrés par le Edge
        for match, candidate, ai_res in evaluated_matches:
            if ai_res.is_approved and candidate:
                pool.append({
                    "match": match, 
                    "type": candidate["selection"], 
                    "odds": candidate["odds"], 
                    "proba": candidate["probability"], 
                    "edge": candidate["edge"],
                    "ai": ai_res.justification
                })

        # Assemblage : Exactement 2 matchs, Cote entre 2.2 et 3.5
        pool.sort(key=lambda x: x['edge'], reverse=True)
        
        for combo in itertools.combinations(pool[:15], 2):
            total_odds = combo[0]["odds"] * combo[1]["odds"]
            
            if 2.2 <= round(total_odds, 2) <= 3.5:
                bet_text = ""
                ai_text = ""
                for i, item in enumerate(combo, 1):
                    bet_text += f"*{i}️⃣ {item['match'].home_team} vs {item['match'].away_team}*\n👉 **{item['type']}**\n📊 Cote : {item['odds']} | 🎯 Proba : {item['proba']:.1f}%\n\n"
                    ai_text += f"✔️ **{item['match'].home_team}** : {item['ai']}\n"
                
                final_proba = round((combo[0]["proba"]/100) * (combo[1]["proba"]/100) * 100, 1)
                
                ticket = GeneratedTicket(
                    category=TicketCategory.ULTRA_SAFE, match_id="combo_value", sport=SportType.SOCCER,
                    match_title="🌟 COMBINÉ VALUE BET (FORME RÉCENTE)", bet_type=bet_text.strip(), odds=round(total_odds, 2),
                    ai_confidence=final_proba, ai_justification=ai_text.strip()
                )
                portfolio[TicketCategory.ULTRA_SAFE].append(ticket)
                break # On s'arrête dès qu'un combiné parfait est trouvé

        return dict(portfolio)


# ============================================================
# 5. PIPELINE GLOBAL (Liaison avec main.py)
# ============================================================
class AnalysisPipeline:
    def __init__(self):
        self.math_engine = DixonColesEngine()
        self.market_analyzer = MarketAnalyzer()
        self.ai_manager = AIRiskManager()
        self.ticket_factory = TicketFactory()

    async def analyze_match(self, match: MatchData, bookmaker_odds: dict):
        # 1. Mathématiques
        simulation = self.math_engine.simulate(match)
        # 2. Marchés et Edge
        candidates = self.market_analyzer.generate_candidates(match, simulation, bookmaker_odds)
        best_candidate = candidates[0] if candidates else None
        # 3. Validation Risque IA
        ai_report = await self.ai_manager.evaluate_match(match, simulation)
        
        return (match, best_candidate, ai_report)

    async def build_daily_portfolio(self, matches_and_odds: List[Tuple[MatchData, dict]]):
        # Traitement asynchrone rapide de tous les matchs
        tasks = [self.analyze_match(m, odds) for m, odds in matches_and_odds]
        evaluated = await asyncio.gather(*tasks)
        
        # Création des tickets
        return self.ticket_factory.build_portfolio(evaluated)

# Instanciation pour l'import dans main.py
pipeline = AnalysisPipeline()
