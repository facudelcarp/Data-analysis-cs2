"""Etiquetas en español de las métricas (compartidas por la UI y la CLI)."""

STAT_LABELS = {
    "name": "Jugador", "team_name": "Equipo", "rounds": "Rondas", "demos": "Demos",
    "kills": "K", "deaths": "D", "assists": "A", "kd": "K/D", "kd_diff": "+/-", "adr": "ADR",
    "hs_pct": "HS %", "kast_pct": "KAST %", "rating2": "Rating 2.0*", "rating1": "Rating 1.0",
    "impact": "Impacto*", "opening_kills": "Entry K", "opening_deaths": "Entry D",
    "opening_success_pct": "Entry %", "trade_kills": "Tradeos", "traded_deaths": "Muertes tradeadas",
    "k2": "2K", "k3": "3K", "k4": "4K", "k5": "5K", "clutches_won": "Clutches ganados",
    "clutches": "Clutches", "utility_damage": "Daño utilidad", "utility_adr": "ADR utilidad",
    "enemies_flashed": "Enemigos flasheados", "flash_assists": "Asist. flash", "awp_kills": "Kills AWP",
    "accuracy_pct": "Precisión %", "mvps": "MVPs", "avg_equip": "Equipo prom. $", "teamkills": "TK",
    "team_damage": "Daño a aliados", "rounds_won": "Rondas ganadas", "kpr": "KPR", "dpr": "DPR",
    "survived": "Rondas sobrevividas", "grenades_thrown": "Granadas", "blind_time": "Ceguera infligida (s)",
}
SCOREBOARD_COLS = ["name", "kills", "deaths", "assists", "kd_diff", "adr", "hs_pct", "kast_pct",
                   "opening_kills", "opening_deaths", "trade_kills", "k3", "k4", "k5", "clutches_won",
                   "utility_damage", "enemies_flashed", "accuracy_pct", "rating1", "rating2"]
RATING_NOTE = ("*Rating 2.0 e Impacto son la aproximación de la comunidad (HLTV no publica la fórmula). "
               "Rating 1.0 es la fórmula oficial publicada.")
