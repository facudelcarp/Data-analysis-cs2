"""Línea de visión contra la malla de colisión real del mapa.

Las mallas (`<mapa>.mesh`, formato AWMH de awpy-data) son los oclusores visuales del
`world_physics` de cada mapa: unos 30-400 mil triángulos. Para responder "¿A ve a B?"
se indexan los triángulos en una grilla 2D. Cada consulta junta los triángulos de las celdas
que cruza el segmento y los testea todos de una vez con Möller–Trumbore vectorizado en numpy.
"""
from __future__ import annotations

import io
import struct
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np

MESH_DIR = Path(__file__).resolve().parent.parent / "assets" / "geometry"
GEOMETRY_URL = "https://github.com/pnxenopoulos/awpy-data/releases/latest/download/geometry.zip"
MAGIC = b"AWMH"
CELL = 192.0
SEG_EPS = 1e-4
PARALLEL_EPS = 1e-8


class VisibilityMesh:
    def __init__(self, vertices: np.ndarray, triangles: np.ndarray, cell: float = CELL):
        tri = vertices[triangles]                      # (m, 3 vértices, xyz)
        self.v0 = tri[:, 0].astype(np.float32)
        self.e1 = (tri[:, 1] - tri[:, 0]).astype(np.float32)
        self.e2 = (tri[:, 2] - tri[:, 0]).astype(np.float32)
        self.zmin = tri[:, :, 2].min(axis=1)
        self.zmax = tri[:, :, 2].max(axis=1)
        self.xmin, self.xmax = tri[:, :, 0].min(axis=1), tri[:, :, 0].max(axis=1)
        self.ymin, self.ymax = tri[:, :, 1].min(axis=1), tri[:, :, 1].max(axis=1)
        self.cell = cell
        lo = tri[:, :, :2].min(axis=1)
        hi = tri[:, :, :2].max(axis=1)
        self.origin = lo.min(axis=0)
        ilo = np.floor((lo - self.origin) / cell).astype(np.int64)
        ihi = np.floor((hi - self.origin) / cell).astype(np.int64)
        self.nx = int(ihi[:, 0].max()) + 1
        self.ny = int(ihi[:, 1].max()) + 1
        # Expandir cada triángulo a todas las celdas de su bounding box (CSR: celda -> triángulos)
        span_x = ihi[:, 0] - ilo[:, 0] + 1
        span_y = ihi[:, 1] - ilo[:, 1] + 1
        counts = span_x * span_y
        tri_id = np.repeat(np.arange(len(tri)), counts)
        local = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
        sx = np.repeat(span_x, counts)
        cx = np.repeat(ilo[:, 0], counts) + local % sx
        cy = np.repeat(ilo[:, 1], counts) + local // sx
        cell_id = cx * self.ny + cy
        order = np.argsort(cell_id, kind="stable")
        self.cell_tris = tri_id[order].astype(np.int32)
        self.cell_start = np.searchsorted(cell_id[order], np.arange(self.nx * self.ny + 1))
        self.n_triangles = len(tri)

    @classmethod
    def from_bytes(cls, data: bytes) -> "VisibilityMesh":
        if data[:4] != MAGIC:
            raise ValueError("no es una malla AWMH")
        _, n_verts, n_tris = struct.unpack_from("<III", data, 4)
        verts = np.frombuffer(data, dtype="<f4", count=n_verts * 3, offset=16).reshape(n_verts, 3)
        tris = np.frombuffer(data, dtype="<u4", count=n_tris * 3, offset=16 + n_verts * 12).reshape(n_tris, 3)
        return cls(verts, tris.astype(np.int64))

    def _candidates(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Triángulos de las celdas que cruzan los segmentos a[i]→b[i] (a, b: (n, 3)). Puede repetir índices:
        testear un triángulo dos veces es más barato que deduplicar."""
        n = max(2, int(np.hypot(*(b[:, :2] - a[:, :2]).T).max() / (self.cell / 3)) + 2)
        f = np.linspace(0, 1, n)[None, :, None]
        pts = (a[:, None, :2] + f * (b[:, None, :2] - a[:, None, :2])).reshape(-1, 2)
        ij = np.floor((pts - self.origin) / self.cell).astype(np.int64)
        # vecinos en x/y para no perder celdas que el segmento corta en diagonal
        ij = np.concatenate([ij, ij + [1, 0], ij + [-1, 0], ij + [0, 1], ij + [0, -1]])
        ok = (ij[:, 0] >= 0) & (ij[:, 0] < self.nx) & (ij[:, 1] >= 0) & (ij[:, 1] < self.ny)
        cells = np.sort(ij[ok, 0] * self.ny + ij[ok, 1])
        if len(cells) == 0:
            return np.empty(0, dtype=np.int32)
        cells = cells[np.concatenate([[True], cells[1:] != cells[:-1]])]
        starts, ends = self.cell_start[cells], self.cell_start[cells + 1]
        lens = ends - starts
        if lens.sum() == 0:
            return np.empty(0, dtype=np.int32)
        idx = np.repeat(starts - np.cumsum(lens) + lens, lens) + np.arange(lens.sum())
        cand = self.cell_tris[idx]
        zlo, zhi = min(a[:, 2].min(), b[:, 2].min()), max(a[:, 2].max(), b[:, 2].max())
        return cand[(self.zmax[cand] >= zlo) & (self.zmin[cand] <= zhi)]

    def visible_many(self, a, b) -> np.ndarray:
        """Visibilidad de varios segmentos cercanos entre sí (p. ej. los ticks de un mismo duelo).

        Junta candidatos una vez para todo el lote y después, por segmento, testea solo los triángulos
        cuyo bounding box se cruza con el del segmento."""
        a = np.atleast_2d(np.asarray(a, dtype=np.float32))
        b = np.atleast_2d(np.asarray(b, dtype=np.float32))
        out = np.ones(len(a), dtype=bool)
        cand = self._candidates(a, b)
        if len(cand) == 0:
            return out
        e1, e2, v0 = self.e1[cand], self.e2[cand], self.v0[cand]
        bx0, bx1, by0, by1 = self.xmin[cand], self.xmax[cand], self.ymin[cand], self.ymax[cand]
        bz0, bz1 = self.zmin[cand], self.zmax[cand]
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        for i in range(len(a)):
            m = ((bx1 >= lo[i, 0]) & (bx0 <= hi[i, 0]) & (by1 >= lo[i, 1]) & (by0 <= hi[i, 1])
                 & (bz1 >= lo[i, 2]) & (bz0 <= hi[i, 2]))
            if not m.any():
                continue
            E1, E2, V0 = e1[m], e2[m], v0[m]
            d = b[i] - a[i]
            p = _cross(d[None], E2)
            det = (E1 * p).sum(1)
            ok = np.abs(det) > PARALLEL_EPS
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            s = a[i] - V0
            u = (s * p).sum(1) * inv
            q = _cross(s, E1)
            v = (q @ d) * inv
            t = (E2 * q).sum(1) * inv
            out[i] = not (ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > SEG_EPS) & (t < 1 - SEG_EPS)).any()
        return out

    def is_visible(self, a, b) -> bool:
        return bool(self.visible_many([a], [b])[0])


def _cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Producto cruz con broadcasting (np.cross es varias veces más lento por el manejo de ejes)."""
    return np.stack([a[..., 1] * b[..., 2] - a[..., 2] * b[..., 1],
                     a[..., 2] * b[..., 0] - a[..., 0] * b[..., 2],
                     a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]], axis=-1)


def download_geometry(dest: Path = MESH_DIR, maps: list[str] | None = None, url: str = GEOMETRY_URL) -> list[Path]:
    """Descarga las mallas de awpy-data (~57 MB comprimido). `maps` limita qué archivos se extraen."""
    dest.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "cs2analysis"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.namelist():
            name = Path(member).name
            if not name.endswith(".mesh") or (maps and name[:-5] not in maps):
                continue
            target = dest / name
            target.write_bytes(z.read(member))
            out.append(target)
    return out


def mesh_path(map_name: str) -> Path | None:
    p = MESH_DIR / f"{map_name}.mesh"
    return p if p.exists() else None


@lru_cache(maxsize=2)
def load_mesh(map_name: str) -> VisibilityMesh | None:
    p = mesh_path(map_name)
    return VisibilityMesh.from_bytes(p.read_bytes()) if p else None
