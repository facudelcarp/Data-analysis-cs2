"""Metadatos de mapas: transformación de coordenadas del juego a píxeles de radar."""
from __future__ import annotations

import io
import json
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

RADAR_DIR = Path(__file__).resolve().parent.parent / "assets" / "radars"
RADAR_SIZE = 1024
# Radares extraídos de los VPK del juego por el pipeline de awpy-data (MIT). No se versionan acá
# porque son assets de Valve: `cs2a radars` los descarga.
RADARS_URL = "https://github.com/pnxenopoulos/awpy-data/releases/latest/download/images.zip"
MAP_DATA_URL = "https://github.com/pnxenopoulos/awpy-data/releases/latest/download/map_data.json"


@dataclass(frozen=True)
class MapInfo:
    pos_x: float
    pos_y: float
    scale: float
    # Mapas con dos niveles (Nuke, Vertigo, Train): por debajo de este Z se considera nivel inferior
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
    "de_train": MapInfo(-2308, 2078, 4.082077, lower_level_max_z=-50),
    "de_vertigo": MapInfo(-3168, 1762, 4.0, lower_level_max_z=11700),
}


def _downloaded_maps() -> dict[str, MapInfo]:
    """Tabla de coordenadas descargada junto con los radares (cubre mapas fuera del Active Duty)."""
    path = RADAR_DIR / "map_data.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
    except ValueError:
        return {}
    out = {}
    for name, m in raw.items():
        if not isinstance(m, dict) or m.get("pos_x") is None or not m.get("scale"):
            continue
        lower = (m.get("verticalsections") or {}).get("lower", {}).get("AltitudeMax")
        out[name] = MapInfo(float(m["pos_x"]), float(m["pos_y"]), float(m["scale"]),
                            float(lower) if lower is not None else None)
    return out


def map_info(map_name: str) -> MapInfo | None:
    return MAPS.get(map_name) or _downloaded_maps().get(map_name)


def radar_image(map_name: str, lower: bool = False) -> Path | None:
    name = f"{map_name}_lower" if lower else map_name
    for candidate in (f"{name}.png", f"{name}_radar.png", f"{name}_radar_psd.png"):
        p = RADAR_DIR / candidate
        if p.exists():
            return p
    return None


def has_levels(map_name: str) -> bool:
    info = map_info(map_name)
    return bool(info and info.lower_level_max_z is not None)


def level_mask(map_name: str, z, lower: bool):
    """Máscara booleana de los puntos que pertenecen al nivel pedido (todo si el mapa tiene uno solo)."""
    info = map_info(map_name)
    if not info or info.lower_level_max_z is None:
        return z.notna()
    return (z < info.lower_level_max_z) if lower else (z >= info.lower_level_max_z)


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "cs2analysis"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def download_radars(dest: Path = RADAR_DIR, url: str = RADARS_URL) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    data = _fetch(url)
    (dest / "map_data.json").write_bytes(_fetch(MAP_DATA_URL))
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            if member.endswith(".png"):
                target = dest / Path(member).name
                target.write_bytes(z.read(member))
                out.append(target)
    return out


def pretty_map(map_name: str) -> str:
    return map_name.removeprefix("de_").removeprefix("cs_").replace("_", " ").title()
