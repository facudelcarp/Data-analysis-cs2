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

MICRO_LABELS = {
    "name": "Jugador", "duels_won": "Duelos ganados", "duels_lost": "Duelos perdidos",
    "ttd_ms": "TTD (ms)", "reaction_ms": "Reacción (ms)", "ttk_ms": "TTK (ms)",
    "crosshair_deg": "Crosshair placement (°)", "crosshair_pitch_deg": "Error vertical (°)",
    "preaim_pct": "Pre-aim %", "flick_pct": "Flick %", "prefire_pct": "Prefire %",
    "peak_ang_speed": "Vel. angular pico (°/s)", "shots_per_kill": "Disparos por kill",
    "time_to_death_ms": "Tiempo hasta morir (ms)", "caught_off_angle_pct": "Agarrado mal parado %",
    "shot_back_pct": "Contestó el duelo %", "shots": "Disparos", "shot_accuracy_pct": "Precisión %",
    "first_bullet_acc_pct": "Precisión 1ª bala %", "spray_acc_pct": "Precisión spray (4+) %",
    "hs_per_hit_pct": "HS por impacto %", "counter_strafe_pct": "Counter-strafe %",
    "speed_at_shot": "Velocidad al disparar (u/s)",
    "no_los_kill_pct": "Kills sin línea de visión %", "wallbang_kills": "Kills por wallbang",
    "inhuman_snaps": "Snaps inhumanos (≥30° en ≤100 ms)",
}
STAT_LABELS.update({k: v for k, v in MICRO_LABELS.items() if k not in STAT_LABELS})

MICRO_COLS = ["name", "duels_won", "ttd_ms", "reaction_ms", "crosshair_deg", "crosshair_pitch_deg", "preaim_pct",
              "flick_pct", "prefire_pct", "ttk_ms", "shots_per_kill", "counter_strafe_pct", "first_bullet_acc_pct",
              "spray_acc_pct", "hs_per_hit_pct", "caught_off_angle_pct", "shot_back_pct", "time_to_death_ms", "no_los_kill_pct",
              "wallbang_kills", "inhuman_snaps"]
MICRO_NOTE = ("Medianas por duelo ganado. TTD = desde que hay línea de visión hasta el primer daño; crosshair placement = "
              "ángulo entre la mira y la cabeza del rival en ese instante. Menos es mejor en ms y °.")
