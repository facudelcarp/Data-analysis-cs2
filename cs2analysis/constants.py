"""Constantes del juego y diccionarios de traducción (crudo -> legible)."""

TICKRATE = 64
TRADE_WINDOW_S = 5.0  # ventana estándar (HLTV/Leetify) para considerar un tradeo

SIDE_T = 2
SIDE_CT = 3
SIDES = {0: "Sin equipo", 1: "Espectador", SIDE_T: "T", SIDE_CT: "CT"}

# RoundEndReason (1-based, como lo emite el evento round_end)
ROUND_END_REASONS = {
    1: "Bomba detonada",
    2: "VIP escapó",
    3: "VIP asesinado",
    4: "Terroristas escaparon",
    5: "CT evitaron la fuga",
    6: "Terroristas neutralizados al escapar",
    7: "Bomba desactivada",
    8: "CT eliminaron a los T",
    9: "T eliminaron a los CT",
    10: "Empate",
    11: "Rehenes rescatados",
    12: "Se agotó el tiempo",
    13: "Rehenes no rescatados",
    14: "Terroristas no escaparon",
    15: "VIP no escapó",
    16: "Inicio de partida",
    17: "Rendición de los T",
    18: "Rendición de los CT",
    19: "Terroristas plantaron",
    20: "CT llegaron al rehén",
}

# Desde ~patch 14160 demoparser2 entrega round_end con motivo/ganador como texto
ROUND_END_REASON_STRINGS = {
    "bomb_exploded": 1, "target_bombed": 1, "bomb_defused": 7, "t_killed": 8, "ct_killed": 9,
    "draw": 10, "round_draw": 10, "time_ran_out": 12, "target_saved": 12, "game_start": 16,
    "game_commencing": 16, "t_surrender": 17, "terrorists_surrender": 17, "ct_surrender": 18,
    "cts_surrender": 18, "t_planted": 19,
}

HITGROUPS = {
    "generic": "Genérico",
    "head": "Cabeza",
    "chest": "Pecho",
    "stomach": "Estómago",
    "left_arm": "Brazo izq.",
    "right_arm": "Brazo der.",
    "left_leg": "Pierna izq.",
    "right_leg": "Pierna der.",
    "neck": "Cuello",
    "gear": "Equipo",
}

WEAPON_NAMES = {
    "ak47": "AK-47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S", "m4a1_silencer_off": "M4A1-S",
    "awp": "AWP", "ssg08": "SSG 08", "scar20": "SCAR-20", "g3sg1": "G3SG1",
    "aug": "AUG", "sg556": "SG 553", "famas": "FAMAS", "galilar": "Galil AR",
    "mp9": "MP9", "mac10": "MAC-10", "mp7": "MP7", "mp5sd": "MP5-SD", "ump45": "UMP-45",
    "p90": "P90", "bizon": "PP-Bizon",
    "nova": "Nova", "xm1014": "XM1014", "mag7": "MAG-7", "sawedoff": "Sawed-Off",
    "m249": "M249", "negev": "Negev",
    "glock": "Glock-18", "hkp2000": "P2000", "usp_silencer": "USP-S", "usp_silencer_off": "USP-S",
    "p250": "P250", "elite": "Dual Berettas", "fiveseven": "Five-SeveN", "tec9": "Tec-9",
    "cz75a": "CZ75-Auto", "deagle": "Desert Eagle", "revolver": "R8 Revolver",
    "taser": "Zeus x27", "knife": "Cuchillo", "knife_t": "Cuchillo", "bayonet": "Cuchillo",
    "hegrenade": "Granada HE", "flashbang": "Flash", "smokegrenade": "Humo",
    "molotov": "Molotov", "incgrenade": "Incendiaria", "inferno": "Fuego (molo/incendiaria)",
    "decoy": "Señuelo", "c4": "C4", "planted_c4": "Bomba (C4)",
    "world": "Mundo (bomba/caída)", "worldspawn": "Mundo",
}

WEAPON_CLASS = {}
for _w in ["ak47", "m4a1", "m4a1_silencer", "m4a1_silencer_off", "aug", "sg556", "famas", "galilar"]:
    WEAPON_CLASS[_w] = "Rifle"
for _w in ["awp", "ssg08", "scar20", "g3sg1"]:
    WEAPON_CLASS[_w] = "Francotirador"
for _w in ["mp9", "mac10", "mp7", "mp5sd", "ump45", "p90", "bizon"]:
    WEAPON_CLASS[_w] = "SMG"
for _w in ["nova", "xm1014", "mag7", "sawedoff"]:
    WEAPON_CLASS[_w] = "Escopeta"
