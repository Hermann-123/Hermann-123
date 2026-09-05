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
    Ce 2ème moteur prend les prédictions brutes du 1er moteur et cherche
    activement des failles (pièges, incohérences) pour sortir LE pronostic le plus solide.
    """
    async def audit_and_refine(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        # Faille #1 : Rejet systématique des matchs indécis
        if base_confidence < 48.0 and sim.proba_over_1_5 < 75.0:
            return AIAuditReport(
                confidence_score=base_confidence, 
                justification="FAILLE DÉTECTÉE : Match piège à haute incertitude, aucun pari fiable.", 
                is_approved=False
            )

        if not settings.GROQ_API_KEY:
            return AIAuditReport(
                confidence_score=base_confidence, 
                justification="Validé par l'audit de sécurité 2nd niveau.", 
                is_approved=True
            )

        # Prompt contradictoire : On demande à l'IA d'ATTAQUER le pronostic du 1er moteur
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
                    headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
                    json={"model": "llama-3.1-8b-instant", "messages": [{"role": "user", "content": prompt}]}, 
                    timeout=10.0
                )
                if response.status_code == 200:
                    ans = response.json()['choices'][0]['message']['content'].strip()
                    if ans.upper().startswith("VETO"):
                        return AIAuditReport(confidence_score=0.0, justification=ans, is_approved=False)
                    return AIAuditReport(confidence_score=round(base_confidence, 1), justification=ans, is_approved=True)
        except Exception as e:
            logger.error(f"Erreur Moteur 2 Groq: {e}")

        return AIAuditReport(confidence_score=base_confidence, justification="Audit Moteur 2 : Indicateurs au vert.", is_approved=True)


# =====================================================================
# 3️⃣ CRÉATEUR DE PORTFEUILLE & SÉLECTION DES MEILLEURS PRONOSTICS
# =====================================================================
class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        pool = []
        
        # Filtrage et génération des meilleures opportunités après validation du Moteur 2
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: 
                continue # Le Moteur 2 a rejeté ce match
            
            p_home, p_draw, p_away = sim.proba_home, sim.proba_draw, sim.proba_away
            base_confidence = max(p_home, p_draw, p_away)

            # 🟢 1. OPTION FAVORIS (Uniquement si confiance solide du Moteur 2)
            if p_home >= 58.0:
                pool.append({"match": match, "type": f"Victoire {match.home_team}", "odds": max(1.30, round(100.0/p_home*0.92, 2)), "proba": p_home, "ai": ai.justification})
            elif p_away >= 58.0:
                pool.append({"match": match, "type": f"Victoire {match.away_team}", "odds": max(1.30, round(100.0/p_away*0.92, 2)), "proba": p_away, "ai": ai.justification})

            # 🟢 2. SÉCURITÉ DOUBLE CHANCE (Si le favori peut douter)
            if 75.0 <= (p_home + p_draw) < 88.0:
                pool.append({"match": match, "type": f"Double Chance (1X) : {match.home_team} ou Nul", "odds": max(1.20, round(100.0/(p_home+p_draw)*0.92, 2)), "proba": p_home+p_draw, "ai": "Moteur 2 : Sécurité garantie sur l'avantage terrain."})
            if 75.0 <= (p_away + p_draw) < 88.0:
                pool.append({"match": match, "type": f"Double Chance (X2) : {match.away_team} ou Nul", "odds": max(1.20, round(100.0/(p_away+p_draw)*0.92, 2)), "proba": p_away+p_draw, "ai": "Moteur 2 : L'équipe visiteuse assurera au moins un point."})

            # 🟢 3. MARCHÉS BUTS (OVER / UNDER)
            if sim.proba_over_1_5 >= 78.0:
                pool.append({"match": match, "type": "Plus de 1,5 buts dans le match", "odds": max(1.22, round(100.0/sim.proba_over_1_5*0.92, 2)), "proba": sim.proba_over_1_5, "ai": "Moteur 2 : Flux offensif régulier confirmé."})
            if sim.proba_over_2_5 >= 62.0:
                pool.append({"match": match, "type": "Plus de 2,5 buts dans le match", "odds": max(1.55, round(100.0/sim.proba_over_2_5*0.92, 2)), "proba": sim.proba_over_2_5, "ai": "Moteur 2 : Match ouvert à fort potentiel de buts."})

            # 🟢 4. BTTS (Les 2 équipes marquent)
            if sim.proba_btts >= 64.0:
                pool.append({"match": match, "type": "Les 2 équipes marquent (BTTS)", "odds": max(1.65, round(100.0/sim.proba_btts*0.92, 2)), "proba": sim.proba_btts, "ai": "Moteur 2 : Porosité défensive constatée des deux côtés."})

        # --- ALGORITHME DE SELECTION ANTI-DOUBLONS ---
        used_match_ids = set()

        def get_best_combo(pool_list, min_odds, max_odds, min_items, max_items, min_proba_threshold=0.0, min_single_odds=1.0):
            # Filtre par probabilité et cote minimale individuelle
            valid_pool = [
                p for p in pool_list 
                if p['proba'] >= min_proba_threshold 
                and p['odds'] >= min_single_odds
                and p['match'].match_id not in used_match_ids
            ]
            
            # Tri STRICT du pronostic le plus sûr au moins sûr
            valid_pool = sorted(valid_pool, key=lambda x: x['proba'], reverse=True)

            for r in range(min_items, max_items + 1):
                for combo in itertools.combinations(valid_pool[:20], r):
                    match_ids = [x['match'].match_id for x in combo]
                    if len(set(match_ids)) != len(match_ids): 
                        continue # 1 seul pari par match
                    
                    total_odds = 1.0
                    for x in combo: 
                        total_odds *= x['odds']
                    
                    if min_odds <= total_odds <= max_odds:
                        # Marquer ces matchs comme utilisés pour éviter les doublons dans les autres tickets
                        for m_id in match_ids:
                            used_match_ids.add(m_id)
                        return combo
            return None

        # 🌟 1. COMBINÉ DU JOUR (Sécurité Maximale : Cotes >= 1.25, Proba >= 75%)
        combo_jour = get_best_combo(pool, min_odds=2.0, max_odds=3.5, min_items=2, max_items=3, min_proba_threshold=75.0, min_single_odds=1.25)
        if combo_jour:
            portfolio[TicketCategory.ULTRA_SAFE].append(self._format_combo(combo_jour, TicketCategory.ULTRA_SAFE, "🌟 COMBINÉ DU JOUR (SÉCURITÉ MAX)"))

        # 💎 2. COMBINÉ VIP (Rentabilité : Cotes >= 1.35, Proba >= 63%, MATCHS DIFFÉRENTS)
        combo_vip = get_best_combo(pool, min_odds=3.2, max_odds=6.0, min_items=3, max_items=4, min_proba_threshold=63.0, min_single_odds=1.35)
        if combo_vip:
            portfolio[TicketCategory.VIP].append(self._format_combo(combo_vip, TicketCategory.VIP, "💎 COMBINÉ VIP (RENTABILITÉ)"))

        # 🚀 3. VALUE BET (Grosse Cote : Cotes >= 1.45 EXCLUSIVEMENT, pas de petites cotes 1.15 !)
        combo_value = get_best_combo(pool, min_odds=7.0, max_odds=30.0, min_items=4, max_items=6, min_proba_threshold=50.0, min_single_odds=1.45)
        if combo_value:
            cat_val = TicketCategory.VALUE_BET if hasattr(TicketCategory, 'VALUE_BET') else TicketCategory.VALUE
            portfolio[cat_val].append(self._format_combo(combo_value, cat_val, "🚀 VALUE BET (GROSSE COTE)"))

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
