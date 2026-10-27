"""Identidad de equipos entre partidas, por jugadores y no por nombre.

En matchmaking todos los equipos se llaman "Equipo A"/"Equipo B" y en FACEIT "team_<capitán>", así que el
nombre no sirve para saber si dos partidas son del mismo equipo. Acá cada aparición de un equipo en una
partida (una *instancia*: demo + lado A/B) se une con otra cuando comparten al menos `MIN_SHARED`
jugadores. Los nombres reales (tags de clan) también unen, igual que antes, pero los genéricos nunca.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .parser import DemoData

MIN_SHARED = 3  # 3 de 5: tolera hasta dos cambios (stand-ins, suplentes) sin confundir equipos distintos
GENERIC_NAME = re.compile(r"^(equipo [ab]|team_.*|team [ab]|ct|t|terrorists?|counter-terrorists?|)$", re.I)


def is_generic_name(name: str) -> bool:
    return bool(GENERIC_NAME.match((name or "").strip()))


@dataclass
class TeamGroup:
    key: str
    name: str
    instances: list[tuple[str, str]] = field(default_factory=list)   # (demo_id, "A"/"B")
    raw_names: list[str] = field(default_factory=list)
    core_players: list[str] = field(default_factory=list)              # nombres, de más a menos partidas
    linked_by: str = "jugadores"                                      # "jugadores", "nombre" o "única partida"

    @property
    def matches(self) -> int:
        return len({d for d, _ in self.instances})


def _instances(demos: list[DemoData]) -> list[dict]:
    out = []
    for d in demos:
        players = d.players
        for letter, key in (("A", "team_a"), ("B", "team_b")):
            roster = players[players["team"] == letter]
            out.append({"demo_id": d.demo_id, "letter": letter, "name": str(d.meta.get(key, "")).strip(),
                        "roster": frozenset(roster["steamid"].astype(str)),
                        "names": dict(zip(roster["steamid"].astype(str), roster["name"].astype(str)))})
    return out


def cluster_teams(demos: list[DemoData], min_shared: int = MIN_SHARED) -> list[TeamGroup]:
    """Agrupa las instancias de equipo de todas las demos en equipos."""
    from .team_analysis import extract_team_keywords  # misma regla de palabras clave que usaba la vista

    inst = _instances(demos)
    parent = list(range(len(inst)))
    slots = [{(i["demo_id"])} for i in inst]  # demos que ya ocupa cada grupo: no unir los dos lados de una partida
    how = ["única partida"] * len(inst)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int, reason: str) -> None:
        ri, rj = find(i), find(j)
        if ri == rj or slots[ri] & slots[rj]:
            return
        parent[ri] = rj
        slots[rj] |= slots[ri]
        how[rj] = "jugadores" if "jugadores" in (how[ri], how[rj], reason) else reason

    for i in range(len(inst)):
        for j in range(i + 1, len(inst)):
            if inst[i]["demo_id"] == inst[j]["demo_id"]:
                continue
            if len(inst[i]["roster"] & inst[j]["roster"]) >= min_shared:
                union(i, j, "jugadores")
    # Nombres reales: misma palabra clave no genérica (BESTIA / BESTIA Esports)
    for i in range(len(inst)):
        ni = inst[i]["name"]
        if is_generic_name(ni):
            continue
        for j in range(i + 1, len(inst)):
            nj = inst[j]["name"]
            if inst[i]["demo_id"] != inst[j]["demo_id"] and not is_generic_name(nj) \
                    and extract_team_keywords(ni) & extract_team_keywords(nj):
                union(i, j, "nombre")

    members: dict[int, list[int]] = {}
    for i in range(len(inst)):
        members.setdefault(find(i), []).append(i)

    groups = []
    for root, idx in members.items():
        appearances = Counter()
        names_by_sid: dict[str, str] = {}
        for i in idx:
            appearances.update(inst[i]["roster"])
            names_by_sid.update(inst[i]["names"])
        core = [names_by_sid.get(s, s) for s, _ in appearances.most_common()]
        raw = Counter(inst[i]["name"] for i in idx if inst[i]["name"])
        real = [n for n, _ in raw.most_common() if not is_generic_name(n)]
        captains = [n[5:] for n, _ in raw.most_common() if n.lower().startswith("team_") and n[5:] in core]
        if real:
            name = real[0]
        elif captains:  # FACEIT nombra al equipo por su capitán: team_<nick>
            name = f"Equipo de {captains[0]}"
        elif core:
            name = f"Equipo de {core[0]}" + (f" y {core[1]}" if len(core) > 1 else "")
        else:
            name = raw.most_common(1)[0][0] if raw else "Equipo"
        groups.append(TeamGroup(
            key=f"{inst[idx[0]]['demo_id']}:{inst[idx[0]]['letter']}", name=name,
            instances=sorted((inst[i]["demo_id"], inst[i]["letter"]) for i in idx),
            raw_names=[n for n, _ in raw.most_common()], core_players=core,
            linked_by=how[root] if len(idx) > 1 else "única partida"))

    # Nombres repetidos (dos "Equipo de X" distintos): desambiguar
    seen = Counter(g.name for g in groups)
    for g in groups:
        if seen[g.name] > 1 and len(g.core_players) > 2:
            g.name = f"{g.name} ({g.core_players[2]})"
    groups.sort(key=lambda g: (-g.matches, g.name.lower()))
    return groups
