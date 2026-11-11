"""Build every published data file from legacy data + source snapshots + manual edits.

    python pipeline/build.py

Inputs (all committed to the repo, so the build is offline and reproducible):
  pipeline/legacy/*.csv       the original 2019 dataset - the fallback layer
  pipeline/sources/*.csv      normalised snapshots written by fetch_sources.py
  pipeline/manual/*.csv       hand-curated aliases, overrides and additions
  pipeline/state/id_registry.csv  ids handed out to new records (keeps ids stable)

Outputs: <table>/<table>.{csv,json,php,sql,xml}, database/bd_geo_code.sql and
pipeline/reports/*.

Field precedence (highest first):
  name     manual override > official BBS/HDX name > legacy
  bn_name  manual override > legacy (sources carry no Bangla) > empty
  url      manual override > legacy > empty
  lat/lon  districts: legacy DC-office point > BBS centroid; others: BBS point
Records only present in legacy data are kept unchanged (bbs_code empty), so
nothing that existed before disappears.
"""
from __future__ import annotations

import collections
import json
import sys

from common import (LEGACY_DIR, MANUAL_DIR, REPO_DIR, REPORTS_DIR, SOURCES_DIR, STATE_DIR,
                    assign, fmt_coord, match_name, read_csv, similarity, write_csv)

# --------------------------------------------------------------------------
# Table schemas. Legacy columns come first, in their legacy order, so
# position-based consumers of the (header-less) CSVs keep working.
# (column, sql type, nullable)
# --------------------------------------------------------------------------
SCHEMAS = {
    "divisions": [("id", "int(2)", False), ("name", "varchar(50)", False),
                  ("bn_name", "varchar(50)", False), ("url", "varchar(100)", False),
                  ("bbs_code", "varchar(12)", True), ("lat", "varchar(15)", True),
                  ("lon", "varchar(15)", True)],
    "districts": [("id", "int(3)", False), ("division_id", "int(2)", False),
                  ("name", "varchar(50)", False), ("bn_name", "varchar(50)", False),
                  ("lat", "varchar(15)", True), ("lon", "varchar(15)", True),
                  ("url", "varchar(100)", False), ("bbs_code", "varchar(12)", True)],
    "upazilas": [("id", "int(4)", False), ("district_id", "int(3)", False),
                 ("name", "varchar(80)", False), ("bn_name", "varchar(80)", False),
                 ("url", "varchar(100)", False), ("bbs_code", "varchar(12)", True),
                 ("lat", "varchar(15)", True), ("lon", "varchar(15)", True)],
    "unions": [("id", "int(5)", False), ("upazilla_id", "int(4)", False),
               ("name", "varchar(80)", False), ("bn_name", "varchar(80)", False),
               ("url", "varchar(100)", False), ("bbs_code", "varchar(12)", True),
               ("lat", "varchar(15)", True), ("lon", "varchar(15)", True)],
    "city_corporations": [("id", "int(3)", False), ("division_id", "int(2)", False),
                          ("district_id", "int(3)", False), ("name", "varchar(80)", False),
                          ("bn_name", "varchar(80)", False), ("url", "varchar(100)", False),
                          ("bbs_code", "varchar(12)", True), ("lat", "varchar(15)", True),
                          ("lon", "varchar(15)", True)],
    "postcodes": [("id", "int(5)", False), ("division_id", "int(2)", False),
                  ("district_id", "int(3)", False), ("upazila_id", "int(4)", True),
                  ("city_corporation_id", "int(3)", True), ("thana", "varchar(80)", False),
                  ("post_office", "varchar(100)", False), ("postcode", "varchar(4)", False),
                  ("lat", "varchar(15)", True), ("lon", "varchar(15)", True),
                  ("link_method", "varchar(20)", False)],
}
FOREIGN_KEYS = {
    "districts": [("division_id", "divisions", "CASCADE")],
    "upazilas": [("district_id", "districts", "CASCADE")],
    "unions": [("upazilla_id", "upazilas", "CASCADE")],
    "city_corporations": [("division_id", "divisions", "CASCADE"),
                          ("district_id", "districts", "CASCADE")],
    "postcodes": [("division_id", "divisions", "CASCADE"), ("district_id", "districts", "CASCADE"),
                  ("upazila_id", "upazilas", "SET NULL"),
                  ("city_corporation_id", "city_corporations", "SET NULL")],
}
TABLE_ORDER = ["divisions", "districts", "upazilas", "unions", "city_corporations", "postcodes"]
LEGACY_COLS = {
    "divisions": ["id", "name", "bn_name", "url"],
    "districts": ["id", "division_id", "name", "bn_name", "lat", "lon", "url"],
    "upazilas": ["id", "district_id", "name", "bn_name", "url"],
    "unions": ["id", "upazilla_id", "name", "bn_name", "url"],
}

