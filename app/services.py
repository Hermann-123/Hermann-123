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
        p_o05 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 0])) * 100
        p_o15 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 1])) * 100
        p_o25 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 2])) * 100
        p_o35 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 3])) * 100
        p_o45 = float(np.sum([matrix[i, j] for i in range(self.max_goals) for j in range(self.max_goals) if i + j > 4])) * 100

        est_corners = round(8.5 + (lambda_x + mu_y) * 1.5, 1)

        return SimulationResult(
            match_id=match.match_id, proba_home=p_home, proba_draw=p_draw, proba_away=p_away, 
            most_likely_score=f"{score_x}-{score_y}", proba_btts=p_btts, 
            proba_over_1_5=p_o15, proba_over_2_5=p_o25, proba_over_3_5=p_o35, estimated_corners=est_corners
        )

class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if base_confidence < 40.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Validé mathématiquement.", is_approved=True)

        prompt = f"""
        En tant qu'expert analyste sportif, évalue le match : {match.home_team} vs {match.away_team}. Score le plus probable : {sim.most_likely_score}.
        Rédige UNE SEULE PHRASE percutante justifiant la solidité d'un pronostic sur ce match. Si le match est trop risqué ou incohérent, réponds "VETO".
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
        return AIAuditReport(confidence_score=base_confidence, justification="Sélection mathématique multi-marchés validée.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        
        # 1. BASSIN ÉTENDU DES MARCHÉS PROFESSIONNELS
        pool = []
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: continue
            
            # A) Résultats 1X2 & Double Chance & Draw No Bet
            p_home, p_draw, p_away = sim.proba_home, sim.proba_draw, sim.proba_away
            
            if p_home >= 50.0:
                pool.append({"match": match, "type": f"Victoire {match.home_team} (1)", "odds": max(1.35, round(100.0/p_home*0.95, 2)), "proba": p_home, "ai": ai.justification})
                pool.append({"match": match, "type": f"Draw No Bet (Remboursé si nul) : {match.home_team}", "odds": max(1.20, round(100.0/(p_home + p_draw*0.5)*0.95, 2)), "proba": p_home + 10, "ai": ai.justification})
            
            if p_away >= 50.0:
                pool.append({"match": match, "type": f"Victoire {match.away_team} (2)", "odds": max(1.35, round(100.0/p_away*0.95, 2)), "proba": p_away, "ai": ai.justification})
                pool.append({"match": match, "type": f"Draw No Bet (Remboursé si nul) : {match.away_team}", "odds": max(1.20, round(100.0/(p_away + p_draw*0.5)*0.95, 2)), "proba": p_away + 10, "ai": ai.justification})

            if p_home + p_draw >= 75.0:
                pool.append({"match": match, "type": f"Double Chance : {match.home_team} ou Nul (1X)", "odds": max(1.15, round(100.0/(p_home+p_draw)*0.95, 2)), "proba": p_home+p_draw, "ai": "Option sécurisée validée par le modèle."})
                
            if p_away + p_draw >= 75.0:
                pool.append({"match": match, "type": f"Double Chance : {match.away_team} ou Nul (X2)", "odds": max(1.15, round(100.0/(p_away+p_draw)*0.95, 2)), "proba": p_away+p_draw, "ai": "Option sécurisée validée par le modèle."})

            # B) Nombre de Buts (Over / Under)
            p_o15 = sim.proba_over_1_5
            if p_o15 >= 70.0:
                pool.append({"match": match, "type": "Plus de 1,5 buts dans le match", "odds": max(1.25, round(100.0/p_o15*0.95, 2)), "proba": p_o15, "ai": "Flux offensif suffisant pour dépasser la ligne d'1.5 buts."})
            elif p_o15 < 35.0: # Moins de 2.5 ou 3.5
                pool.append({"match": match, "type": "Moins de 3,5 buts dans le match", "odds": 1.30, "proba": 70.0, "ai": "Rencontre fermée anticipée par le modèle."})

            p_o25 = sim.proba_over_2_5
            if p_o25 >= 55.0:
                pool.append({"match": match, "type": "Plus de 2,5 buts dans le match", "odds": max(1.50, round(100.0/p_o25*0.95, 2)), "proba": p_o25, "ai": "Indicateurs de buts élevés des deux côtés."})

            # C) Les deux équipes marquent (BTTS)
            p_btts = sim.proba_btts
            if p_btts >= 55.0:
                pool.append({"match": match, "type": "Les deux équipes marquent (BTTS : Oui)", "odds": max(1.55, round(100.0/p_btts*0.95, 2)), "proba": p_btts, "ai": "Failles défensives mutuelles et attaques tranchantes."})
            elif p_btts < 40.0:
                pool.append({"match": match, "type": "Les deux équipes marquent (BTTS : Non)", "odds": 1.50, "proba": 65.0, "ai": "Imperméabilité défensive ou manque de réalisme attendu."})

            # D) Corners & Marchés Spéciaux
            pool.append({"match": match, "type": "Plus de 8,5 corners dans le match", "odds": 1.65, "proba": 65.0, "ai": "Pression sur les ailes et tirs cadrés fréquents."})

        # 2. MOTEUR DE COMBINAISON CIBLÉ SUR TES COTES
        def get_best_combo(pool_list, min_odds, max_odds, min_items, max_items):
            if not pool_list: return None
            random.shuffle(pool_list)
            
            for r in range(min_items, max_items + 1):
                for combo in itertools.combinations(pool_list[:35], r):
                    match_ids = [x['match'].match_id for x in combo]
                    if len(set(match_ids)) != len(match_ids): continue # Un seul pari par match max dans le combiné
                    
                    total_odds = 1.0
                    for x in combo: total_odds *= x['odds']
                    
                    if min_odds <= total_odds <= max_odds:
                        return combo
            return None

        # 3. GÉNÉRATION DES 3 CATÉGORIES PRINCIPALES
        
        # 🌟 Combiné du Jour (Cote 2.2 à 3.5)
        combo_jour = get_best_combo(pool, 2.2, 3.5, 2, 3)
        if combo_jour:
            portfolio[TicketCategory.ULTRA_SAFE].append(self._format_combo(combo_jour, TicketCategory.ULTRA_SAFE, "🌟 COMBINÉ DU JOUR"))

        # 💎 Combiné VIP (Cote 3.0 à 5.5)
        combo_vip = get_best_combo(pool, 3.0, 5.5, 3, 4)
        if combo_vip:
            portfolio[TicketCategory.VIP].append(self._format_combo(combo_vip, TicketCategory.VIP, "💎 COMBINÉ VIP"))

        # 🚀 Value Bet (Cote 8.0 à infini)
        combo_value = get_best_combo(pool, 8.0, 35.0, 4, 6)
        if combo_value:
            cat_val = TicketCategory.VALUE_BET if hasattr(TicketCategory, 'VALUE_BET') else TicketCategory.VALUE
            portfolio[cat_val].append(self._format_combo(combo_value, cat_val, "🚀 VALUE BET (COTE 8+)"))

        return dict(portfolio)

    def _format_combo(self, combo, cat, title):
        total_odds = 1.0
        bet_text = ""
        ai_text = "🧠 **Analyse Stratégique :**\n"
        avg_conf = 0.0
        
        for i, c in enumerate(combo, 1):
            total_odds *= c['odds']
            avg_conf += c['proba']
            bet_text += f"*{i}️⃣ {c['match'].home_team} vs {c['match'].away_team}*\n👉 **{c['type']}** (Cote: {c['odds']})\n\n"
            ai_text += f"✔️ {c['match'].home_team} vs {c['match'].away_team} : {c['ai']}\n"
            
        total_odds = round(total_odds, 2)
        avg_conf = round(avg_conf / len(combo), 1)
        
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
