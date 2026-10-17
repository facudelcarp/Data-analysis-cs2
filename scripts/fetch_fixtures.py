"""Descarga demos reales de validación (fixtures públicas de awpy, con resultados de referencia
de csstats / FACEIT / HLTV) a tests/data/. Pesan ~1.8 GB en total.

    python scripts/fetch_fixtures.py            # todas
    python scripts/fetch_fixtures.py valve      # solo las que contienen "valve" (84 MB)
"""
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = "https://raw.githubusercontent.com/pnxenopoulos/awpy-fixtures/main/manifest.json"
DEST = Path(__file__).resolve().parent.parent / "tests" / "data"


def main(filters: list[str]) -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(urllib.request.urlopen(MANIFEST, timeout=30).read())
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2))
    for f in manifest["fixtures"]:
        if filters and not any(x in f["name"] for x in filters):
            continue
        target = DEST / f["asset"]
        if target.exists() and target.stat().st_size == f["size"]:
            print("ya está", target.name)
            continue
        print(f"descargando {target.name} ({f['size'] / 1e6:.0f} MB)…")
        h = hashlib.sha256()
        with urllib.request.urlopen(f["url"], timeout=60) as resp, open(target, "wb") as out:
            while chunk := resp.read(8 << 20):
                h.update(chunk)
                out.write(chunk)
        if h.hexdigest() != f["sha256"]:
            target.unlink()
            raise SystemExit(f"sha256 inválido para {target.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
