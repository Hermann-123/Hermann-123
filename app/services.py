import asyncio
import httpx
import numpy as np
from scipy.stats import poisson
from typing import List, Tuple
from datetime import datetime
from collections import defaultdict
import itertools
import random

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
        base_confidence = max(sim.proba_home, sim.proba_away)
        
        # On valide les matchs fiables pour les combinés (55% minimum)
        if base_confidence < 55.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Validé mathématiquement.", is_approved=True)

        prompt = f"""
        Tu es un expert en trading sportif.
        Match : {match.home_team} vs {match.away_team}. Le modèle prévoit ce score : {sim.most_likely_score}.
        TA MISSION : Rédige UNE SEULE PHRASE très courte et percutante expliquant pourquoi ce choix est idéal pour être placé dans un ticket combiné. 
        Si le match est un piège, réponds UNIQUEMENT "VETO".
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
                    return AIAuditReport(confidence_score=round(base_confidence, 1), justification=ans, is_approved=is_approved)
        except: pass
        return AIAuditReport(confidence_score=base_confidence, justification="Sélection mathématique validée.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        
        # 1. Extraction de tous les paris fiables de la journée
        pool = []
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: continue
            
            best_proba = max(sim.proba_home, sim.proba_away)
            best_team = match.home_team if best_proba == sim.proba_home else match.away_team
            win_odds = max(1.30, round(100.0 / best_proba * 1.02, 2)) # Marge réaliste
            
            if best_proba >= 58.0:
                pool.append({"match": match, "type": f"Victoire {best_team}", "odds": win_odds, "proba": best_proba, "ai": ai.justification})
            
            if sim.proba_btts >= 60.0:
                btts_odds = max(1.40, round(100.0 / sim.proba_btts * 1.02, 2))
                pool.append({"match": match, "type": "Les 2 équipes marquent", "odds": btts_odds, "proba": sim.proba_btts, "ai": ai.justification})

        # 2. Le Moteur de Combinaison (Cherche à atteindre les cotes exactes)
        def get_best_combo(pool_list, min_odds, max_odds, min_items, max_items):
            random.shuffle(pool_list) # Mélange pour des tickets variés
            pool_list = sorted(pool_list, key=lambda x: x['proba'], reverse=True)[:15] # Top 15 matchs les plus sûrs
            
            for r in range(min_items, max_items + 1):
                for combo in itertools.combinations(pool_list, r):
                    # Interdit de mettre 2 fois le même match dans le combiné
                    match_ids = [x['match'].match_id for x in combo]
                    if len(set(match_ids)) != len(match_ids): continue 
                    
                    total_odds = 1.0
                    for x in combo: total_odds *= x['odds']
                    
                    if min_odds <= total_odds <= max_odds:
                        return combo
            return None

        # 3. CRÉATION DES COMBINÉS 
        
        # 🟢 Combiné du Jour (Cote cible : 2.2 à 3.5)
        # On cherche 2 à 3 matchs très sûrs.
        combo_jour = get_best_combo([p for p in pool if p['proba'] >= 65.0], 2.2, 3.5, 2, 3)
        if combo_jour:
            portfolio[TicketCategory.ULTRA_SAFE].append(self._format_combo(combo_jour, TicketCategory.ULTRA_SAFE, "🌟 COMBINÉ DU JOUR"))

        # 🔵 Combiné VIP (Cote cible : 3.0 à 5.5)
        # On assemble 3 à 4 matchs fiables.
        combo_vip = get_best_combo(pool, 3.0, 5.5, 2, 4)
        if combo_vip:
            portfolio[TicketCategory.VIP].append(self._format_combo(combo_vip, TicketCategory.VIP, "💎 COMBINÉ VIP"))

        # 🔴 Value Bet (Cote cible : 8.0 à infini, ici plafonné à 50.0)
        # On combine 4 à 6 matchs pour faire exploser la cote.
        combo_value = get_best_combo(pool, 8.0, 50.0, 3, 6)
        if combo_value:
            portfolio[TicketCategory.VALUE].append(self._format_combo(combo_value, TicketCategory.VALUE, "🚀 VALUE BET (COTE 8+)"))

        return dict(portfolio)

    def _format_combo(self, combo, cat, title):
        total_odds = 1.0
        bet_text = ""
        ai_text = "🧠 **Rapport IA du Combiné :**\n"
        avg_conf = 0.0
        
        # On assemble la présentation du ticket
        for i, c in enumerate(combo, 1):
            total_odds *= c['odds']
            avg_conf += c['proba']
            bet_text += f"*{i}️⃣ {c['match'].home_team} vs {c['match'].away_team}*\n👉 **{c['type']}** (Cote: {c['odds']})\n\n"
            ai_text += f"✔️ {c['match'].home_team}: {c['ai']}\n"
            
        total_odds = round(total_odds, 2)
        avg_conf = round(avg_conf / len(combo), 1)
        
        # Création d'un ID unique basé sur les matchs du combiné
        ids = sorted([c['match'].match_id for c in combo])
        unique_id = f"combo_{cat.name}_{'_'.join(ids)}"
        
        return GeneratedTicket(
            category=cat, 
            match_id=unique_id, 
            sport=combo[0]['match'].sport, 
            match_title=title, 
            bet_type=bet_text.strip(), 
            odds=total_odds, 
            ai_confidence=avg_conf, 
            ai_justification=ai_text.strip()
        )
