"""Shared helpers for the Bangladesh GeoCode data pipeline.

Only the Python standard library is used here so that `build.py` runs
anywhere without extra installs. `fetch_sources.py` additionally needs
`openpyxl` (see requirements.txt) to read the HDX workbook.
"""
from __future__ import annotations

import csv
import difflib
import re
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parent
REPO_DIR = PIPELINE_DIR.parent
LEGACY_DIR = PIPELINE_DIR / "legacy"
SOURCES_DIR = PIPELINE_DIR / "sources"
MANUAL_DIR = PIPELINE_DIR / "manual"
STATE_DIR = PIPELINE_DIR / "state"
REPORTS_DIR = PIPELINE_DIR / "reports"


# --------------------------------------------------------------------------
# CSV helpers
# --------------------------------------------------------------------------
def read_csv(path: Path, header: bool = True) -> list:
    """Read a UTF-8 CSV. Returns list of dicts (header) or list of lists."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        if header:
            return [dict(r) for r in csv.DictReader(fh)
                    if any((v or "").strip() for v in r.values())]
        return [r for r in csv.reader(fh) if r]


def write_csv(path: Path, fieldnames: list, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})


# --------------------------------------------------------------------------
# Name normalisation / fuzzy matching
# --------------------------------------------------------------------------
# Words that differ only by language between sources ("North X" vs "Uttar X").
_WORD_MAP = {
    "north": "uttar", "uttor": "uttar", "uttara": "uttar",
    "south": "dakshin", "dakkhin": "dakshin", "dakhin": "dakshin", "dokkhin": "dakshin",
    "dakshina": "dakshin",
    "east": "purba", "purbo": "purba", "purb": "purba",
    "west": "paschim", "poschim": "paschim", "pashchim": "paschim",
    "middle": "madhya", "moddho": "madhya", "maddha": "madhya", "central": "madhya",
    "boro": "bara", "baro": "bara", "chhoto": "chota", "choto": "chota",
}
# Generic words that carry no identity.
_STOP = {"sadar", "upazila", "upazilla", "union", "parishad", "up", "no", "the",
         "city", "corporation", "division", "district", "zila", "thana", "model"}


def _phonetic(s: str) -> str:
    """Collapse common Bangla->Latin transliteration variants."""
    s = re.sub(r"[^a-z]", "", s.lower())
    s = re.sub(r"c(?!h)", "k", s)  # Dacope ~ Dakop
    for a, b in (("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("bh", "b"),
                 ("dh", "d"), ("th", "t"), ("jh", "j"), ("ph", "f"), ("rh", "r"),
                 ("w", "o"), ("v", "b"), ("z", "j"), ("q", "k"), ("y", "i"),
                 ("ee", "i"), ("oo", "u"), ("ou", "o"), ("ow", "o"), ("h", ""),
                 ("o", "a"), ("e", "i")):
        s = s.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", s)  # drop doubled letters


_DIRECTIONS = {"uttar", "dakshin", "purba", "paschim", "madhya"}


def _words(text: str) -> list:
    return [_WORD_MAP.get(t, t) for t in re.sub(r"[^a-z]+", " ", text.lower()).split()]


_BN_DIRECTIONS = {"উত্তর": "uttar", "দক্ষিণ": "dakshin", "পূর্ব": "purba",
                  "পশ্চিম": "paschim", "মধ্য": "madhya"}


def match_name(name: str, bn_name: str = "") -> str:
    """English name plus any direction spelled out only in the Bangla name.

    e.g. ("Nabinagarw", "নবীনগর(পশ্চিম)") -> "Nabinagarw paschim"
    """
    have = directions(name)
    # whole words only: পূর্বধলা (Purbadhala) is a name, not "East Dhala"
    bn_words = re.split(r"[\s()\-,.]+", bn_name or "")
    extra = [_BN_DIRECTIONS[w] for w in bn_words if w in _BN_DIRECTIONS and _BN_DIRECTIONS[w] not in have]
    return " ".join([name or ""] + extra)


def directions(name: str) -> set:
    """Direction words anywhere in the name, including '(South)' style suffixes."""
    return {w for w in _words(name or "") if w in _DIRECTIONS}


def tokens(name: str, keep_parenthetical: bool = False) -> list:
    s = (name or "").replace("&", " ")
    if keep_parenthetical:
        s = s.replace("(", " ").replace(")", " ")
    else:
        # parenthetical notes are usually alternates ("Atbar Pur (Paschim Chandina)"),
        # but a bare direction in brackets ("Belgor (South)") is part of the name
        s = re.sub(r"\((.*?)\)",
                   lambda m: " " + m.group(1) + " " if set(_words(m.group(1))) <= _DIRECTIONS else " ", s)
    return [p for p in (_phonetic(t) for t in _words(s) if t not in _STOP) if p]


def _ratio(ta: list, tb: list) -> float:
    joined = difflib.SequenceMatcher(None, "".join(ta), "".join(tb)).ratio()
    ordered = difflib.SequenceMatcher(None, "".join(sorted(ta)), "".join(sorted(tb))).ratio()
    return max(joined, ordered)


def similarity(a: str, b: str) -> float:
    """0..1 similarity of two place names, order-insensitive.

    Names whose direction words conflict ("North X" vs "Dakshin X") are
    heavily penalised so that sibling unions are never cross-assigned.
    """
    da, db = directions(a), directions(b)
    if da and db and not (da & db):
        penalty = 0.5
    elif bool(da) != bool(db):
        penalty = 0.9   # "Singerbil" vs "Dakshin Singerbil": possible, but weaker
    else:
        penalty = 1.0
    best = 0.0
    for ka in (False, True):
        for kb in (False, True):
            ta, tb = tokens(a, ka), tokens(b, kb)
            if ta and tb:
                best = max(best, _ratio(ta, tb))
    if best == 0.0:
        # fall back to the raw string (e.g. "Sadar" alone)
        ra, rb = _phonetic(a or ""), _phonetic(b or "")
        best = difflib.SequenceMatcher(None, ra, rb).ratio() if ra and rb else 0.0
    return best * penalty


def assign(left: list, right: list, lname, rname, threshold: float) -> dict:
    """Greedy one-to-one matching by descending similarity.

    Returns {id(left_item): (right_item, score)} for pairs >= threshold.
    """
    pairs = []
    for i, l in enumerate(left):
        for j, r in enumerate(right):
            s = similarity(lname(l), rname(r))
            if s >= threshold:
                pairs.append((s, i, j))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    used_l, used_r, out = set(), set(), {}
    for s, i, j in pairs:
        if i in used_l or j in used_r:
            continue
        used_l.add(i)
        used_r.add(j)
        out[i] = (right[j], s)
    return out


def fmt_coord(v) -> str:
    if v in (None, ""):
        return ""
    return f"{float(v):.6f}".rstrip("0").rstrip(".")
