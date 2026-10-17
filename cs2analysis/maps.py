"""Metadatos de mapas: transformación de coordenadas del juego a píxeles de radar."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

RADAR_DIR = Path(__file__).resolve().parent.parent / "assets" / "radars"
RADAR_SIZE = 1024


@dataclass(frozen=True)
class MapInfo:
    pos_x: float
    pos_y: float
    scale: float
    # Mapas con dos niveles (Nuke, Vertigo): por debajo de este Z se considera nivel inferior
    lower_level_max_z: float | None = None

    def to_radar(self, x, y):
        """Coordenadas del juego -> píxeles del radar de 1024x1024 (y crece hacia abajo)."""
        return (x - self.pos_x) / self.scale, (self.pos_y - y) / self.scale


# Valores de los archivos resource/overviews/<mapa>.txt de CS2
MAPS: dict[str, MapInfo] = {
    "de_ancient": MapInfo(-2953, 2164, 5.0),
    "de_anubis": MapInfo(-2796, 3328, 5.22),
    "de_dust2": MapInfo(-2476, 3239, 4.4),
    "de_inferno": MapInfo(-2087, 3870, 4.9),
    "de_mirage": MapInfo(-3230, 1713, 5.0),
    "de_nuke": MapInfo(-3453, 2887, 7.0, lower_level_max_z=-495),
    "de_overpass": MapInfo(-4831, 1781, 5.2),
    "de_train": MapInfo(-2308, 2078, 4.082077),
    "de_vertigo": MapInfo(-3168, 1762, 4.0, lower_level_max_z=11700),
}


def map_info(map_name: str) -> MapInfo | None:
    return MAPS.get(map_name)


def radar_image(map_name: str) -> Path | None:
    for candidate in (f"{map_name}.png", f"{map_name}_radar.png", f"{map_name}_radar_psd.png"):
        p = RADAR_DIR / candidate
        if p.exists():
            return p
    return None


def pretty_map(map_name: str) -> str:
    return map_name.removeprefix("de_").removeprefix("cs_").replace("_", " ").title()
