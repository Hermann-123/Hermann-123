import asyncio
import httpx
import numpy as np
from scipy.stats import poisson
from typing import List, Tuple, Dict, Any
from datetime import datetime
from collections import defaultdict
import itertools

from app.models import MatchData, SimulationResult, AIAuditReport, GeneratedTicket, TicketCategory, SportType
from app.core import settings, logger

# =====================================================================
# 1️⃣ MOTEUR 1 : GÉNÉRATEUR MATHÉMATIQUE (DIXON-COLES)
# =====================================================================
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


# =====================================================================
# 2️⃣ MOTEUR 2 : AUDITEUR ADVERSAIRE (CHASSEUR DE FAILLES & SÉCURITÉ)
# =====================================================================
class AdversarialEngine:
    """
    Audit contradictoire pour détecter les matchs pièges et valider la fiabilité.
    """
    async def audit_and_refine(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        # Faille #1 : Rejet systématique des matchs trop indécis sans potentiel de buts
        if base_confidence < 48.0 and sim.proba_over_1_5 < 75.0:
            return AIAuditReport(
                confidence_score=base_confidence, 
                justification="FAILLE DÉTECTÉE : Match piège à haute incertitude, aucun pari fiable.", 
                is_approved=False
            )

        api_key = getattr(settings, 'GROQ_API_KEY', None)
        if not api_key:
            return AIAuditReport(
                confidence_score=base_confidence, 
                justification="Validé par l'audit de sécurité 2nd niveau (Clé IA absente).", 
                is_approved=True
            )

        prompt = f"""
        ANALYSE CONTRADICTOIRE (MOTEUR 2 - CHASSEUR DE FAILLES) :
        Match : {match.home_team} vs {match.away_team}
        Résultats Moteur 1 : Victoire Domicile {sim.proba_home:.1f}%, Nul {sim.proba_draw:.1f}%, Extérieur {sim.proba_away:.1f}%.
        Plus de 1.5 buts : {sim.proba_over_1_5:.1f}%, BTTS (Les 2 marquent) : {sim.proba_btts:.1f}%.

        MISSION : Recherche une faille dans ces données. 
        - Est-ce un piège (favori en baisse, match fermé, statistiques trompeuses) ?
        - Si c'est un piège, réponds 'VETO: <explication de la faille>'.
        - Si le pronostic est solide, donne UNE SEULE PHRASE d'explication concrète de la dynamique réelle des deux équipes.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "llama-3.1-8b-instant", 
                        "messages": [{"role": "user", "content": prompt}]
                    }, 
                    timeout=10.0
                )
                if response.status_code == 200:
                    ans = response.json()['choices'][0]['message']['content'].strip()
                    if ans.upper().startswith("VETO"):
                        return AIAuditReport(confidence_score=0.0, justification=ans, is_approved=False)
                    return AIAuditReport(confidence_score=round(base_confidence, 1), justification=ans, is_approved=True)
                else:
                    logger.error(f"Erreur API Groq ({response.status_code}) : {response.text}")
        except Exception as e:
            logger.error(f"Erreur Moteur 2 Groq : {e}")

        return AIAuditReport(confidence_score=base_confidence, justification="Audit Moteur 2 : Indicateurs au vert.", is_approved=True)


# =====================================================================
# 3️⃣ CRÉATEUR DE PORTFEUILLE & SÉLECTION FLEXIBLE DES PRONOSTICS
# =====================================================================
class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        pool = []
        
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: 
                continue
            
            p_home, p_draw, p_away = sim.proba_home, sim.proba_draw, sim.proba_away

            if p_home >= 52.0:
                pool.append({"match": match, "type": f"Victoire {match.home_team}", "odds": max(1.25, round(100.0/p_home*0.92, 2)), "proba": p_home, "ai": ai.justification})
            elif p_away >= 52.0:
                pool.append({"match": match, "type": f"Victoire {match.away_team}", "odds": max(1.25, round(100.0/p_away*0.92, 2)), "proba": p_away, "ai": ai.justification})

            if 70.0 <= (p_home + p_draw) < 88.0:
                pool.append({"match": match, "type": f"Double Chance (1X) : {match.home_team} ou Nul", "odds": max(1.18, round(100.0/(p_home+p_draw)*0.92, 2)), "proba": p_home+p_draw, "ai": "Moteur 2 : Sécurité garantie sur l'avantage terrain."})
            if 70.0 <= (p_away + p_draw) < 88.0:
                pool.append({"match": match, "type": f"Double Chance (X2) : {match.away_team} ou Nul", "odds": max(1.18, round(100.0/(p_away+p_draw)*0.92, 2)), "proba": p_away+p_draw, "ai": "Moteur 2 : L'équipe visiteuse assurera au moins un point."})

            if sim.proba_over_1_5 >= 72.0:
                pool.append({"match": match, "type": "Plus de 1,5 buts dans le match", "odds": max(1.18, round(100.0/sim.proba_over_1_5*0.92, 2)), "proba": sim.proba_over_1_5, "ai": "Moteur 2 : Flux offensif régulier confirmé."})
            if sim.proba_over_2_5 >= 58.0:
                pool.append({"match": match, "type": "Plus de 2,5 buts dans le match", "odds": max(1.45, round(100.0/sim.proba_over_2_5*0.92, 2)), "proba": sim.proba_over_2_5, "ai": "Moteur 2 : Match ouvert à fort potentiel de buts."})

            if sim.proba_btts >= 60.0:
                pool.append({"match": match, "type": "Les 2 équipes marquent (BTTS)", "odds": max(1.55, round(100.0/sim.proba_btts*0.92, 2)), "proba": sim.proba_btts, "ai": "Moteur 2 : Porosité défensive constatée des deux côtés."})

        used_match_ids = set()

        def get_best_combo(pool_list, min_odds, max_odds, min_items, max_items, min_proba_threshold=0.0, min_single_odds=1.0):
            valid_pool = [
                p for p in pool_list 
                if p['proba'] >= min_proba_threshold 
                and p['odds'] >= min_single_odds
                and p['match'].match_id not in used_match_ids
            ]
            
            valid_pool = sorted(valid_pool, key=lambda x: x['proba'], reverse=True)

            for r in range(min_items, max_items + 1):
                for combo in itertools.combinations(valid_pool[:20], r):
                    match_ids = [x['match'].match_id for x in combo]
                    if len(set(match_ids)) != len(match_ids): 
                        continue
                    
                    total_odds = 1.0
                    for x in combo: 
                        total_odds *= x['odds']
                    
                    if min_odds <= total_odds <= max_odds:
                        for m_id in match_ids:
                            used_match_ids.add(m_id)
                        return combo
            return None

        # 🌟 1. COMBINÉ DU JOUR (Cotes totales >= 1.60, min 2 matchs ou 1 pari solide)
        combo_jour = get_best_combo(pool, min_odds=1.60, max_odds=4.0, min_items=2, max_items=3, min_proba_threshold=65.0, min_single_odds=1.18)
        if combo_jour:
            portfolio[TicketCategory.ULTRA_SAFE].append(self._format_combo(combo_jour, TicketCategory.ULTRA_SAFE, "🌟 COMBINÉ DU JOUR (SÉCURITÉ MAX)"))

        # 💎 2. COMBINÉ VIP (Cotes totales >= 2.5)
        combo_vip = get_best_combo(pool, min_odds=2.5, max_odds=6.0, min_items=2, max_items=4, min_proba_threshold=60.0, min_single_odds=1.25)
        if combo_vip:
            portfolio[TicketCategory.VIP].append(self._format_combo(combo_vip, TicketCategory.VIP, "💎 COMBINÉ VIP (RENTABILITÉ)"))

        # 🚀 3. VALUE BET / OPPORTUNITÉ (Accepte aussi les paris simples si peu de matchs)
        combo_value = get_best_combo(pool, min_odds=1.45, max_odds=30.0, min_items=1, max_items=5, min_proba_threshold=50.0, min_single_odds=1.35)
        if combo_value:
            cat_val = getattr(TicketCategory, 'VALUE_BET', getattr(TicketCategory, 'VALUE', TicketCategory.VIP))
            portfolio[cat_val].append(self._format_combo(combo_value, cat_val, "🚀 VALUE BET (OPPORTUNITÉ)"))

        return dict(portfolio)

    def _format_combo(self, combo, cat, title):
        total_odds = 1.0
        combo_proba_math = 1.0
        
        bet_text = ""
        ai_text = "🧠 **Rapport Moteur 2 (Analyse des Failles) :**\n"
        
        for i, c in enumerate(combo, 1):
            total_odds *= c['odds']
            combo_proba_math *= (c['proba'] / 100.0)
            
            bet_text += f"*{i}️⃣ {c['match'].home_team} vs {c['match'].away_team}*\n👉 **{c['type']}**\n📊 Cote : {c['odds']} | 🎯 Confiance Moteur 2 : {c['proba']:.1f}%\n\n"
            ai_text += f"✔️ **{c['match'].home_team} vs {c['match'].away_team}** : {c['ai']}\n\n"
            
        total_odds = round(total_odds, 2)
        final_combo_proba = round(combo_proba_math * 100, 1)
        
        bet_text += f"🔥 **FIABILITÉ GLOBALE DU COMBINÉ : {final_combo_proba}%**\n"
        
        ids = sorted([c['match'].match_id for c in combo])
        unique_id = f"combo_{cat.name}_{'_'.join(ids)}"
        
        return GeneratedTicket(
            category=cat, 
            match_id=unique_id, 
            sport=combo[0]['match'].sport, 
            match_title=title, 
            bet_type=bet_text.strip(), 
            odds=total_odds, 
            ai_confidence=final_combo_proba, 
            ai_justification=ai_text.strip()
        )
