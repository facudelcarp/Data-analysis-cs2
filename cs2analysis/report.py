"""Generador de Match Report ejecutivo (HTML descargable y visualizable) para equipos y coaches."""
from __future__ import annotations

from html import escape

import pandas as pd
from .parser import DemoData
from .stats import player_stats, team_stats, round_timeline
from .mistakes import detect_mistakes
from .maps import pretty_map
from .archetypes import get_player_side_archetypes


def esc(value) -> str:
    """Todo texto que viene de la demo (nicks, equipos) se escapa: un nick puede ser "<script>"."""
    return escape(str(value))


def generate_html_report(d: DemoData) -> str:
    m = d.meta
    ps = player_stats(d)
    ts = team_stats(d)
    rt = round_timeline(d)
    errs = detect_mistakes(d)

    team_a = m["team_a"]
    team_b = m["team_b"]
    score_a = m["score_a"]
    score_b = m["score_b"]
    winner = team_a if score_a > score_b else (team_b if score_b > score_a else "Empate")

    # MVP por rating 2.0
    best_player = ps.sort_values("rating2", ascending=False).iloc[0] if not ps.empty else None
    mvp_badge = ""
    if best_player is not None:
        info_mvp = get_player_side_archetypes(d, best_player["steamid"])
        mvp_badge = info_mvp.get("dual_badge", "")

    # Filas de jugadores
    def player_table_html(team_code: str) -> str:
        t_ps = ps[ps["team"] == team_code].sort_values("rating2", ascending=False)
        rows = ""
        for _, p in t_ps.iterrows():
            info_p = get_player_side_archetypes(d, p["steamid"])
            dual_badge = info_p.get("dual_badge", "")
            rows += f"""
            <tr>
              <td><strong>{esc(p['name'])}</strong> <span style="font-size: 10px; color: #ffd166; background: rgba(255,209,102,0.12); padding: 1px 5px; border-radius: 3px; margin-left: 4px;">{esc(dual_badge)}</span></td>
              <td>{p['rating2']:.2f}</td>
              <td>{int(p['kills'])}-{int(p['deaths'])}-{int(p['assists'])}</td>
              <td>{p['adr']:.1f}</td>
              <td>{p['kast_pct']:.0f}%</td>
              <td>{p['hs_pct']:.0f}%</td>
              <td>{int(p['opening_kills'])}-{int(p['opening_deaths'])}</td>
            </tr>
            """
        return rows

    # Lista de errores críticos
    err_html = ""
    if not errs.empty:
        for _, e in errs.head(6).iterrows():
            badge_color = "#ef476f" if e["severity"] == "CRÍTICA" else "#ffd166"
            err_html += f"""
            <div style="margin-bottom: 8px; padding: 8px 12px; background: #222; border-left: 4px solid {badge_color}; border-radius: 4px;">
              <span style="font-size: 11px; font-weight: bold; background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 3px;">
                Ronda {esc(e['round'])} · {esc(e['team_name'])}
              </span>
              <strong style="margin-left: 8px; color: #fff;">{esc(e['title'])}</strong>
              <div style="font-size: 13px; color: #bbb; margin-top: 3px;">{esc(e['detail'])}</div>
            </div>
            """
    else:
        err_html = "<p style='color: #888;'>Sin errores graves detectados.</p>"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Match Report - {esc(team_a)} vs {esc(team_b)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #e0e0e0; margin: 0; padding: 25px; }}
  .container {{ max-width: 900px; margin: 0 auto; background: #1a1a1a; padding: 30px; border-radius: 12px; border: 1px solid #333; }}
  .header {{ text-align: center; border-bottom: 1px solid #333; padding-bottom: 20px; margin-bottom: 25px; }}
  .score {{ font-size: 42px; font-weight: 800; color: #fff; margin: 10px 0; }}
  .score span {{ color: #2a78d6; }}
  .meta-tag {{ font-size: 13px; color: #888; letter-spacing: 0.5px; text-transform: uppercase; }}
  h2 {{ color: #f0f0f0; font-size: 18px; border-bottom: 2px solid #2a78d6; padding-bottom: 6px; margin-top: 25px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }}
  th, td {{ padding: 8px 10px; text-align: left; border-bottom: 1px solid #282828; }}
  th {{ background: #222; color: #aaa; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
  tr:hover {{ background: #222; }}
  .mvp-box {{ background: rgba(42, 120, 214, 0.12); border: 1px solid rgba(42, 120, 214, 0.4); padding: 12px 16px; border-radius: 8px; margin-bottom: 20px; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="meta-tag">CS2 Analysis · Match Report Oficial</div>
    <div style="font-size: 20px; font-weight: 600; margin-top: 5px;">{esc(team_a)} vs {esc(team_b)}</div>
    <div class="score">{score_a} <span>:</span> {score_b}</div>
    <div style="color: #aaa; font-size: 14px;">Mapa: <strong>{pretty_map(m['map'])}</strong> · Duración: {m['duration_min']} min · Ganador: <strong>{esc(winner)}</strong></div>
  </div>

  {f'''<div class="mvp-box">
    <strong>⭐ MVP del Partido:</strong> {esc(best_player["name"])} <span style="font-size: 11px; color: #ffd166; background: rgba(255,209,102,0.15); padding: 2px 7px; border-radius: 4px; margin-left: 6px;">{esc(mvp_badge)}</span> — Rating {best_player["rating2"]:.2f} · ADR {best_player["adr"]:.1f} · {int(best_player["kills"])}-{int(best_player["deaths"])}
  </div>''' if best_player is not None else ''}

  <h2>{esc(team_a)} ({score_a})</h2>
  <table>
    <thead><tr><th>Jugador</th><th>Rating</th><th>K-D-A</th><th>ADR</th><th>KAST</th><th>HS%</th><th>Entry</th></tr></thead>
    <tbody>{player_table_html("A")}</tbody>
  </table>

  <h2>{esc(team_b)} ({score_b})</h2>
  <table>
    <thead><tr><th>Jugador</th><th>Rating</th><th>K-D-A</th><th>ADR</th><th>KAST</th><th>HS%</th><th>Entry</th></tr></thead>
    <tbody>{player_table_html("B")}</tbody>
  </table>

  <h2>⚠️ Lowlights y Momentos Críticos</h2>
  {err_html}
</div>
</body>
</html>
"""