# Matching thresholds (see common.similarity)
TH_DIVISION, TH_DISTRICT, TH_UPAZILA = 0.6, 0.7, 0.75
TH_UNION_SAME_UPAZILA, TH_UNION_SAME_DISTRICT = 0.75, 0.88
TH_THANA = 0.85
LOW_CONFIDENCE = 0.9


# --------------------------------------------------------------------------
class IdRegistry:
    """Hands out stable ids for records that did not exist in the legacy data."""

    PATH = STATE_DIR / "id_registry.csv"

    def __init__(self):
        self.map = {(r["table"], r["key"]): int(r["id"]) for r in read_csv(self.PATH)}

    def get(self, table: str, key: str, taken: set) -> int:
        if (table, key) in self.map:
            return self.map[(table, key)]
        used = taken | {i for (t, _), i in self.map.items() if t == table}
        new = max(used, default=0) + 1
        self.map[(table, key)] = new
        return new

    def save(self):
        rows = [{"table": t, "key": k, "id": i} for (t, k), i in
                sorted(self.map.items(), key=lambda x: (TABLE_ORDER.index(x[0][0]), x[1]))]
        write_csv(self.PATH, ["table", "key", "id"], rows)


def load_legacy(table):
    return [dict(zip(LEGACY_COLS[table], r)) for r in read_csv(LEGACY_DIR / f"{table}.csv", header=False)]


def src(name):
    return read_csv(SOURCES_DIR / f"{name}.csv")


class Report:
    def __init__(self):
        self.lines, self.low, self.files = [], [], {}

    def add(self, line=""):
        self.lines.append(line)

    def match(self, table, legacy_id, legacy_name, bbs_code, bbs_name, score, how):
        if score < LOW_CONFIDENCE:
            self.low.append({"table": table, "legacy_id": legacy_id, "legacy_name": legacy_name,
                             "bbs_code": bbs_code, "bbs_name": bbs_name,
                             "score": f"{score:.2f}", "matched_by": how})


# --------------------------------------------------------------------------
# Build steps
# --------------------------------------------------------------------------
def build_divisions(rep, reg):
    legacy, bbs = load_legacy("divisions"), src("bbs_admin1")
    m = assign(legacy, bbs, lambda r: r["name"], lambda r: r["name"], TH_DIVISION)
    out, used = [], set()
    for i, l in enumerate(legacy):
        row = {**l, "bbs_code": None, "lat": None, "lon": None}
        if i in m:
            b, s = m[i]
            used.add(b["pcode"])
            row.update(name=b["name"], bbs_code=b["pcode"], lat=b["lat"], lon=b["lon"])
            rep.match("divisions", l["id"], l["name"], b["pcode"], b["name"], s, "name")
        out.append(row)
    taken = {int(r["id"]) for r in out}
    for b in bbs:
        if b["pcode"] not in used:
            out.append({"id": str(reg.get("divisions", b["pcode"], taken)), "name": b["name"],
                        "bn_name": "", "url": "", "bbs_code": b["pcode"], "lat": b["lat"], "lon": b["lon"]})
    return out


