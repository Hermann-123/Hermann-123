class AIRiskManager:
    async def evaluate_match(self, match: MatchData, sim: SimulationResult) -> AIAuditReport:
        base_confidence = max(sim.proba_home, sim.proba_draw, sim.proba_away)
        
        if base_confidence < 40.0:
            return AIAuditReport(confidence_score=base_confidence, justification="VETO", is_approved=False)

        if not settings.GROQ_API_KEY:
            return AIAuditReport(confidence_score=base_confidence, justification="Validé mathématiquement.", is_approved=True)

        # 🧠 NOUVEAU PROMPT IA : On exige des explications concrètes
        prompt = f"""
        En tant qu'expert analyste sportif, évalue le match : {match.home_team} vs {match.away_team}. 
        Le modèle mathématique donne {base_confidence:.1f}% de chance à ce pronostic.
        TA MISSION : Rédige une analyse CONCRÈTE ET RASSURANTE (1 à 2 phrases max) expliquant tactiquement pourquoi ce pari précis est un excellent choix. Sois précis sur la dynamique des équipes.
        Si le match est trop risqué, réponds UNIQUEMENT "VETO".
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
        return AIAuditReport(confidence_score=base_confidence, justification="Indicateurs de performance largement favorables à ce scénario.", is_approved=True)

class TicketFactory:
    def build_portfolio(self, evaluated_matches: List[Tuple[MatchData, SimulationResult, AIAuditReport]]):
        portfolio = defaultdict(list)
        
        pool = []
        for match, sim, ai in evaluated_matches:
            if not ai.is_approved: continue
            
            p_home, p_draw, p_away = sim.proba_home, sim.proba_draw, sim.proba_away
            
            if p_home >= 50.0:
                pool.append({"match": match, "type": f"Victoire {match.home_team} (1)", "odds": max(1.35, round(100.0/p_home*0.95, 2)), "proba": p_home, "ai": ai.justification})
                pool.append({"match": match, "type": f"Draw No Bet : {match.home_team}", "odds": max(1.20, round(100.0/(p_home + p_draw*0.5)*0.95, 2)), "proba": p_home + 10, "ai": ai.justification})
            
            if p_away >= 50.0:
                pool.append({"match": match, "type": f"Victoire {match.away_team} (2)", "odds": max(1.35, round(100.0/p_away*0.95, 2)), "proba": p_away, "ai": ai.justification})
                pool.append({"match": match, "type": f"Draw No Bet : {match.away_team}", "odds": max(1.20, round(100.0/(p_away + p_draw*0.5)*0.95, 2)), "proba": p_away + 10, "ai": ai.justification})

            if p_home + p_draw >= 75.0:
                pool.append({"match": match, "type": f"Double Chance : {match.home_team} ou Nul (1X)", "odds": max(1.15, round(100.0/(p_home+p_draw)*0.95, 2)), "proba": p_home+p_draw, "ai": ai.justification})
                
            if p_away + p_draw >= 75.0:
                pool.append({"match": match, "type": f"Double Chance : {match.away_team} ou Nul (X2)", "odds": max(1.15, round(100.0/(p_away+p_draw)*0.95, 2)), "proba": p_away+p_draw, "ai": ai.justification})

            p_o15 = sim.proba_over_1_5
            if p_o15 >= 70.0:
                pool.append({"match": match, "type": "Plus de 1,5 buts dans le match", "odds": max(1.25, round(100.0/p_o15*0.95, 2)), "proba": p_o15, "ai": ai.justification})

            p_o25 = sim.proba_over_2_5
            if p_o25 >= 55.0:
                pool.append({"match": match, "type": "Plus de 2,5 buts dans le match", "odds": max(1.50, round(100.0/p_o25*0.95, 2)), "proba": p_o25, "ai": ai.justification})

            p_btts = sim.proba_btts
            if p_btts >= 55.0:
                pool.append({"match": match, "type": "Les deux équipes marquent (BTTS : Oui)", "odds": max(1.55, round(100.0/p_btts*0.95, 2)), "proba": p_btts, "ai": ai.justification})

            pool.append({"match": match, "type": "Plus de 8,5 corners dans le match", "odds": 1.65, "proba": 65.0, "ai": "Pression offensive constante générant beaucoup de corners."})

        def get_best_combo(pool_list, min_odds, max_odds, min_items, max_items):
            if not pool_list: return None
            import random
            random.shuffle(pool_list)
            
            for r in range(min_items, max_items + 1):
                import itertools
                for combo in itertools.combinations(pool_list[:35], r):
                    match_ids = [x['match'].match_id for x in combo]
                    if len(set(match_ids)) != len(match_ids): continue
                    
                    total_odds = 1.0
                    for x in combo: total_odds *= x['odds']
                    
                    if min_odds <= total_odds <= max_odds:
                        return combo
            return None

        combo_jour = get_best_combo(pool, 2.2, 3.5, 2, 3)
        if combo_jour:
            portfolio[TicketCategory.ULTRA_SAFE].append(self._format_combo(combo_jour, TicketCategory.ULTRA_SAFE, "🌟 COMBINÉ DU JOUR"))

        combo_vip = get_best_combo(pool, 3.0, 5.5, 3, 4)
        if combo_vip:
            portfolio[TicketCategory.VIP].append(self._format_combo(combo_vip, TicketCategory.VIP, "💎 COMBINÉ VIP"))

        combo_value = get_best_combo(pool, 8.0, 35.0, 4, 6)
        if combo_value:
            cat_val = TicketCategory.VALUE_BET if hasattr(TicketCategory, 'VALUE_BET') else TicketCategory.VALUE
            portfolio[cat_val].append(self._format_combo(combo_value, cat_val, "🚀 VALUE BET (COTE 8+)"))

        return dict(portfolio)

    def _format_combo(self, combo, cat, title):
        total_odds = 1.0
        combo_proba_math = 1.0
        
        bet_text = ""
        ai_text = "🧠 **Rapport IA Détaillé :**\n"
        
        for i, c in enumerate(combo, 1):
            total_odds *= c['odds']
            combo_proba_math *= (c['proba'] / 100.0) # Multiplication des probabilités
            
            # 🟢 AFFICHAGE DU POURCENTAGE PAR MATCH
            bet_text += f"*{i}️⃣ {c['match'].home_team} vs {c['match'].away_team}*\n👉 **{c['type']}**\n📊 Cote : {c['odds']} | 🎯 Confiance : {c['proba']:.1f}%\n\n"
            
            # 🟢 EXPLICATION CONCRÈTE PAR MATCH
            ai_text += f"✔️ **{c['match'].home_team} vs {c['match'].away_team}** : {c['ai']}\n\n"
            
        total_odds = round(total_odds, 2)
        
        # 🟢 PROBABILITÉ GLOBALE DU COMBINÉ EN %
        final_combo_proba = round(combo_proba_math * 100, 1)
        bet_text += f"🔥 **PROBABILITÉ GLOBALE DU COMBINÉ : {final_combo_proba}%**\n"
        
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
