"""Vista: Replay 2D animado de la ronda sobre el mapa de radar.

Renderiza un canvas interactivo a 60 FPS con:
- Movimiento fluido de jugadores (interpolación lineal entre ticks)
- Visión / dirección hacia donde apuntan o se desplazan
- Barras de vida y estado vivo/muerto en tiempo real
- Kill feed dinámico y trazadores de disparo en duelos
- Granadas (humos expansivos con duración de 20s, molotovs)
- Estado de la bomba (en tránsito, plantada con cuenta regresiva de 40s, defuse, detonación)
- Filtro por tipo de compra económica (Full buy vs Full buy, Eco vs Full buy, Force vs Force, etc.)
- Controles de reproducción: Play/Pausa, scrubber arrastrable, velocidades (0.5x, 1x, 2x, 4x)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from .. import stats
from ..constants import BUY_ORDER, BUY_THRESHOLDS
from ..maps import map_info, pretty_map, radar_image
from ..translate import weapon_name
from . import charts, common as ui


def render(d) -> None:
    st.subheader("🎬 Replay 2D interactivo")
    if d.positions.empty:
        st.warning("Esta demo no tiene posiciones registradas (se cargó sin muestreo de ticks).")
        return

    rt = stats.round_timeline(d)
    if rt.empty:
        st.warning("No se encontraron rondas.")
        return

    teams = {"A": d.meta["team_a"], "B": d.meta["team_b"]}

    # Clasificar todas las compras y armar las variables de enfrentamiento
    tagged_rt = _tag_round_buys(rt, teams)
    filter_options = _build_filter_options(tagged_rt)

    # 1. Filtro por tipo de compra
    c_filter, c_lvl = st.columns([3, 1])
    filter_keys = list(filter_options.keys())
    
    # Manejo de estado del filtro
    saved_filter = st.session_state.get("replay_buy_filter", filter_keys[0])
    filter_idx = filter_keys.index(saved_filter) if saved_filter in filter_keys else 0
    selected_filter = c_filter.selectbox(
        "Filtrar rondas por tipo de compra",
        filter_keys,
        index=filter_idx,
        key="replay_buy_filter"
    )
    
    with c_lvl:
        lower = ui.level_selector(d.meta["map"], "replay_level")
        ui.radar_hint(d.meta["map"], "radar_dl_replay")

    # Rondas elegibles según el filtro
    eligible_rounds = filter_options[selected_filter]
    if not eligible_rounds:
        st.warning("No hay rondas para este tipo de compra.")
        return

    # 2. Selector de ronda y botones Anterior / Siguiente
    if "replay_round_sel" not in st.session_state or st.session_state["replay_round_sel"] not in eligible_rounds:
        st.session_state["replay_round_sel"] = eligible_rounds[0]

    current_round = st.session_state["replay_round_sel"]
    curr_idx = eligible_rounds.index(current_round)

    c_prev, c_sel, c_next = st.columns([0.7, 2.6, 0.7])
    if c_prev.button("◀ Anterior", disabled=(curr_idx <= 0), key="replay_btn_prev", width="stretch"):
        st.session_state["replay_round_sel"] = eligible_rounds[curr_idx - 1]
        st.rerun()

    def _round_label(r: int) -> str:
        row = tagged_rt[tagged_rt["round"] == r].iloc[0]
        win = teams.get(row["winner_team"], row["winner_team"])
        score_a, score_b = row["score_a"], row["score_b"]
        matchup = row.get("matchup_simp", "")
        return f"Ronda {r} · Gana {win} ({score_a}-{score_b}) — {matchup}"

    sel_round = c_sel.selectbox(
        "Ronda a reproducir",
        eligible_rounds,
        index=curr_idx,
        format_func=_round_label,
        key="replay_round_sel"
    )

    if c_next.button("Siguiente ▶", disabled=(curr_idx >= len(eligible_rounds) - 1), key="replay_btn_next", width="stretch"):
        st.session_state["replay_round_sel"] = eligible_rounds[curr_idx + 1]
        st.rerun()

    # Fila de contexto económico de la ronda
    round_info = tagged_rt[tagged_rt["round"] == sel_round].iloc[0]
    _render_economy_banner(round_info, teams)

    # 3. Preparar datos y renderizar el Canvas Replay
    payload = _build_replay_payload(d, sel_round, round_info, teams, lower=lower)
    if not payload:
        st.info("Sin datos de posiciones para esta ronda.")
        return

    html_code = _generate_player_html(payload)
    if hasattr(st, "iframe"):  # st.components.v1.html está deprecado y se elimina en versiones nuevas
        st.iframe(html_code, height=880)
    else:
        components.html(html_code, height=880, scrolling=False)
    charts.explain(f"reproduciendo Ronda {sel_round} ({round_info.get('matchup_simp', '')}). Puntos azules = CT, "
                   "naranjas = T. Hacé clic en ▶ para reproducir o arrastrá la barra para ir al momento de un duelo.")


def _tag_round_buys(rt: pd.DataFrame, teams: dict[str, str]) -> pd.DataFrame:
    """Clasifica y etiqueta cada ronda con todas las variables de compra de CS2."""
    df = rt.copy()

    def simplify(b: str) -> str:
        if not b or pd.isna(b):
            return "Sin dato"
        b_str = str(b)
        if "Force" in b_str:
            return "Force"
        if "Eco" in b_str:
            return "Eco"
        return b_str  # "Full buy", "Pistola"

    sim_rank = {"Full buy": 4, "Force": 3, "Eco": 2, "Pistola": 1, "Sin dato": 0}
    can_rank = {"Full buy": 4, "Force / semi-buy": 3, "Semi-eco": 2, "Eco": 1, "Pistola": 0}

    matchup_simp = []
    matchup_exact = []
    matchup_side = []
    matchup_team = []

    for _, r in df.iterrows():
        ct_b = str(r.get("ct_buy", "Sin dato"))
        t_b = str(r.get("t_buy", "Sin dato"))
        ct_t = str(r.get("ct_team", "A"))
        t_t = str(r.get("t_team", "B"))
        name_ct = teams.get(ct_t, f"Equipo {ct_t}")
        name_t = teams.get(t_t, f"Equipo {t_t}")

        s_ct, s_t = simplify(ct_b), simplify(t_b)

        # 1. Enfrentamiento simétrico simplificado (ej: "Full buy vs Eco")
        if sim_rank.get(s_ct, 0) >= sim_rank.get(s_t, 0):
            ms = f"{s_ct} vs {s_t}"
        else:
            ms = f"{s_t} vs {s_ct}"
        matchup_simp.append(ms)

        # 2. Enfrentamiento simétrico exacto con umbrales de dinero
        if can_rank.get(ct_b, 0) >= can_rank.get(t_b, 0):
            me = f"{ct_b} vs {t_b}"
        else:
            me = f"{t_b} vs {ct_b}"
        matchup_exact.append(me)

        # 3. Enfrentamiento por lado específico (ej: "CT Full buy vs T Eco")
        matchup_side.append(f"CT {s_ct} vs T {s_t}")

        # 4. Enfrentamiento por equipo (ej: "Equipo A (Full buy) vs Equipo B (Eco)")
        buy_a = ct_b if ct_t == "A" else t_b
        buy_b = t_b if ct_t == "A" else ct_b
        matchup_team.append(f"{name_ct} ({s_ct}) vs {name_t} ({s_t})")

    df["matchup_simp"] = matchup_simp
    df["matchup_exact"] = matchup_exact
    df["matchup_side"] = matchup_side
    df["matchup_team"] = matchup_team
    return df


def _build_filter_options(df: pd.DataFrame) -> dict[str, list[int]]:
    """Arma el diccionario de filtros agrupados por todas las variables de compra que ocurrieron."""
    out: dict[str, list[int]] = {}
    total_rounds = df["round"].tolist()
    out[f"Todas las rondas ({len(total_rounds)})"] = total_rounds

    # Enfrentamientos estándar simétricos (Full buy vs Full buy, Full buy vs Eco, etc.)
    preferred_order = [
        "Full buy vs Full buy",
        "Full buy vs Force",
        "Full buy vs Eco",
        "Force vs Force",
        "Force vs Eco",
        "Eco vs Eco",
        "Pistola vs Pistola",
    ]
    for key in preferred_order:
        rnds = df.loc[df["matchup_simp"] == key, "round"].tolist()
        if rnds:
            out[f"⚔️ {key} ({len(rnds)} rondas)"] = rnds

    # Enfrentamientos por lado específico (CT vs T)
    for key, group in df.groupby("matchup_side"):
        rnds = group["round"].tolist()
        label = f"🛡️ {key} ({len(rnds)} rondas)"
        if label not in out:
            out[label] = rnds

    # Enfrentamientos exactos si diferencian Semi-eco de Eco
    for key, group in df.groupby("matchup_exact"):
        if "Semi-eco" in key:
            rnds = group["round"].tolist()
            label = f"💵 {key} ({len(rnds)} rondas)"
            if label not in out:
                out[label] = rnds

    return out


def _render_economy_banner(row: pd.Series, teams: dict[str, str]) -> None:
    """Muestra tarjetas con los valores de equipo y el tipo de enfrentamiento de la ronda."""
    ct_buy = str(row.get("ct_buy", ""))
    t_buy = str(row.get("t_buy", ""))
    ct_equip = int(row.get("ct_equip", 0))
    t_equip = int(row.get("t_equip", 0))
    matchup = str(row.get("matchup_simp", ""))
    ct_team = teams.get(str(row.get("ct_team", "")), "CT")
    t_team = teams.get(str(row.get("t_team", "")), "T")

    c1, c2, c3 = st.columns(3)
    c1.markdown(
        f"<div style='border:1px solid rgba(57,135,229,0.3);background:rgba(57,135,229,0.08);border-radius:6px;padding:6px 10px;'>"
        f"<span style='font-size:0.75rem;color:#3987e5;font-weight:700;'>🛡️ CT ({ct_team})</span>"
        f"<div style='font-size:1.05rem;font-weight:700;'>{ct_buy} · ${ct_equip:,.0f}</div></div>",
        unsafe_allow_html=True
    )
    c2.markdown(
        f"<div style='border:1px solid rgba(217,89,38,0.3);background:rgba(217,89,38,0.08);border-radius:6px;padding:6px 10px;'>"
        f"<span style='font-size:0.75rem;color:#d95926;font-weight:700;'>💣 T ({t_team})</span>"
        f"<div style='font-size:1.05rem;font-weight:700;'>{t_buy} · ${t_equip:,.0f}</div></div>",
        unsafe_allow_html=True
    )
    # Contexto de paridad económica
    diff = ct_equip - t_equip
    if abs(diff) < 6_000 and "Full" in matchup:
        context = "⚔️ Compras parejas (full buy vs full buy)"
    elif diff > 8_000:
        context = "📈 Ventaja de equipamiento para CT"
    elif diff < -8_000:
        context = "📉 Ventaja de equipamiento para T"
    else:
        context = f"Duelo económico: {matchup}"

    c3.markdown(
        f"<div style='border:1px solid rgba(255,255,255,0.1);background:#191918;border-radius:6px;padding:6px 10px;'>"
        f"<span style='font-size:0.75rem;color:#c3c2b7;font-weight:700;'>SITUACIÓN</span>"
        f"<div style='font-size:0.95rem;font-weight:600;margin-top:2px;'>{context}</div></div>",
        unsafe_allow_html=True
    )


def _build_replay_payload(d, round_num: int, round_info, teams: dict[str, str], lower: bool = False) -> dict | None:
    map_name = d.meta["map"]
    info = map_info(map_name)

    # Posiciones de la ronda
    pos = d.positions[d.positions["round"] == round_num].copy()
    if pos.empty:
        return None

    # Función de conversión a radar (0..1024)
    if info:
        def to_radar(x, y):
            rx, ry = info.to_radar(x, y)
            return float(rx), float(ry)
    else:
        min_x, max_x = d.positions["x"].min(), d.positions["x"].max()
        min_y, max_y = d.positions["y"].min(), d.positions["y"].max()
        dx = max(max_x - min_x, 1)
        dy = max(max_y - min_y, 1)
        def to_radar(x, y):
            rx = 60 + 904 * (x - min_x) / dx
            ry = 964 - 904 * (y - min_y) / dy
            return float(rx), float(ry)

    # Imagen de radar en base64
    img_path = radar_image(map_name, lower=lower) or radar_image(map_name, lower=False)
    radar_b64 = ""
    if img_path and Path(img_path).exists():
        radar_b64 = f"data:image/png;base64,{base64.b64encode(Path(img_path).read_bytes()).decode('ascii')}"

    # Tiempos de inicio y fin
    t_min = float(pos["time_in_round"].min())
    t_max = float(pos["time_in_round"].max())

    # Roster de jugadores
    players_data = []
    for sid, group in pos.groupby("steamid"):
        first = group.iloc[0]
        players_data.append({
            "steamid": sid,
            "name": str(first["name"]),
            "side": str(first["side"]),
            "team": str(first["team"])
        })

    # Trayectorias por jugador
    positions_by_player = {}
    for sid, group in pos.groupby("steamid"):
        sorted_grp = group.sort_values("time_in_round")
        traj = []
        for _, row in sorted_grp.iterrows():
            rx, ry = to_radar(row["x"], row["y"])
            traj.append({
                "t": round(float(row["time_in_round"]), 2),
                "x": round(rx, 1),
                "y": round(ry, 1),
                "hp": int(row["health"])
            })
        positions_by_player[sid] = traj

    # Kills de la ronda
    kills_data = []
    k_round = d.kills[d.kills["round"] == round_num] if not d.kills.empty else pd.DataFrame()
    for _, k in k_round.iterrows():
        ax, ay = to_radar(k["attacker_x"], k["attacker_y"]) if pd.notna(k["attacker_x"]) else (None, None)
        vx, vy = to_radar(k["victim_x"], k["victim_y"]) if pd.notna(k["victim_x"]) else (None, None)
        kills_data.append({
            "t": round(float(k["time_in_round"]), 2),
            "attacker": str(k["attacker_name"]),
            "attacker_side": str(k["attacker_side"]),
            "attacker_sid": str(k["attacker_steamid"]),
            "victim": str(k["victim_name"]),
            "victim_side": str(k["victim_side"]),
            "victim_sid": str(k["victim_steamid"]),
            "weapon": weapon_name(str(k["weapon"])),
            "headshot": bool(k["headshot"]),
            "ax": round(ax, 1) if ax is not None else None,
            "ay": round(ay, 1) if ay is not None else None,
            "vx": round(vx, 1) if vx is not None else None,
            "vy": round(vy, 1) if vy is not None else None,
        })

    # Eventos de bomba
    bomb_data = []
    b_round = d.bomb[d.bomb["round"] == round_num] if not d.bomb.empty else pd.DataFrame()
    for _, b in b_round.iterrows():
        bx, by = to_radar(b["player_x"], b["player_y"]) if pd.notna(b["player_x"]) else (None, None)
        bomb_data.append({
            "t": round(float(b["time_in_round"]), 2),
            "event": str(b["event_code"]),
            "site": str(b.get("site_letter", "")),
            "player": str(b.get("player_name", "")),
            "x": round(bx, 1) if bx is not None else None,
            "y": round(by, 1) if by is not None else None,
        })

    # Granadas
    grenades_data = []
    g_round = d.grenades[d.grenades["round"] == round_num] if not d.grenades.empty else pd.DataFrame()
    for _, g in g_round.iterrows():
        gx, gy = to_radar(g["x"], g["y"]) if pd.notna(g["x"]) else (None, None)
        grenades_data.append({
            "t": round(float(g["time_in_round"]), 2),
            "type": str(g["grenade"]),
            "thrower": str(g.get("thrower_name", "")),
            "side": str(g.get("thrower_side", "")),
            "x": round(gx, 1) if gx is not None else None,
            "y": round(gy, 1) if gy is not None else None,
        })

    # Ceguera por flashes
    blinds_data = []
    b_round = d.blinds[d.blinds["round"] == round_num] if not d.blinds.empty else pd.DataFrame()
    for _, b in b_round.iterrows():
        blinds_data.append({
            "t": round(float(b["time_in_round"]), 2),
            "sid": str(b.get("victim_steamid", "")),
            "dur": round(float(b.get("blind_duration", 0)), 2),
        })

    return {
        "map": map_name,
        "round": round_num,
        "score_a": int(round_info["score_a"]) if round_info is not None else 0,
        "score_b": int(round_info["score_b"]) if round_info is not None else 0,
        "winner_team": teams.get(round_info["winner_team"], "") if round_info is not None else "",
        "winner_side": str(round_info["winner_side"]) if round_info is not None else "",
        "reason": str(round_info["reason"]) if round_info is not None else "",
        "ct_buy": str(round_info["ct_buy"]) if round_info is not None and "ct_buy" in round_info else "",
        "t_buy": str(round_info["t_buy"]) if round_info is not None and "t_buy" in round_info else "",
        "ct_equip": int(round_info["ct_equip"]) if round_info is not None and "ct_equip" in round_info else 0,
        "t_equip": int(round_info["t_equip"]) if round_info is not None and "t_equip" in round_info else 0,
        "matchup": str(round_info.get("matchup_simp", "")),
        "tMin": t_min,
        "tMax": max(t_max, t_min + 1),
        "radarImage": radar_b64,
        "hasRadar": bool(radar_b64),
        "players": players_data,
        "positions": positions_by_player,
        "kills": kills_data,
        "bomb": bomb_data,
        "grenades": grenades_data,
        "blinds": blinds_data,
    }


def _generate_player_html(payload: dict) -> str:
    """Genera el HTML5 Canvas interactivo con el reproductor 2D embebido."""
    json_str = json.dumps(payload).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0f0f0e;
    color: #f0efec;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    user-select: none;
    overflow: hidden;
  }}
  .replay-container {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 6px 10px;
    max-width: 1040px;
    margin: 0 auto;
  }}
  /* Header / Marcador */
  .hud-top {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #191918;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 13px;
  }}
  .team-alive-badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-weight: 700;
    font-size: 13px;
    padding: 3px 10px;
    border-radius: 6px;
  }}
  .badge-ct {{ background: rgba(57, 135, 229, 0.2); color: #3987e5; border: 1px solid rgba(57, 135, 229, 0.4); }}
  .badge-t  {{ background: rgba(217, 89, 38, 0.2); color: #d95926; border: 1px solid rgba(217, 89, 38, 0.4); }}
  .buy-label {{
    font-size: 11px;
    font-weight: 500;
    opacity: 0.85;
  }}
  .hud-timer {{
    font-family: ui-monospace, monospace;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.5px;
    color: #ffd166;
  }}

  /* Layout principal */
  .stage {{
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }}
  .canvas-wrapper {{
    position: relative;
    background: #141413;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.12);
    overflow: hidden;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    width: 740px;
    height: 740px;
    flex-shrink: 0;
  }}
  .zoom-controls {{
    position: absolute;
    top: 10px;
    right: 10px;
    display: flex;
    gap: 4px;
    background: rgba(20, 20, 19, 0.88);
    backdrop-filter: blur(4px);
    border: 1px solid rgba(255, 255, 255, 0.16);
    border-radius: 6px;
    padding: 3px 6px;
    z-index: 10;
  }}
  .zoom-btn {{
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.12);
    color: #f0efec;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 8px;
    border-radius: 4px;
    cursor: pointer;
    transition: background 0.15s;
    user-select: none;
  }}
  .zoom-btn:hover {{
    background: rgba(255, 255, 255, 0.20);
    color: #ffffff;
  }}
  canvas {{
    width: 100%;
    height: 100%;
    display: block;
    user-select: none;
  }}

  /* Sidebar con jugadores y KillFeed */
  .sidebar {{
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 10px;
    height: 740px;
  }}
  .roster-card {{
    background: #191918;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .roster-title {{
    font-size: 11px;
    text-transform: uppercase;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
  }}
  .player-row {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 12px;
    padding: 3px 5px;
    border-radius: 4px;
    background: rgba(255,255,255,0.02);
    cursor: pointer;
    transition: background 0.15s;
  }}
  .player-row:hover {{
    background: rgba(255,255,255,0.08);
  }}
  .player-row.selected {{
    border: 1px solid #ffd166;
    background: rgba(255, 209, 102, 0.12);
  }}
  .player-row.dead {{
    opacity: 0.35;
    filter: grayscale(1);
    text-decoration: line-through;
  }}
  .hp-bar-bg {{
    width: 50px;
    height: 5px;
    background: rgba(255,255,255,0.1);
    border-radius: 3px;
    overflow: hidden;
  }}
  .hp-bar-fill {{
    height: 100%;
    transition: width 0.15s ease-out;
  }}
  .hp-ct {{ background: #3987e5; }}
  .hp-t  {{ background: #d95926; }}

  /* Feed */
  .feed-box {{
    flex: 1;
    background: #191918;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 8px 10px;
    overflow-y: auto;
    font-size: 11px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .feed-item {{
    padding: 3px 6px;
    border-radius: 4px;
    background: rgba(0,0,0,0.3);
    border-left: 3px solid #ffd166;
  }}

  /* Controles */
  .controls-bar {{
    display: flex;
    align-items: center;
    gap: 8px;
    background: #191918;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 8px;
    padding: 8px 12px;
  }}
  .btn {{
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.12);
    color: #f0efec;
    padding: 5px 10px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    transition: all 0.15s;
    white-space: nowrap;
  }}
  .btn:hover {{ background: rgba(255,255,255,0.18); }}
  .btn-play {{ background: #2a78d6; border-color: #3987e5; min-width: 40px; }}
  .btn-play:hover {{ background: #3987e5; }}
  .speed-pill {{
    padding: 3px 7px;
    font-size: 11px;
    border-radius: 4px;
    cursor: pointer;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.08);
  }}
  .speed-pill.active {{
    background: #ffd166;
    color: #1a1a19;
    font-weight: 700;
  }}
  .timeline {{
    flex: 1;
    cursor: pointer;
    accent-color: #ffd166;
  }}
  .opt-label {{
    font-size: 11px;
    color: #c3c2b7;
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    white-space: nowrap;
  }}
</style>
</head>
<body>

<div class="replay-container">
  <!-- Marcador / HUD superior con compras de ambos equipos -->
  <div class="hud-top">
    <div class="team-alive-badge badge-ct">
      🛡️ CT &nbsp;<span id="alive-ct">5</span>
      <span class="buy-label" id="hud-ct-buy"></span>
    </div>
    <div style="text-align: center;">
      <span style="font-weight:700; font-size:14px; margin-right:8px;" id="round-title">Ronda</span>
      <span class="hud-timer" id="timer-display">0:00</span>
    </div>
    <div class="team-alive-badge badge-t">
      <span class="buy-label" id="hud-t-buy"></span>
      <span id="alive-t">5</span>&nbsp; T 💣
    </div>
  </div>

  <!-- Escenario: Canvas + Sidebar -->
  <div class="stage">
    <div class="canvas-wrapper">
      <div class="zoom-controls">
        <button class="zoom-btn" id="btn-zoom-in" title="Acercar (o rueda del ratón)">🔍 +</button>
        <button class="zoom-btn" id="btn-zoom-out" title="Alejar (o rueda del ratón)">🔍 -</button>
        <button class="zoom-btn" id="btn-zoom-reset" title="Restablecer zoom">⟲ <span id="zoom-level">100%</span></button>
      </div>
      <canvas id="replay-canvas" width="1024" height="1024"></canvas>
    </div>

    <div class="sidebar">
      <div class="roster-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="roster-title" style="color: #3987e5;">Counter-Terrorists</span>
          <span style="font-size:10px; color:#888;">clic para estela</span>
        </div>
        <div id="roster-ct"></div>
      </div>

      <div class="roster-card">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span class="roster-title" style="color: #d95926;">Terrorists</span>
          <span style="font-size:10px; color:#888;">clic para estela</span>
        </div>
        <div id="roster-t"></div>
      </div>

      <div class="feed-box">
        <div style="font-size:11px; font-weight:700; color:#c3c2b7; margin-bottom:4px;">Kill feed</div>
        <div id="kill-feed-list"></div>
      </div>
    </div>
  </div>

  <!-- Barra de control inferior -->
  <div class="controls-bar">
    <button class="btn btn-play" id="btn-toggle" title="Espacio para Play/Pausa">▶</button>
    <button class="btn" id="btn-restart" title="Reiniciar">⏮</button>
    <button class="btn" id="btn-jump-kill" title="Ir a la primera baja">⚡ 1ª Kill</button>
    <button class="btn" id="btn-jump-plant" title="Ir al plantado de bomba">💣 Planta</button>
    <input type="range" class="timeline" id="timeline" min="0" max="100" step="0.1" value="0">
    <span id="time-indicator" style="font-size:12px; font-family:monospace; min-width:85px; color:#c3c2b7;">0:00 / 0:00</span>
    
    <div style="display: flex; gap: 3px;">
      <button class="speed-pill" data-speed="0.5">0.5x</button>
      <button class="speed-pill active" data-speed="1.0">1x</button>
      <button class="speed-pill" data-speed="2.0">2x</button>
      <button class="speed-pill" data-speed="4.0">4x</button>
    </div>

    <label class="opt-label"><input type="checkbox" id="chk-names" checked> Nombres</label>
    <label class="opt-label"><input type="checkbox" id="chk-trails" checked> Estela</label>
    <label class="opt-label"><input type="checkbox" id="chk-smokes" checked> Granadas</label>
  </div>
</div>

<script>
const DATA = {json_str};

const canvas = document.getElementById('replay-canvas');
const ctx = canvas.getContext('2d');
const btnToggle = document.getElementById('btn-toggle');
const btnRestart = document.getElementById('btn-restart');
const timeline = document.getElementById('timeline');
const timeIndicator = document.getElementById('time-indicator');
const timerDisplay = document.getElementById('timer-display');
const aliveCTElem = document.getElementById('alive-ct');
const aliveTElem = document.getElementById('alive-t');
const hudCtBuy = document.getElementById('hud-ct-buy');
const hudTBuy = document.getElementById('hud-t-buy');
const rosterCT = document.getElementById('roster-ct');
const rosterT = document.getElementById('roster-t');
const killFeedList = document.getElementById('kill-feed-list');
// Los nombres vienen de la demo y se insertan con innerHTML: un nick puede ser HTML.
const esc = (v) => String(v).replace(/[&<>"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}})[c]);
const chkNames = document.getElementById('chk-names');
const chkSmokes = document.getElementById('chk-smokes');

// Mostrar economía en el HUD superior
if (DATA.ct_buy) {{
  hudCtBuy.textContent = `(${{DATA.ct_buy}} · $${{(DATA.ct_equip/1000).toFixed(0)}}k)`;
}}
if (DATA.t_buy) {{
  hudTBuy.textContent = `(${{DATA.t_buy}} · $${{(DATA.t_equip/1000).toFixed(0)}}k)`;
}}

// Imagen del radar
let radarImg = null;
if (DATA.hasRadar && DATA.radarImage) {{
  radarImg = new Image();
  radarImg.src = DATA.radarImage;
}}

let isPlaying = false;
let currentTime = Math.max(0, DATA.tMin);
let playbackSpeed = 1.0;
let lastTimestamp = null;

timeline.min = DATA.tMin;
timeline.max = DATA.tMax;
timeline.value = currentTime;
document.getElementById('round-title').textContent = `Ronda ${{DATA.round}} · ${{DATA.score_a}} - ${{DATA.score_b}}`;

// Setup de velocidad
document.querySelectorAll('.speed-pill').forEach(pill => {{
  pill.addEventListener('click', () => {{
    document.querySelectorAll('.speed-pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    playbackSpeed = parseFloat(pill.dataset.speed);
  }});
}});

// Controles
function togglePlay() {{
  isPlaying = !isPlaying;
  btnToggle.textContent = isPlaying ? '⏸' : '▶';
  if (isPlaying) {{
    lastTimestamp = performance.now();
    requestAnimationFrame(renderLoop);
  }}
}}
btnToggle.addEventListener('click', togglePlay);

btnRestart.addEventListener('click', () => {{
  currentTime = Math.max(0, DATA.tMin);
  timeline.value = currentTime;
  drawFrame(currentTime);
}});

timeline.addEventListener('input', (e) => {{
  currentTime = parseFloat(e.target.value);
  drawFrame(currentTime);
}});

window.addEventListener('keydown', (e) => {{
  if (e.code === 'Space') {{
    e.preventDefault();
    togglePlay();
  }} else if (e.code === 'ArrowRight') {{
    currentTime = Math.min(DATA.tMax, currentTime + 3);
    timeline.value = currentTime;
    drawFrame(currentTime);
  }} else if (e.code === 'ArrowLeft') {{
    currentTime = Math.max(DATA.tMin, currentTime - 3);
    timeline.value = currentTime;
    drawFrame(currentTime);
  }}
}});

const btnJumpKill = document.getElementById('btn-jump-kill');
const btnJumpPlant = document.getElementById('btn-jump-plant');
const chkTrails = document.getElementById('chk-trails');

const btnZoomIn = document.getElementById('btn-zoom-in');
const btnZoomOut = document.getElementById('btn-zoom-out');
const btnZoomReset = document.getElementById('btn-zoom-reset');
const zoomLevelText = document.getElementById('zoom-level');

let zoomScale = 1.0;
let panX = 0;
let panY = 0;
let isPanning = false;
let startPanMouseX = 0;
let startPanMouseY = 0;
let hasDragged = false;

function clampPan() {{
  const maxPanX = 0;
  const minPanX = 1024 * (1 - zoomScale);
  const maxPanY = 0;
  const minPanY = 1024 * (1 - zoomScale);
  panX = Math.min(maxPanX, Math.max(minPanX, panX));
  panY = Math.min(maxPanY, Math.max(minPanY, panY));
}}

function setZoom(newScale, focalX = 512, focalY = 512) {{
  const clamped = Math.max(1.0, Math.min(4.0, newScale));
  if (clamped <= 1.01) {{
    zoomScale = 1.0;
    panX = 0;
    panY = 0;
  }} else {{
    const factor = clamped / zoomScale;
    panX = focalX - (focalX - panX) * factor;
    panY = focalY - (focalY - panY) * factor;
    zoomScale = clamped;
    clampPan();
  }}
  if (zoomLevelText) {{
    zoomLevelText.textContent = Math.round(zoomScale * 100) + '%';
  }}
  canvas.style.cursor = zoomScale > 1.0 ? 'grab' : 'default';
  drawFrame(currentTime);
}}

if (btnZoomIn) btnZoomIn.addEventListener('click', () => setZoom(zoomScale + 0.35, 512, 512));
if (btnZoomOut) btnZoomOut.addEventListener('click', () => setZoom(zoomScale - 0.35, 512, 512));
if (btnZoomReset) btnZoomReset.addEventListener('click', () => setZoom(1.0));

canvas.addEventListener('wheel', (e) => {{
  e.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const mouseScreenX = (e.clientX - rect.left) * (1024 / rect.width);
  const mouseScreenY = (e.clientY - rect.top) * (1024 / rect.height);
  const zoomDelta = e.deltaY < 0 ? 0.3 : -0.3;
  setZoom(zoomScale + zoomDelta, mouseScreenX, mouseScreenY);
}}, {{ passive: false }});

canvas.addEventListener('mousedown', (e) => {{
  if (e.button === 0 && zoomScale > 1.0) {{
    isPanning = true;
    hasDragged = false;
    startPanMouseX = e.clientX;
    startPanMouseY = e.clientY;
    canvas.style.cursor = 'grabbing';
  }}
}});

window.addEventListener('mousemove', (e) => {{
  if (isPanning) {{
    const rect = canvas.getBoundingClientRect();
    const scale = 1024 / rect.width;
    const dx = (e.clientX - startPanMouseX) * scale;
    const dy = (e.clientY - startPanMouseY) * scale;
    if (Math.hypot(dx, dy) > 4) {{
      hasDragged = true;
    }}
    panX += dx;
    panY += dy;
    startPanMouseX = e.clientX;
    startPanMouseY = e.clientY;
    clampPan();
    drawFrame(currentTime);
  }}
}});

window.addEventListener('mouseup', () => {{
  if (isPanning) {{
    isPanning = false;
    canvas.style.cursor = zoomScale > 1.0 ? 'grab' : 'default';
  }}
}});

canvas.addEventListener('dblclick', () => {{
  if (zoomScale > 1.0) setZoom(1.0);
  else setZoom(2.0, 512, 512);
}});

[chkNames, chkSmokes, chkTrails].forEach(chk => {{
  if (chk) chk.addEventListener('change', () => drawFrame(currentTime));
}});

let selectedPlayerId = null;

// Salto a eventos clave
btnJumpKill.addEventListener('click', () => {{
  if (DATA.kills && DATA.kills.length > 0) {{
    currentTime = Math.max(DATA.tMin, DATA.kills[0].t - 1.5);
    timeline.value = currentTime;
    drawFrame(currentTime);
  }}
}});

btnJumpPlant.addEventListener('click', () => {{
  const plant = DATA.bomb ? DATA.bomb.find(b => b.event === 'bomb_planted') : null;
  if (plant) {{
    currentTime = Math.max(DATA.tMin, plant.t - 2.0);
    timeline.value = currentTime;
    drawFrame(currentTime);
  }}
}});

function selectPlayer(sid) {{
  if (!sid || selectedPlayerId === sid) {{
    selectedPlayerId = null;
  }} else {{
    selectedPlayerId = sid;
  }}
  drawFrame(currentTime);
}}
window.selectPlayer = selectPlayer;

// Clic en el canvas para seleccionar jugador
canvas.addEventListener('click', (e) => {{
  if (hasDragged) {{
    hasDragged = false;
    return;
  }}
  const rect = canvas.getBoundingClientRect();
  const scaleX = 1024 / rect.width;
  const scaleY = 1024 / rect.height;
  const screenX = (e.clientX - rect.left) * scaleX;
  const screenY = (e.clientY - rect.top) * scaleY;
  const clickX = (screenX - panX) / zoomScale;
  const clickY = (screenY - panY) / zoomScale;

  let clickedSid = null;
  DATA.players.forEach(p => {{
    const st = getPlayerState(p.steamid, currentTime);
    if (st) {{
      const dist = Math.hypot(st.x - clickX, st.y - clickY);
      if (dist <= 22) {{
        clickedSid = p.steamid;
      }}
    }}
  }});
  selectPlayer(clickedSid);
}});

// Interpolación de posición para un jugador en tiempo t
function getPlayerState(sid, t) {{
  const samples = DATA.positions[sid];
  if (!samples || samples.length === 0) return null;
  if (t < samples[0].t) return samples[0];
  if (t >= samples[samples.length - 1].t) return samples[samples.length - 1];

  let low = 0, high = samples.length - 1;
  while (low <= high) {{
    const mid = (low + high) >> 1;
    if (samples[mid].t <= t) low = mid + 1;
    else high = mid - 1;
  }}
  const idx0 = Math.max(0, high);
  const idx1 = Math.min(samples.length - 1, idx0 + 1);
  const p0 = samples[idx0];
  const p1 = samples[idx1];
  if (idx0 === idx1 || p1.t === p0.t) return p0;

  const alpha = (t - p0.t) / (p1.t - p0.t);
  const x = p0.x + alpha * (p1.x - p0.x);
  const y = p0.y + alpha * (p1.y - p0.y);
  const hp = Math.round(p0.hp + alpha * (p1.hp - p0.hp));

  const dx = p1.x - p0.x;
  const dy = p1.y - p0.y;
  const angle = Math.atan2(dy, dx);

  return {{ x, y, hp, angle, speed: Math.hypot(dx, dy) }};
}}

function formatTime(s) {{
  const sign = s < 0 ? '-' : '';
  const abs = Math.abs(s);
  const m = Math.floor(abs / 60);
  const sec = Math.floor(abs % 60);
  return `${{sign}}${{m}}:${{sec < 10 ? '0' : ''}}${{sec}}`;
}}

function drawFrame(t) {{
  ctx.save();
  ctx.fillStyle = '#10100f';
  ctx.fillRect(0, 0, 1024, 1024);

  // Transformación de zoom y pan
  ctx.translate(panX, panY);
  ctx.scale(zoomScale, zoomScale);

  if (radarImg && radarImg.complete) {{
    ctx.drawImage(radarImg, 0, 0, 1024, 1024);
  }} else {{
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let i = 64; i < 1024; i += 64) {{
      ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 1024); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(1024, i); ctx.stroke();
    }}
  }}

  // 1. Granadas y Utilidades activas
  if (chkSmokes.checked && DATA.grenades) {{
    DATA.grenades.forEach(g => {{
      if (!g.x || !g.y) return;
      const elapsed = t - g.t;

      // A. Humo (dura 20 s en CS2)
      if (g.type === 'Humo') {{
        if (elapsed >= 0 && elapsed <= 20) {{
          const alpha = elapsed < 1.5 ? (elapsed / 1.5) * 0.75 : (elapsed > 18 ? ((20 - elapsed) / 2) * 0.75 : 0.75);
          ctx.beginPath();
          ctx.arc(g.x, g.y, 45, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(180, 185, 190, ${{alpha}})`;
          ctx.fill();
          ctx.strokeStyle = 'rgba(230, 235, 240, 0.4)';
          ctx.lineWidth = 2;
          ctx.stroke();

          ctx.font = '11px sans-serif';
          ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
          ctx.textAlign = 'center';
          ctx.fillText('💨', g.x, g.y + 4);
        }}
      }}

      // B. Fuego (Molotov / Incendiaria, dura 7.0 s en CS2)
      else if (g.type === 'Fuego') {{
        if (elapsed >= 0 && elapsed <= 7.0) {{
          const alpha = elapsed < 0.6 ? (elapsed / 0.6) * 0.70 : (elapsed > 6.0 ? ((7.0 - elapsed) / 1.0) * 0.70 : 0.70);
          ctx.beginPath();
          ctx.arc(g.x, g.y, 36, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(225, 65, 15, ${{alpha * 0.75}})`;
          ctx.fill();
          ctx.strokeStyle = `rgba(255, 175, 30, ${{alpha * 0.9}})`;
          ctx.lineWidth = 2.5;
          ctx.stroke();

          // Núcleo caliente de fuego
          ctx.beginPath();
          ctx.arc(g.x, g.y, 18, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 195, 45, ${{alpha * 0.5}})`;
          ctx.fill();

          ctx.font = '13px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('🔥', g.x, g.y + 5);
        }}
      }}

      // C. Granada HE (Onda expansiva, dura 0.75 s)
      else if (g.type === 'Granada HE') {{
        if (elapsed >= 0 && elapsed <= 0.75) {{
          const p = elapsed / 0.75;
          const r = 10 + p * 38;
          const alpha = (1 - p);
          ctx.beginPath();
          ctx.arc(g.x, g.y, r, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(230, 75, 20, ${{alpha * 0.35}})`;
          ctx.fill();
          ctx.strokeStyle = `rgba(255, 215, 75, ${{alpha}})`;
          ctx.lineWidth = 3;
          ctx.stroke();

          if (p < 0.45) {{
            ctx.font = '13px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('💥', g.x, g.y + 5);
          }}
        }}
      }}

      // D. Flashbang (Destello cegador, dura 0.7 s en el mapa)
      else if (g.type === 'Flash') {{
        if (elapsed >= 0 && elapsed <= 0.7) {{
          const p = elapsed / 0.7;
          const r = 12 + p * 45;
          const alpha = (1 - p);
          ctx.beginPath();
          ctx.arc(g.x, g.y, r, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 255, 220, ${{alpha * 0.35}})`;
          ctx.fill();
          ctx.strokeStyle = `rgba(255, 255, 240, ${{alpha * 0.95}})`;
          ctx.lineWidth = 3.5;
          ctx.stroke();

          if (p < 0.4) {{
            ctx.font = '13px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('⚡', g.x, g.y + 5);
          }}
        }}
      }}

      // E. Señuelo (Decoy, dura 15 s)
      else if (g.type === 'Señuelo') {{
        if (elapsed >= 0 && elapsed <= 15.0) {{
          const alpha = elapsed > 13.0 ? (15.0 - elapsed) / 2.0 : 0.7;
          ctx.beginPath();
          ctx.arc(g.x, g.y, 14, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(144, 133, 233, ${{alpha * 0.4}})`;
          ctx.fill();
          ctx.strokeStyle = `rgba(144, 133, 233, ${{alpha}})`;
          ctx.lineWidth = 2;
          ctx.stroke();

          ctx.font = '10px sans-serif';
          ctx.textAlign = 'center';
          ctx.fillText('📡', g.x, g.y + 3);
        }}
      }}
    }});
  }}

  // 2. Kills y marcas de muerte
  const deathsBefore = DATA.kills.filter(k => k.t <= t);
  const deathMap = new Set(deathsBefore.map(k => k.victim_sid));

  deathsBefore.forEach(k => {{
    if (k.vx && k.vy) {{
      ctx.strokeStyle = k.victim_side === 'CT' ? 'rgba(57, 135, 229, 0.45)' : 'rgba(217, 89, 38, 0.45)';
      ctx.lineWidth = 2;
      const sz = 7;
      ctx.beginPath();
      ctx.moveTo(k.vx - sz, k.vy - sz); ctx.lineTo(k.vx + sz, k.vy + sz);
      ctx.moveTo(k.vx + sz, k.vy - sz); ctx.lineTo(k.vx - sz, k.vy + sz);
      ctx.stroke();
    }}
  }});

  DATA.kills.forEach(k => {{
    const diff = t - k.t;
    if (diff >= 0 && diff < 0.7 && k.ax && k.ay && k.vx && k.vy) {{
      const lineAlpha = (1 - diff / 0.7);
      ctx.strokeStyle = `rgba(255, 215, 0, ${{lineAlpha}})`;
      ctx.lineWidth = 2.5;
      ctx.setLineDash([6, 6]);
      ctx.beginPath();
      ctx.moveTo(k.ax, k.ay);
      ctx.lineTo(k.vx, k.vy);
      ctx.stroke();
      ctx.setLineDash([]);
    }}
  }});

  // 3. Bomba C4
  if (DATA.bomb) {{
    const plantEvent = DATA.bomb.find(b => b.event === 'bomb_planted' && b.t <= t);
    if (plantEvent && plantEvent.x && plantEvent.y) {{
      const defuseEvent = DATA.bomb.find(b => b.event === 'bomb_defused' && b.t <= t);
      const explodeEvent = DATA.bomb.find(b => b.event === 'bomb_exploded' && b.t <= t);
      const bombElapsed = t - plantEvent.t;
      const bombRemain = Math.max(0, 40 - bombElapsed);

      const pulse = 1 + 0.15 * Math.sin(t * 8);
      ctx.beginPath();
      ctx.arc(plantEvent.x, plantEvent.y, 14 * pulse, 0, Math.PI * 2);
      ctx.fillStyle = defuseEvent ? 'rgba(57, 135, 229, 0.6)' : (explodeEvent ? 'rgba(255, 60, 0, 0.8)' : 'rgba(255, 50, 50, 0.7)');
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 11px sans-serif';
      ctx.textAlign = 'center';
      const label = defuseEvent ? 'DEFUSED' : (explodeEvent ? 'EXPLODED' : `C4 ${{bombRemain.toFixed(0)}}s`);
      ctx.fillText(label, plantEvent.x, plantEvent.y - 18);
    }}
  }}

  // 4. Estela / Rastro del jugador seleccionado
  if (selectedPlayerId && chkTrails.checked) {{
    const traj = DATA.positions[selectedPlayerId];
    if (traj && traj.length > 0) {{
      const pInfo = DATA.players.find(p => p.steamid === selectedPlayerId);
      const isCT = pInfo ? pInfo.side === 'CT' : true;
      const trailColor = isCT ? 'rgba(57, 135, 229, 0.7)' : 'rgba(217, 89, 38, 0.7)';
      
      ctx.beginPath();
      let started = false;
      for (let i = 0; i < traj.length; i++) {{
        if (traj[i].t > t) break;
        if (!started) {{
          ctx.moveTo(traj[i].x, traj[i].y);
          started = true;
        }} else {{
          ctx.lineTo(traj[i].x, traj[i].y);
        }}
      }}
      ctx.strokeStyle = trailColor;
      ctx.lineWidth = 3.5;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }}
  }}

  // 5. Jugadores vivos
  let aliveCT = 0;
  let aliveT = 0;

  DATA.players.forEach(p => {{
    const isDead = deathMap.has(p.steamid);
    const state = getPlayerState(p.steamid, t);
    if (!state) return;

    if (!isDead) {{
      if (p.side === 'CT') aliveCT++; else aliveT++;

      const isCT = p.side === 'CT';
      const color = isCT ? '#3987e5' : '#d95926';
      const isSelected = (p.steamid === selectedPlayerId);

      // Halo dorado si está seleccionado
      if (isSelected) {{
        ctx.beginPath();
        ctx.arc(state.x, state.y, 18, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255, 209, 102, 0.25)';
        ctx.fill();
        ctx.strokeStyle = '#ffd166';
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }}

      if (state.speed > 0.4) {{
        ctx.beginPath();
        const tipX = state.x + Math.cos(state.angle) * (isSelected ? 24 : 18);
        const tipY = state.y + Math.sin(state.angle) * (isSelected ? 24 : 18);
        ctx.moveTo(state.x, state.y);
        ctx.lineTo(tipX, tipY);
        ctx.strokeStyle = isSelected ? '#ffd166' : 'rgba(255, 255, 255, 0.8)';
        ctx.lineWidth = isSelected ? 4 : 3;
        ctx.stroke();
      }}

      ctx.beginPath();
      ctx.arc(state.x, state.y, 11, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = isSelected ? '#ffd166' : '#ffffff';
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.stroke();

      if (state.hp < 100 && state.hp > 0) {{
        ctx.beginPath();
        ctx.arc(state.x, state.y, 14, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * (state.hp / 100)));
        ctx.strokeStyle = state.hp > 50 ? '#06d6a0' : (state.hp > 25 ? '#ffd166' : '#ef476f');
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }}

      // Efecto visual si el jugador está cegado por una flash
      if (DATA.blinds) {{
        const bItem = DATA.blinds.find(b => b.sid === p.steamid && t >= b.t && t <= (b.t + b.dur));
        if (bItem) {{
          const bAlpha = Math.min(1.0, (bItem.t + bItem.dur - t) / 1.2);
          ctx.beginPath();
          ctx.arc(state.x, state.y, 16, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(255, 255, 255, ${{bAlpha * 0.45}})`;
          ctx.fill();
          ctx.strokeStyle = `rgba(255, 255, 240, ${{bAlpha * 0.9}})`;
          ctx.lineWidth = 2.5;
          ctx.stroke();

          ctx.font = '11px sans-serif';
          ctx.fillStyle = '#ffffff';
          ctx.textAlign = 'center';
          ctx.fillText('⚡', state.x, state.y - 14);
        }}
      }}

      if (chkNames.checked) {{
        ctx.font = isSelected ? '700 12px -apple-system, sans-serif' : '600 11px -apple-system, sans-serif';
        ctx.textAlign = 'center';
        const txt = p.name;
        const tw = ctx.measureText(txt).width;

        ctx.fillStyle = isSelected ? 'rgba(255, 209, 102, 0.95)' : 'rgba(15, 15, 14, 0.85)';
        ctx.fillRect(state.x - tw / 2 - 3, state.y - 25, tw + 6, 14);

        ctx.fillStyle = isSelected ? '#10100f' : '#ffffff';
        ctx.fillText(txt, state.x, state.y - 14);
      }}
    }}
  }});

  ctx.restore();

  // Actualizar HUD
  aliveCTElem.textContent = aliveCT;
  aliveTElem.textContent = aliveT;
  timerDisplay.textContent = formatTime(t);
  timeIndicator.textContent = `${{formatTime(t)}} / ${{formatTime(DATA.tMax)}}`;
  timeline.value = t;

  updateRosters(deathMap, t);
  updateKillFeed(t);
}}

function updateRosters(deathMap, t) {{
  let ctHtml = '';
  let tHtml = '';
  DATA.players.forEach(p => {{
    const isDead = deathMap.has(p.steamid);
    const state = getPlayerState(p.steamid, t);
    const hp = (isDead || !state) ? 0 : Math.max(0, state.hp);
    const isCT = p.side === 'CT';
    const hpColor = isCT ? 'hp-ct' : 'hp-t';
    const isSelected = (p.steamid === selectedPlayerId);

    const row = `
      <div class="player-row ${{isDead ? 'dead' : ''}} ${{isSelected ? 'selected' : ''}}" onclick="selectPlayer('${{p.steamid}}')">
        <span style="font-weight:600; max-width:95px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          ${{isDead ? '💀 ' : ''}}${{esc(p.name)}}
        </span>
        <div style="display:flex; align-items:center; gap:5px;">
          <span style="font-family:monospace; font-size:11px; width:22px; text-align:right;">${{hp}}</span>
          <div class="hp-bar-bg"><div class="hp-bar-fill ${{hpColor}}" style="width:${{hp}}%;"></div></div>
        </div>
      </div>
    `;
    if (isCT) ctHtml += row; else tHtml += row;
  }});
  rosterCT.innerHTML = ctHtml;
  rosterT.innerHTML = tHtml;
}}

function updateKillFeed(t) {{
  const activeKills = DATA.kills.filter(k => k.t <= t);
  let feedHtml = '';
  activeKills.slice(-8).forEach(k => {{
    const attColor = k.attacker_side === 'CT' ? '#3987e5' : '#d95926';
    const vicColor = k.victim_side === 'CT' ? '#3987e5' : '#d95926';
    feedHtml += `
      <div class="feed-item">
        <span style="color:${{attColor}}; font-weight:700;">${{esc(k.attacker)}}</span>
        <span style="color:#c3c2b7;"> [${{k.weapon}}${{k.headshot ? ' 🎯' : ''}}] </span>
        <span style="color:${{vicColor}}; font-weight:700;">${{esc(k.victim)}}</span>
      </div>
    `;
  }});
  killFeedList.innerHTML = feedHtml || '<span style="color:#666; font-size:11px;">Sin bajas aún</span>';
}}

function renderLoop(timestamp) {{
  if (!isPlaying) return;
  const delta = (timestamp - lastTimestamp) / 1000;
  lastTimestamp = timestamp;

  currentTime += delta * playbackSpeed;
  if (currentTime >= DATA.tMax) {{
    currentTime = DATA.tMax;
    isPlaying = false;
    btnToggle.textContent = '▶';
  }}

  drawFrame(currentTime);

  if (isPlaying) {{
    requestAnimationFrame(renderLoop);
  }}
}}

if (radarImg) {{
  radarImg.onload = () => drawFrame(currentTime);
}}
drawFrame(currentTime);

</script>
</body>
</html>
"""