def build_districts(rep, reg, divisions):
    legacy, bbs = load_legacy("districts"), src("bbs_admin2")
    div_code = {d["id"]: d["bbs_code"] for d in divisions}
    div_by_code = {d["bbs_code"]: d["id"] for d in divisions if d["bbs_code"]}
    out, used = [], set()
    by_div = collections.defaultdict(list)
    for i, l in enumerate(legacy):
        by_div[l["division_id"]].append(i)
    matched = {}
    for div_id, idxs in by_div.items():
        cands = [b for b in bbs if b["adm1_pcode"] == div_code.get(div_id)]
        m = assign([legacy[i] for i in idxs], cands, lambda r: r["name"], lambda r: r["name"], TH_DISTRICT)
        for k, v in m.items():
            matched[idxs[k]] = v
    for i, l in enumerate(legacy):
        row = {**l, "bbs_code": None}
        if i in matched:
            b, s = matched[i]
            used.add(b["pcode"])
            row.update(name=b["name"], bbs_code=b["pcode"])
            # keep the precise legacy DC-office point; fall back to BBS centroid
            row["lat"] = l["lat"] or b["lat"]
            row["lon"] = l["lon"] or b["lon"]
            rep.match("districts", l["id"], l["name"], b["pcode"], b["name"], s, "name")
        out.append(row)
    taken = {int(r["id"]) for r in out}
    for b in bbs:
        if b["pcode"] not in used and b["adm1_pcode"] in div_by_code:
            out.append({"id": str(reg.get("districts", b["pcode"], taken)),
                        "division_id": div_by_code[b["adm1_pcode"]], "name": b["name"], "bn_name": "",
                        "lat": b["lat"], "lon": b["lon"], "url": "", "bbs_code": b["pcode"]})
    return out


def build_upazilas(rep, reg, districts, aliases):
    legacy = load_legacy("upazilas")
    bbs = [b for b in src("bbs_admin3") if b["type"] == "upazila"]
    bbs_by_code = {b["pcode"]: b for b in bbs}
    dist_code = {d["id"]: d["bbs_code"] for d in districts}
    dist_by_code = {d["bbs_code"]: d["id"] for d in districts if d["bbs_code"]}

    matched, used = {}, set()
    for i, l in enumerate(legacy):                      # 1. manual aliases
        code = aliases.get(("upazilas", l["id"]))
        if code and code in bbs_by_code:
            matched[i] = (bbs_by_code[code], 1.0, "manual_alias")
            used.add(code)
    by_dist = collections.defaultdict(list)             # 2. fuzzy within district
    for i, l in enumerate(legacy):
        if i not in matched:
            by_dist[l["district_id"]].append(i)
    for did, idxs in by_dist.items():
        cands = [b for b in bbs if b["adm2_pcode"] == dist_code.get(did) and b["pcode"] not in used]
        m = assign([legacy[i] for i in idxs], cands, lambda r: match_name(r["name"], r["bn_name"]),
                   lambda r: r["name"], TH_UPAZILA)
        for k, (b, s) in m.items():
            matched[idxs[k]] = (b, s, "name")
            used.add(b["pcode"])

    out, unmatched = [], []
    for i, l in enumerate(legacy):
        row = {**l, "bbs_code": None, "lat": None, "lon": None}
        if i in matched:
            b, s, how = matched[i]
            row.update(name=b["name"], bbs_code=b["pcode"], lat=b["lat"], lon=b["lon"])
            rep.match("upazilas", l["id"], l["name"], b["pcode"], b["name"], s, how)
        else:
            unmatched.append(l)
        out.append(row)
    taken = {int(r["id"]) for r in out}
    new = []
    for b in bbs:
        if b["pcode"] not in used and b["adm2_pcode"] in dist_by_code:
            row = {"id": str(reg.get("upazilas", b["pcode"], taken)),
                   "district_id": dist_by_code[b["adm2_pcode"]], "name": b["name"], "bn_name": "",
                   "url": "", "bbs_code": b["pcode"], "lat": b["lat"], "lon": b["lon"]}
            out.append(row)
            new.append(row)
    rep.files["unmatched_legacy_upazilas.csv"] = (LEGACY_COLS["upazilas"], unmatched)
    rep.add(f"- upazilas: {len(matched)} legacy matched to BBS, {len(unmatched)} legacy kept as-is, "
            f"{len(new)} added from BBS ({', '.join(r['name'] for r in new) or 'none'})")
    return out


