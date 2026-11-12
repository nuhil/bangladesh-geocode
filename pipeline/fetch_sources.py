"""Download the upstream datasets and normalise them into small CSV snapshots.

    python pipeline/fetch_sources.py            # download, fall back to cache
    python pipeline/fetch_sources.py --offline  # only use pipeline/.cache
    python pipeline/fetch_sources.py --refresh  # ignore cache younger than 24h

Sources (see README "Data sources"):
  * HDX COD-AB Bangladesh (Bangladesh Bureau of Statistics via UN OCHA)
      - bgd_admin_boundaries.xlsx      : admin 1-3 tables + admin 4 points
      - bgd_admin_boundaries.geojson.zip: admin 3 polygons (for point-in-polygon)
  * GeoNames postal codes (Bangladesh Post Office codes) - BD.zip

Fallback chain, per source:
  1. fresh download            -> pipeline/.cache/<file>
  2. previously cached download (pipeline/.cache)
  3. keep the committed snapshot CSV in pipeline/sources/ untouched
The build step (build.py) only ever reads the committed snapshots, plus the
legacy data, so a failed fetch never breaks or empties the published data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

from common import PIPELINE_DIR, SOURCES_DIR, fmt_coord, write_csv

CACHE_DIR = PIPELINE_DIR / ".cache"
UA = "bangladesh-geocode-pipeline/1.0"

HDX_PACKAGE_API = "https://data.humdata.org/api/3/action/package_show?id=cod-ab-bgd"
HDX_DATASET_PAGE = "https://data.humdata.org/dataset/cod-ab-bgd"
# Used only when the CKAN API itself is unreachable.
HDX_FALLBACK_URLS = {
    "bgd_admin_boundaries.xlsx":
        "https://data.humdata.org/dataset/401d3fae-4262-48c9-891f-461fd776d49b/resource/"
        "5f7e534d-9b06-442e-a706-083789bff2c9/download/bgd_admin_boundaries.xlsx",
    "bgd_admin_boundaries.geojson.zip":
        "https://data.humdata.org/dataset/401d3fae-4262-48c9-891f-461fd776d49b/resource/"
        "cec2abe3-d8b7-4025-9362-9f7e780f2a07/download/bgd_admin_boundaries.geojson.zip",
}
GEONAMES_URL = "https://download.geonames.org/export/zip/BD.zip"

# GeoNames still uses the pre-2015 BBS codes for the four districts that moved
# from Dhaka division to the new Mymensingh division.
GEONAMES_DISTRICT_REMAP = {"3039": "4539", "3061": "4561", "3072": "4572", "3089": "4589"}


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Download with cache fallback
# --------------------------------------------------------------------------
CACHE_MAX_AGE = 24 * 3600
REFRESH = False


def download(url: str, name: str, offline: bool, timeout: int = 600) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / name
    fresh = target.exists() and (dt.datetime.now().timestamp() - target.stat().st_mtime) < CACHE_MAX_AGE
    if fresh and not REFRESH:
        log(f"  using cached {name} (< 24h old; --refresh to force)")
        return target
    if not offline:
        tmp = target.with_suffix(target.suffix + ".part")
        for attempt in (1, 2):
            try:
                log(f"  downloading {name} (attempt {attempt}) ...")
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open("wb") as fh:
                    while chunk := r.read(1 << 16):
                        fh.write(chunk)
                tmp.replace(target)
                return target
            except Exception as exc:  # noqa: BLE001 - any failure -> fallback
                log(f"  ! download failed: {exc}")
                tmp.unlink(missing_ok=True)
    if target.exists():
        log(f"  using cached {target.name}")
        return target
    log(f"  ! {name} unavailable (no download, no cache)")
    return None


def hdx_resource_urls(offline: bool) -> tuple:
    """Resolve the current resource URLs from the HDX CKAN API."""
    urls, meta = dict(HDX_FALLBACK_URLS), {}
    if offline:
        return urls, meta
    try:
        req = urllib.request.Request(HDX_PACKAGE_API, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            pkg = json.load(r)["result"]
        for res in pkg.get("resources", []):
            if res.get("name") in urls:
                urls[res["name"]] = res["url"]
        meta = {
            "title": pkg.get("title"),
            "dataset_date": pkg.get("dataset_date"),
            "metadata_modified": pkg.get("metadata_modified"),
            "source": pkg.get("dataset_source"),
            "license": pkg.get("license_title"),
        }
    except Exception as exc:  # noqa: BLE001
        log(f"  ! HDX API unavailable ({exc}); using pinned resource URLs")
    return urls, meta


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Point in polygon (pure Python, bbox-filtered)
# --------------------------------------------------------------------------
class PolygonIndex:
    def __init__(self):
        self.items = []  # (bbox, code, [polygon rings])

    def add(self, code: str, geometry: dict) -> None:
        polys = geometry["coordinates"]
        if geometry["type"] == "Polygon":
            polys = [polys]
        for rings in polys:
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            self.items.append(((min(xs), min(ys), max(xs), max(ys)), code, rings))

    @staticmethod
    def _in_ring(x, y, ring) -> bool:
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def lookup(self, lon: float, lat: float) -> str:
        for (x0, y0, x1, y1), code, rings in self.items:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and self._in_ring(lon, lat, rings[0]):
                if not any(self._in_ring(lon, lat, h) for h in rings[1:]):
                    return code
        return ""


def load_admin3_polygons(geo_zip: Path | None) -> PolygonIndex | None:
    if not geo_zip:
        return None
    try:
        with zipfile.ZipFile(geo_zip) as z:
            name = next(n for n in z.namelist() if n.endswith("admin3.geojson"))
            data = json.loads(z.read(name).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log(f"  ! cannot read admin3 polygons: {exc}")
        return None
    idx = PolygonIndex()
    for f in data["features"]:
        idx.add(f["properties"]["adm3_pcode"], f["geometry"])
    log(f"  loaded {len(data['features'])} admin3 polygons")
    return idx


# --------------------------------------------------------------------------
# Normalisers
# --------------------------------------------------------------------------
def v03_adm3(code8: str) -> str:
    """BD302614 (2011 census point code) -> BD30260014 (COD-AB v03 code)."""
    return code8[:6] + "00" + code8[6:] if code8 and len(code8) == 8 else code8


def normalise_hdx(xlsx: Path, poly: PolygonIndex | None) -> dict:
    import openpyxl  # imported lazily so build.py never needs it

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)

    def sheet(name):
        rows = list(wb[name].iter_rows(values_only=True))
        head = rows[0]
        return [dict(zip(head, r)) for r in rows[1:]]

    a1 = [{"pcode": r["adm1_pcode"], "name": r["adm1_name"],
           "lat": fmt_coord(r["center_lat"]), "lon": fmt_coord(r["center_lon"])}
          for r in sheet("bgd_admin1")]
    a2 = [{"pcode": r["adm2_pcode"], "name": r["adm2_name"], "adm1_pcode": r["adm1_pcode"],
           "lat": fmt_coord(r["center_lat"]), "lon": fmt_coord(r["center_lon"])}
          for r in sheet("bgd_admin2")]
    a3 = [{"pcode": r["adm3_pcode"], "name": r["adm3_name"], "adm2_pcode": r["adm2_pcode"],
           "type": "city_corporation" if "City Corporation" in r["adm3_name"] else "upazila",
           "lat": fmt_coord(r["center_lat"]), "lon": fmt_coord(r["center_lon"]),
           "area_sqkm": f"{float(r['area_sqkm']):.2f}" if r.get("area_sqkm") else "",
           "valid_on": r["valid_on"].date().isoformat() if r.get("valid_on") else ""}
          for r in sheet("bgd_admin3")]

    p3, p4 = [], []
    for r in sheet("bgd_adminpoints"):
        lvl = r["admin_level"]
        if lvl == 3:
            lon, lat = float(r["x_coord"]), float(r["y_coord"])
            p3.append({"pcode": r["adm3_pcode"], "v03_pcode": v03_adm3(r["adm3_pcode"]),
                       "name": r["adm3_name"], "adm2_pcode": r["adm2_pcode"],
                       "lat": fmt_coord(lat), "lon": fmt_coord(lon),
                       "pip_adm3_pcode": poly.lookup(lon, lat) if poly else ""})
        elif lvl == 4:
            low = (r["adm4_name"] or "").lower()
            kind = "ward" if "ward" in low else "paurashava" if "paurashava" in low else "union"
            p4.append({"pcode": r["adm4_pcode"], "name": r["adm4_name"], "kind": kind,
                       "adm3_pcode": r["adm3_pcode"], "v03_adm3_pcode": v03_adm3(r["adm3_pcode"]),
                       "adm3_name": r["adm3_name"], "adm2_pcode": r["adm2_pcode"],
                       "lat": fmt_coord(r["y_coord"]), "lon": fmt_coord(r["x_coord"])})
    for rows in (a1, a2, a3, p3, p4):
        rows.sort(key=lambda r: r["pcode"])
    return {"bbs_admin1": a1, "bbs_admin2": a2, "bbs_admin3": a3,
            "bbs_admin3_points": p3, "bbs_admin4_points": p4}


def normalise_geonames(zpath: Path, poly: PolygonIndex | None) -> list:
    with zipfile.ZipFile(zpath) as z:
        lines = z.read("BD.txt").decode("utf-8").splitlines()
    out = []
    for line in lines:
        c = line.split("\t")
        if len(c) < 11:
            continue
        dcode = GEONAMES_DISTRICT_REMAP.get(c[6], c[6])
        lat, lon = c[9], c[10]
        pip = ""
        if poly and lat and lon:
            pip = poly.lookup(float(lon), float(lat))
        out.append({"postcode": c[1], "post_office": c[2].strip(), "thana": c[7].strip(),
                    "district_pcode": f"BD{dcode}", "lat": fmt_coord(lat), "lon": fmt_coord(lon),
                    "pip_adm3_pcode": pip})
    out.sort(key=lambda r: (r["postcode"], r["post_office"]))
    return out


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true", help="use pipeline/.cache only")
    ap.add_argument("--refresh", action="store_true", help="re-download even if cache is fresh")
    args = ap.parse_args()
    global REFRESH
    REFRESH = args.refresh

    manifest_path = SOURCES_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()

    log("HDX COD-AB Bangladesh")
    urls, meta = hdx_resource_urls(args.offline)
    xlsx = download(urls["bgd_admin_boundaries.xlsx"], "bgd_admin_boundaries.xlsx", args.offline)
    geo = download(urls["bgd_admin_boundaries.geojson.zip"], "bgd_admin_boundaries.geojson.zip",
                   args.offline)
    poly = load_admin3_polygons(geo)

    if xlsx:
        try:
            tables = normalise_hdx(xlsx, poly)
            for name, rows in tables.items():
                write_csv(SOURCES_DIR / f"{name}.csv", list(rows[0].keys()), rows)
                log(f"  wrote sources/{name}.csv ({len(rows)} rows)")
            manifest["hdx_cod_ab_bgd"] = {
                "page": HDX_DATASET_PAGE, "xlsx_url": urls["bgd_admin_boundaries.xlsx"],
                "geojson_url": urls["bgd_admin_boundaries.geojson.zip"],
                "xlsx_sha256": sha256(xlsx), "geojson_used": bool(poly),
                "retrieved_at": now, **({"metadata": meta} if meta else
                                        {"metadata": manifest.get("hdx_cod_ab_bgd", {}).get("metadata", {})}),
            }
        except Exception as exc:  # noqa: BLE001
            log(f"  ! could not normalise HDX workbook ({exc}); keeping previous snapshot")
    else:
        log("  keeping previous HDX snapshot")

    log("GeoNames postal codes")
    gz = download(GEONAMES_URL, "geonames_BD.zip", args.offline, timeout=120)
    if gz:
        try:
            rows = normalise_geonames(gz, poly)
            write_csv(SOURCES_DIR / "geonames_postcodes.csv", list(rows[0].keys()), rows)
            log(f"  wrote sources/geonames_postcodes.csv ({len(rows)} rows)")
            manifest["geonames_postcodes"] = {
                "page": "https://download.geonames.org/export/zip/", "url": GEONAMES_URL,
                "license": "Creative Commons Attribution 4.0", "sha256": sha256(gz),
                "geometry_linked": bool(poly), "retrieved_at": now,
            }
        except Exception as exc:  # noqa: BLE001
            log(f"  ! could not normalise GeoNames file ({exc}); keeping previous snapshot")
    else:
        log("  keeping previous GeoNames snapshot")

    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    log("done. Now run: python pipeline/build.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
