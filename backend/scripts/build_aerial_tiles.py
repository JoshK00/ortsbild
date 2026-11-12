"""Build the aerial photo map of Stuttgart: tiles/stuttgart_luftbild.pmtiles

The photos are the digital orthophotos (20 cm) of the Landesamt fuer Geoinformation und Landentwicklung Baden-Wuerttemberg,
open data under "Datenlizenz Deutschland - Namensnennung - Version 2.0" (dl-de/by-2-0, https://www.govdata.de/dl-de/by-2-0).
The licence allows to store and pass on the photos if the source is named, the dashboard names it on the map.

The script asks the official WMTS of the LGL for the tiles of the city (a few thousand requests, 4 at a time, with a
pause), writes them into an MBTiles file and turns that into PMTiles with the `pmtiles` program. It can be stopped and
started again, a tile that is already in the file is not asked for twice.

  python3 backend/scripts/build_aerial_tiles.py --max-zoom 17
"""
from __future__ import annotations

import argparse
import math
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WMTS = (
    "https://owsproxy.lgl-bw.de/owsproxy/ows/WMTS_LGL-BW_ATKIS_DOP_20_C?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
    "&LAYER=DOP_20_C&STYLE=default&FORMAT=image/jpeg&TILEMATRIXSET=GoogleMapsCompatible"
    "&TILEMATRIX=GoogleMapsCompatible:{z}&TILEROW={y}&TILECOL={x}"
)
# the city of Stuttgart (west, south, east, north), a little more than the city limits
BOUNDS = (9.03, 48.685, 9.325, 48.87)
ATTRIBUTION = "Luftbild: LGL-BW, Datenlizenz Deutschland – Namensnennung – Version 2.0, www.lgl-bw.de"
USER_AGENT = "Ortsbild-tile-build/1.0 (student project, one-time build for a city map)"
WORKERS = 4
PAUSE = 0.05  # seconds each worker waits after a tile


def tile_x(lon: float, z: int) -> int:
    return int((lon + 180.0) / 360.0 * 2**z)


def tile_y(lat: float, z: int) -> int:
    return int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * 2**z)


def tiles_of(z: int):
    west, south, east, north = BOUNDS
    for x in range(tile_x(west, z), tile_x(east, z) + 1):
        for y in range(tile_y(north, z), tile_y(south, z) + 1):
            yield z, x, y


def fetch(z: int, x: int, y: int) -> bytes:
    request = urllib.request.Request(WMTS.format(z=z, x=x, y=y), headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
                if response.headers.get_content_type() != "image/jpeg" or len(data) < 200:
                    raise ValueError("no jpeg: " + response.headers.get_content_type())
                return data
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            last = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"tile {z}/{x}/{y} failed: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-zoom", type=int, default=12)
    parser.add_argument("--max-zoom", type=int, default=17)
    parser.add_argument("--out", default="tiles/stuttgart_luftbild.pmtiles")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mbtiles = out.with_suffix(".mbtiles")
    db = sqlite3.connect(mbtiles)
    db.executescript(
        "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);"
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
        "CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row);"
    )
    db.execute("DELETE FROM metadata")
    west, south, east, north = BOUNDS
    for name, value in {
        "name": "Stuttgart Luftbild", "format": "jpg", "type": "baselayer", "version": "1",
        "minzoom": str(args.min_zoom), "maxzoom": str(args.max_zoom), "bounds": f"{west},{south},{east},{north}",
        "attribution": ATTRIBUTION,
    }.items():
        db.execute("INSERT INTO metadata VALUES (?, ?)", (name, value))
    db.commit()

    have = {(z, x, (2**z - 1) - tms_y) for z, x, tms_y in db.execute("SELECT zoom_level, tile_column, tile_row FROM tiles")}
    todo = [t for z in range(args.min_zoom, args.max_zoom + 1) for t in tiles_of(z) if t not in have]
    print(f"{len(todo)} tiles to get, {len(have)} already there", flush=True)

    def work(tile):
        z, x, y = tile
        data = fetch(z, x, y)
        time.sleep(PAUSE)
        return z, x, y, data

    done = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for z, x, y, data in pool.map(work, todo):
            db.execute("INSERT OR REPLACE INTO tiles VALUES (?, ?, ?, ?)", (z, x, (2**z - 1) - y, data))
            done += 1
            if done % 500 == 0:
                db.commit()
                rate = done / (time.time() - started)
                print(f"{done}/{len(todo)}  {rate:.1f} tiles/s  about {(len(todo) - done) / rate / 60:.0f} min left", flush=True)
    db.commit()
    db.close()

    subprocess.run(["pmtiles", "convert", str(mbtiles), str(out)], check=True)
    print(f"done: {out} ({out.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