def build_city_corporations(rep, reg, districts, manual_cc):
    dist = {d["bbs_code"]: d for d in districts if d["bbs_code"]}
    out = []
    for b in src("bbs_admin3"):
        if b["type"] != "city_corporation" or b["adm2_pcode"] not in dist:
            continue
        d = dist[b["adm2_pcode"]]
        cur = manual_cc.get(b["pcode"], {})
        out.append({"id": None, "division_id": d["division_id"], "district_id": d["id"],
                    "name": b["name"], "bn_name": cur.get("bn_name", ""), "url": cur.get("url", ""),
                    "bbs_code": b["pcode"], "lat": b["lat"], "lon": b["lon"]})
    taken = set()
    for r in sorted(out, key=lambda r: r["bbs_code"]):
        r["id"] = str(reg.get("city_corporations", r["bbs_code"], taken))
        taken.add(int(r["id"]))
    rep.add(f"- city_corporations: {len(out)} from BBS")
    return out


def build_unions(rep, reg, upazilas, districts, aliases):
    legacy = load_legacy("unions")
    pts = [p for p in src("bbs_admin4_points") if p["kind"] == "union"]
    upz = {u["id"]: u for u in upazilas}
    dist_code = {d["id"]: d["bbs_code"] for d in districts}

    lname = lambda r: match_name(r["name"], r["bn_name"])  # noqa: E731

    matched, used = {}, set()
    by_code = {p["pcode"]: p for p in pts}
    for i, l in enumerate(legacy):                      # 0. manual aliases
        code = aliases.get(("unions", l["id"]))
        if code and code in by_code:
            matched[i] = (by_code[code], 1.0, "manual_alias")
            used.add(code)
    groups = collections.defaultdict(list)
    for i, l in enumerate(legacy):
        if i not in matched:
            groups[l["upazilla_id"]].append(i)
    # pass 1: candidates inside the same upazila
    for uid, idxs in groups.items():
        code = (upz.get(uid) or {}).get("bbs_code")
        cands = [p for p in pts if code and p["v03_adm3_pcode"] == code and p["pcode"] not in used]
        m = assign([legacy[i] for i in idxs], cands, lname, lambda r: r["name"],
                   TH_UNION_SAME_UPAZILA)
        for k, (p, s) in m.items():
            matched[idxs[k]] = (p, s, "name_in_upazila")
            used.add(p["pcode"])
    # pass 2: leftovers, anywhere in the same district (handles upazila splits/renames)
    by_dist = collections.defaultdict(list)
    for i, l in enumerate(legacy):
        if i not in matched and l["upazilla_id"] in upz:
            by_dist[upz[l["upazilla_id"]]["district_id"]].append(i)
    for did, idxs in by_dist.items():
        cands = [p for p in pts if p["adm2_pcode"] == dist_code.get(did) and p["pcode"] not in used]
        m = assign([legacy[i] for i in idxs], cands, lname, lambda r: r["name"],
                   TH_UNION_SAME_DISTRICT)
        for k, (p, s) in m.items():
            matched[idxs[k]] = (p, s, "name_in_district")
            used.add(p["pcode"])

    out, unmatched = [], []
    for i, l in enumerate(legacy):
        row = {**l, "bbs_code": None, "lat": None, "lon": None}
        if i in matched:
            p, s, how = matched[i]
            # union names: keep the legacy spelling (it matches the union's own
            # website); BBS census spellings are often abbreviated.
            row.update(bbs_code=p["pcode"], lat=p["lat"], lon=p["lon"])
            rep.match("unions", l["id"], l["name"], p["pcode"], p["name"], s, how)
        else:
            unmatched.append(l)
        out.append(row)
    bbs_only = [p for p in pts if p["pcode"] not in used]
    rep.files["unmatched_legacy_unions.csv"] = (LEGACY_COLS["unions"], unmatched)
    rep.files["bbs_only_unions.csv"] = (list(pts[0].keys()) if pts else [], bbs_only)
    rep.add(f"- unions: {len(matched)} legacy matched to BBS (code + coordinates added), "
            f"{len(unmatched)} legacy kept as-is, {len(bbs_only)} BBS-only union points listed in "
            f"reports/bbs_only_unions.csv for review (not auto-added: the BBS union layer is "
            f"2011-census vintage and would re-introduce merged/abolished unions)")
    return out