for _w in ["m249", "negev"]:
    WEAPON_CLASS[_w] = "Ametralladora"
for _w in ["glock", "hkp2000", "usp_silencer", "usp_silencer_off", "p250", "elite", "fiveseven",
           "tec9", "cz75a", "deagle", "revolver"]:
    WEAPON_CLASS[_w] = "Pistola"
for _w in ["hegrenade", "flashbang", "smokegrenade", "molotov", "incgrenade", "inferno", "decoy"]:
    WEAPON_CLASS[_w] = "Utilidad"

UTILITY_DAMAGE_WEAPONS = {"hegrenade", "inferno", "molotov", "incgrenade"}

GRENADE_EVENTS = {
    "smokegrenade_detonate": "Humo",
    "flashbang_detonate": "Flash",
    "hegrenade_detonate": "Granada HE",
    "inferno_startburn": "Fuego",
    "decoy_started": "Señuelo",
}

BOMB_EVENTS = {
    "bomb_beginplant": "Empieza a plantar",
    "bomb_planted": "Bomba plantada",
    "bomb_begindefuse": "Empieza a desactivar",
    "bomb_defused": "Bomba desactivada",
    "bomb_exploded": "Bomba detonada",
    "bomb_dropped": "Bomba soltada",
    "bomb_pickup": "Bomba recogida",
}

# Clasificación de compra por valor total de equipo del equipo al terminar el freeze time
BUY_THRESHOLDS = [  # (límite superior exclusivo, etiqueta)
    (5_000, "Eco"),
    (10_000, "Semi-eco"),
    (20_000, "Force / semi-buy"),
    (float("inf"), "Full buy"),
]
BUY_ORDER = ["Pistola", "Eco", "Semi-eco", "Force / semi-buy", "Full buy"]

# Nombres de columnas de demoparser2 -> español (para "datos crudos traducidos")
COLUMN_NAMES = {
    "tick": "Tick",
    "round": "Ronda",
    "time_in_round": "Tiempo de ronda (s)",
    "attacker_name": "Atacante",
    "attacker_steamid": "SteamID atacante",
    "attacker_side": "Lado atacante",
    "attacker_place": "Zona atacante",
    "victim_name": "Víctima",
    "victim_steamid": "SteamID víctima",
    "victim_side": "Lado víctima",
    "victim_place": "Zona víctima",
    "assister_name": "Asistente",
    "weapon": "Arma",
    "weapon_class": "Tipo de arma",
    "headshot": "Headshot",
    "hitgroup": "Golpe en",
    "penetrated": "Atravesó pared",
    "thrusmoke": "A través de humo",
    "noscope": "Sin mira",
    "attackerblind": "Atacante cegado",
    "assistedflash": "Asistencia con flash",
    "distance": "Distancia (m)",
    "is_opening": "Primera kill de la ronda",
    "is_trade": "Fue tradeo",
    "was_traded": "Muerte tradeada",
    "is_teamkill": "Teamkill",
    "is_suicide": "Suicidio",
    "dmg_health": "Daño a vida",
    "dmg_health_raw": "Daño bruto (sin tope)",
    "dmg_armor": "Daño a armadura",
    "health": "Vida restante",
    "armor": "Armadura restante",
    "player_name": "Jugador",
    "steamid": "SteamID",
    "name": "Jugador",
    "side": "Lado",
    "place": "Zona",
    "grenade": "Granada",
    "blind_duration": "Duración ceguera (s)",
    "is_enemy": "Es enemigo",
    "event": "Evento",
    "site": "Sitio",
    "winner_side": "Lado ganador",
    "winner_team": "Equipo ganador",
    "reason": "Motivo",
    "start_tick": "Tick inicio",
    "freeze_end_tick": "Tick fin freeze",
    "end_tick": "Tick fin",
    "duration_s": "Duración (s)",
    "score_a": "Marcador A",
    "score_b": "Marcador B",
    "ct_team": "Equipo CT",
    "t_team": "Equipo T",
    "ct_equip": "Equipo CT ($)",
    "t_equip": "Equipo T ($)",
    "ct_buy": "Compra CT",
    "t_buy": "Compra T",
    "bomb_planted": "Bomba plantada",
    "bomb_site": "Sitio bomba",
    "team": "Equipo",
    "equip_value": "Valor equipo ($)",
    "balance": "Dinero ($)",
    "cash_spent": "Gastado ($)",
    "armor_value": "Armadura",
    "has_helmet": "Casco",
    "has_defuser": "Kit",
    "x": "X", "y": "Y", "z": "Z",
}