def build_postcodes(rep, reg, districts, upazilas, ccs):
    rows = src("geonames_postcodes")
    dist = {d["bbs_code"]: d for d in districts if d["bbs_code"]}
    upz_by_code = {u["bbs_code"]: u for u in upazilas if u["bbs_code"]}
    cc_by_code = {c["bbs_code"]: c for c in ccs}
    upz_by_dist = collections.defaultdict(list)
    for u in upazilas:
        upz_by_dist[u["district_id"]].append(u)
    # 2011 census thanas/upazilas, with the v03 unit their point falls in
    thana_pts = collections.defaultdict(list)
    for p in src("bbs_admin3_points"):
        thana_pts[p["adm2_pcode"]].append(p)

    def best(name, cands, key):
        scored = [(similarity(name, key(c)), c) for c in cands]
        scored.sort(key=lambda x: -x[0])
        return scored[0] if scored else (0.0, None)

    out, counts, district_only = [], collections.Counter(), []
    taken = set()
    for r in rows:
        d = dist.get(r["district_pcode"])
        if not d:
            counts["no_district"] += 1
            continue
        upazila_id = cc_id = None
        how = "district"
        # 1. postal thana name == an upazila of the district
        s, u = best(r["thana"], upz_by_dist[d["id"]], lambda u: u["name"])
        if s >= TH_THANA:
            upazila_id, how = u["id"], "thana_name"
        else:
            # 2. postal thana name == a census (metropolitan) thana lying in a city corporation
            s, t = best(r["thana"], thana_pts[r["district_pcode"]], lambda t: t["name"])
            if s >= TH_THANA and t["pip_adm3_pcode"] in cc_by_code:
                cc_id, how = cc_by_code[t["pip_adm3_pcode"]]["id"], "metro_thana"
            # 3. the post office coordinate, only if it lies inside its own district
            elif r["pip_adm3_pcode"]:
                if r["pip_adm3_pcode"] in cc_by_code and \
                        cc_by_code[r["pip_adm3_pcode"]]["district_id"] == d["id"]:
                    cc_id, how = cc_by_code[r["pip_adm3_pcode"]]["id"], "coordinates"
                elif r["pip_adm3_pcode"] in upz_by_code and \
                        upz_by_code[r["pip_adm3_pcode"]]["district_id"] == d["id"]:
                    upazila_id, how = upz_by_code[r["pip_adm3_pcode"]]["id"], "coordinates"
        counts[how] += 1
        key = f"{r['postcode']}|{r['post_office']}"
        row = {"id": str(reg.get("postcodes", key, taken)), "division_id": d["division_id"],
               "district_id": d["id"], "upazila_id": upazila_id, "city_corporation_id": cc_id,
               "thana": r["thana"], "post_office": r["post_office"], "postcode": r["postcode"],
               "lat": r["lat"], "lon": r["lon"], "link_method": how}
        taken.add(int(row["id"]))
        out.append(row)
        if how == "district":
            district_only.append(row)
    rep.files["postcodes_district_only.csv"] = ([c for c, _, _ in SCHEMAS["postcodes"]], district_only)
    rep.add(f"- postcodes: {len(out)} post offices; linked by "
            + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return out


def apply_manual_additions(tables, reg, rep):
    n = 0
    for a in read_csv(MANUAL_DIR / "additions.csv"):
        t = a["table"]
        if t not in ("upazilas", "unions"):
            print(f"  ! additions.csv: unsupported table {t!r}", file=sys.stderr)
            continue
        parent_col = "district_id" if t == "upazilas" else "upazilla_id"
        parent_table = "districts" if t == "upazilas" else "upazilas"
        parent = next((p for p in tables[parent_table]
                       if a["parent_key"] in (p["id"], p.get("bbs_code"))), None)
        if not parent:
            print(f"  ! additions.csv: parent {a['parent_key']!r} not found for {a['name']!r}",
                  file=sys.stderr)
            continue
        taken = {int(r["id"]) for r in tables[t]}
        rid = reg.get(t, f"manual:{parent['id']}:{a['name']}", taken)
        tables[t].append({"id": str(rid), parent_col: parent["id"], "name": a["name"],
                          "bn_name": a.get("bn_name", ""), "url": a.get("url", ""),
                          "bbs_code": None, "lat": fmt_coord(a.get("lat")) or None,
                          "lon": fmt_coord(a.get("lon")) or None})
        n += 1
    for a in read_csv(MANUAL_DIR / "postcode_additions.csv"):
        taken = {int(r["id"]) for r in tables["postcodes"]}
        d = next((x for x in tables["districts"] if a["district_id"] == x["id"]), None)
        if not d:
            print(f"  ! postcode_additions.csv: district {a['district_id']!r} not found", file=sys.stderr)
            continue
        key = f"{a['postcode']}|{a['post_office']}"
        tables["postcodes"].append({
            "id": str(reg.get("postcodes", key, taken)), "division_id": d["division_id"],
            "district_id": d["id"], "upazila_id": a.get("upazila_id") or None,
            "city_corporation_id": a.get("city_corporation_id") or None, "thana": a["thana"],
            "post_office": a["post_office"], "postcode": a["postcode"],
            "lat": fmt_coord(a.get("lat")) or None, "lon": fmt_coord(a.get("lon")) or None,
            "link_method": "manual"})
        n += 1
    rep.add(f"- manual additions applied: {n}")


def apply_overrides(tables, rep):
    n = 0
    for o in read_csv(MANUAL_DIR / "overrides.csv"):
        t, key, field = o["table"], o["key"], o["field"]
        if t not in tables or field not in [c for c, _, _ in SCHEMAS[t]] or field == "id":
            print(f"  ! overrides.csv: bad table/field {t}.{field}", file=sys.stderr)
            continue
        hit = [r for r in tables[t]
               if (key.startswith("id:") and r["id"] == key[3:]) or r.get("bbs_code") == key]
        if not hit:
            print(f"  ! overrides.csv: no {t} row with key {key!r}", file=sys.stderr)
        for r in hit:
            r[field] = o["value"]
            n += 1
    rep.add(f"- manual overrides applied: {n}")


def validate(tables) -> list:
    errors = []
    ids = {t: {r["id"] for r in rows} for t, rows in tables.items()}
    for t, rows in tables.items():
        if len(ids[t]) != len(rows):
            errors.append(f"{t}: duplicate ids")
        for col, ref, _ in FOREIGN_KEYS.get(t, []):
            for r in rows:
                if r.get(col) not in (None, "") and r[col] not in ids[ref]:
                    errors.append(f"{t}.{r['id']}: {col}={r[col]} not in {ref}")
        for col, _, nullable in SCHEMAS[t]:
            if not nullable:
                for r in rows:
                    if r.get(col) is None:
                        errors.append(f"{t}.{r['id']}: {col} is null")
    return errors


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------
def _sql_val(v, sqltype):
    if v is None or (v == "" and sqltype.startswith("int")):
        return "NULL"
    if sqltype.startswith("int"):
        return str(int(v))
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def create_table_sql(t):
    cols = [f"  `{c}` {typ} {'DEFAULT NULL' if null else 'NOT NULL'}" for c, typ, null in SCHEMAS[t]]
    return f"CREATE TABLE `{t}` (\n" + ",\n".join(cols) + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"


def sql_body(t, rows):
    cols = SCHEMAS[t]
    names = ", ".join(f"`{c}`" for c, _, _ in cols)
    out = [f"--\n-- Table structure for table `{t}`\n--\n", f"DROP TABLE IF EXISTS `{t}`;",
           create_table_sql(t), f"\n--\n-- Dumping data for table `{t}`\n--\n"]
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        vals = ",\n".join("(" + ", ".join(_sql_val(r.get(c), typ) for c, typ, _ in cols) + ")"
                          for r in chunk)
        out.append(f"INSERT INTO `{t}` ({names}) VALUES\n{vals};\n")
    keys = ["  ADD PRIMARY KEY (`id`)"] + [f"  ADD KEY `{c}` (`{c}`)" for c, _, _ in FOREIGN_KEYS.get(t, [])]
    if any(c == "bbs_code" for c, _, _ in cols):
        keys.append("  ADD KEY `bbs_code` (`bbs_code`)")
    if t == "postcodes":
        keys.append("  ADD KEY `postcode` (`postcode`)")
    id_type = cols[0][1]
    max_id = max((int(r["id"]) for r in rows), default=0)
    out.append(f"--\n-- Indexes for table `{t}`\n--\nALTER TABLE `{t}`\n" + ",\n".join(keys) + ";\n")
    out.append(f"ALTER TABLE `{t}`\n  MODIFY `id` {id_type} NOT NULL AUTO_INCREMENT, "
               f"AUTO_INCREMENT={max_id + 1};\n")
    return "\n".join(out)


def sql_constraints(t):
    fks = FOREIGN_KEYS.get(t, [])
    if not fks:
        return ""
    lines = [f"  ADD CONSTRAINT `{t}_fk_{c}` FOREIGN KEY (`{c}`) REFERENCES `{ref}` (`id`) "
             f"ON DELETE {act} ON UPDATE CASCADE" for c, ref, act in fks]
    return f"--\n-- Constraints for table `{t}`\n--\nALTER TABLE `{t}`\n" + ",\n".join(lines) + ";\n"


SQL_HEAD = """-- Bangladesh GeoCode - generated by pipeline/build.py, do not edit by hand.
-- Edit pipeline/manual/*.csv instead and rebuild. Sources: see README.md
{sources}
SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET FOREIGN_KEY_CHECKS = 0;
SET AUTOCOMMIT = 0;
START TRANSACTION;
SET NAMES utf8mb4;
"""
SQL_TAIL = "SET FOREIGN_KEY_CHECKS = 1;\nCOMMIT;\n"


def _php_val(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _xml(v):
    return (str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def write_table(t, rows, sources_line):
    cols = [c for c, _, _ in SCHEMAS[t]]
    d = REPO_DIR / t
    d.mkdir(exist_ok=True)

    def val(r, c):
        v = r.get(c)
        return None if v in (None, "") and dict((x, n) for x, _, n in SCHEMAS[t])[c] else (v or "")

    # CSV - header-less like the legacy files, every field quoted
    with (d / f"{t}.csv").open("w", encoding="utf-8", newline="") as fh:
        for r in rows:
            fh.write(",".join('"' + str(r.get(c) or "").replace('"', '""') + '"' for c in cols) + "\n")
    # JSON - same phpMyAdmin envelope as before (values are strings, nulls are null)
    data = [{c: (None if val(r, c) is None else str(val(r, c))) for c in cols} for r in rows]
    js = ('[\n{"type":"header","version":"bd-geocode-pipeline","comment":"Generated by '
          'pipeline/build.py"},\n{"type":"database","name":"bd_geo_code"},\n'
          f'{{"type":"table","name":"{t}","database":"bd_geo_code","data":\n[\n'
          + ",\n".join(json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in data)
          + "\n]\n}\n]\n")
    (d / f"{t}.json").write_text(js, encoding="utf-8", newline="\n")
    # PHP array
    php = ["<?php", "/**", " * Bangladesh GeoCode - generated by pipeline/build.py, do not edit by hand.",
           " */", "", f"/* `bd_geo_code`.`{t}` */", f"${t} = array("]
    php.append(",\n".join("  array(" + ",".join(f"'{c}' => {_php_val(val(r, c))}" for c in cols) + ")"
                          for r in rows))
    php.append(");\n")
    (d / f"{t}.php").write_text("\n".join(php), encoding="utf-8", newline="\n")
    # SQL (one table per file; constraints included like the legacy dumps)
    sql = SQL_HEAD.format(sources=sources_line) + "\n" + sql_body(t, rows) + "\n" + sql_constraints(t) + SQL_TAIL
    (d / f"{t}.sql").write_text(sql, encoding="utf-8", newline="\n")
    # XML (phpMyAdmin XML export layout)
    x = ['<?xml version="1.0" encoding="utf-8"?>',
         "<!-- Bangladesh GeoCode - generated by pipeline/build.py, do not edit by hand. -->",
         '<pma_xml_export version="1.0" xmlns:pma="https://www.phpmyadmin.net/some_doc_url/">',
         "    <pma:structure_schemas>",
         '        <pma:database name="bd_geo_code" collation="utf8mb4_general_ci" charset="utf8mb4">',
         f'            <pma:table name="{t}">',
         "\n".join("                " + line for line in create_table_sql(t).splitlines()),
         "            </pma:table>", "        </pma:database>", "    </pma:structure_schemas>",
         '    <database name="bd_geo_code">', f"        <!-- Table {t} -->"]
    for r in rows:
        x.append(f'        <table name="{t}">')
        for c in cols:
            v = val(r, c)
            x.append(f'            <column name="{c}"' + (" />" if v is None else f">{_xml(v)}</column>"))
        x.append("        </table>")
    x += ["    </database>", "</pma_xml_export>", ""]
    (d / f"{t}.xml").write_text("\n".join(x), encoding="utf-8", newline="\n")


def write_combined_sql(tables, sources_line):
    d = REPO_DIR / "database"
    d.mkdir(exist_ok=True)
    parts = [SQL_HEAD.format(sources=sources_line)]
    parts += [sql_body(t, tables[t]) for t in TABLE_ORDER]
    parts += [sql_constraints(t) for t in TABLE_ORDER]
    parts.append(SQL_TAIL)
    (d / "bd_geo_code.sql").write_text("\n".join(parts), encoding="utf-8", newline="\n")


# --------------------------------------------------------------------------
def main() -> int:
    rep, reg = Report(), IdRegistry()
    aliases = {(a["table"], a["legacy_id"]): a["bbs_pcode"] for a in read_csv(MANUAL_DIR / "aliases.csv")}
    manual_cc = {c["bbs_pcode"]: c for c in read_csv(MANUAL_DIR / "city_corporations.csv")}
    have_bbs = bool(src("bbs_admin3"))
    if not have_bbs:
        print("! no BBS snapshot found - building from legacy data only (fallback)", file=sys.stderr)

    tables = {}
    tables["divisions"] = build_divisions(rep, reg)
    tables["districts"] = build_districts(rep, reg, tables["divisions"])
    tables["upazilas"] = build_upazilas(rep, reg, tables["districts"], aliases)
    tables["city_corporations"] = build_city_corporations(rep, reg, tables["districts"], manual_cc)
    tables["unions"] = build_unions(rep, reg, tables["upazilas"], tables["districts"], aliases)
    tables["postcodes"] = build_postcodes(rep, reg, tables["districts"], tables["upazilas"],
                                          tables["city_corporations"])
    apply_manual_additions(tables, reg, rep)
    apply_overrides(tables, rep)
    for t in tables:
        tables[t].sort(key=lambda r: int(r["id"]))

    errors = validate(tables)
    if errors:
        print("Validation failed:\n  " + "\n  ".join(errors[:50]), file=sys.stderr)
        return 1

    manifest = {}
    mpath = SOURCES_DIR / "manifest.json"
    if mpath.exists():
        manifest = json.loads(mpath.read_text("utf-8"))
    sources_line = "\n".join(f"-- {k}: retrieved {v.get('retrieved_at', '?')}" for k, v in manifest.items()) \
        or "-- (legacy data only)"
    for t in TABLE_ORDER:
        write_table(t, tables[t], sources_line)
    write_combined_sql(tables, sources_line)
    reg.save()

    # reports
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, (cols, rows) in rep.files.items():
        write_csv(REPORTS_DIR / name, cols, rows)
    rep.low.sort(key=lambda r: (r["table"], float(r["score"])))
    write_csv(REPORTS_DIR / "low_confidence_matches.csv",
              ["table", "legacy_id", "legacy_name", "bbs_code", "bbs_name", "score", "matched_by"], rep.low)
    summary = ["# Build report", "", "Generated by `pipeline/build.py`.", "",
               "| table | rows | with bbs_code |", "|---|---:|---:|"]
    for t in TABLE_ORDER:
        n = sum(1 for r in tables[t] if r.get("bbs_code"))
        summary.append(f"| {t} | {len(tables[t])} | {n if 'bbs_code' in [c for c, _, _ in SCHEMAS[t]] else '-'} |")
    summary += ["", "## Notes", ""] + rep.lines + [
        "", f"- {len(rep.low)} matches below {LOW_CONFIDENCE} similarity are listed in "
            "`low_confidence_matches.csv`; fix a wrong one with `manual/aliases.csv`.", ""]
    (REPORTS_DIR / "build_report.md").write_text("\n".join(summary), encoding="utf-8", newline="\n")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
