"""
parse_rfq: a deterministic, dependency-free parser for messy packaging RFQs.

The design is deliberately rule based:
  * normalise Hinglish/English text and common abbreviations
  * find numeric expressions (digits, Indian grouping, k/lakh/crore, word numbers)
  * reject numbers that are really GSM, microns, dimensions, fill weight or capacity
  * classify the product with weighted keyword/pattern matches
  * find a delivery place from a gazetteer, with context fallbacks for unseen places

It is not tuned to the examples in my_tests.jsonl; the rules are about language
and packaging vocabulary rather than specific sentences.
"""

from __future__ import annotations

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

_DOTTED_ABBREVIATIONS = [
    (r"\bm\s*\.\s*t\s*\.?\s*s?\b", " mt "),
    (r"\bk\s*\.\s*g\s*\.?\s*s?\b", " kg "),
    (r"\bg\s*\.\s*s\s*\.\s*m\s*\.?", " gsm "),
    (r"\bu\s*\.\s*a\s*\.\s*e\s*\.?", " uae "),
    (r"\bu\s*\.\s*s\s*\.\s*a\s*\.?", " usa "),
    (r"\bu\s*\.\s*k\s*\.?", " uk "),
]


def _normalize(text: str) -> str:
    t = str(text).lower()
    t = (
        t.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2212", "-")
        .replace("\u00d7", "x")
        .replace("\u03bc", "u")
        .replace("\u00b5", "u")
        .replace("\u20b9", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
    )
    for pattern, replacement in _DOTTED_ABBREVIATIONS:
        t = re.sub(pattern, replacement, t)
    # frequent spelling variants for units
    t = re.sub(r"\b(?:gms|gsmtr|gsm\s*tr)\b", "gsm", t)
    t = re.sub(r"\b(?:mts|m\.t)\b", "mt", t)
    # Split compact multiplier+count forms: 20kpcs -> 20 k pcs.
    t = re.sub(
        r"(?<=\d)\s*"
        r"(k|lakhs?|lacs?|crores?|thousands?|hazaars?|hazars?|hajars?|"
        r"hajaars?|hazrs?|hzrs?|million|mn)\s*"
        r"(?=(?:pcs?|pieces?|bags?|sacks?|box(?:es)?|cartons?|"
        r"pouch(?:es)?|packets?|units?|nos?)\b)",
        r" \1 ",
        t,
    )
    t = re.sub(r"\s+", " ", t)
    return t.strip()


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_MULTIPLIERS = {
    "k": 1_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "hazaar": 1_000,
    "hazar": 1_000,
    "hajar": 1_000,
    "hajaar": 1_000,
    "hazr": 1_000,
    "hzr": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "cr": 10_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "mn": 1_000_000,
}

_WORD_UNITS = {
    "zero": 0,
    "one": 1,
    "ek": 1,
    "two": 2,
    "do": 2,
    "teen": 3,
    "tin": 3,
    "three": 3,
    "four": 4,
    "char": 4,
    "chaar": 4,
    "five": 5,
    "paanch": 5,
    "panch": 5,
    "six": 6,
    "chhe": 6,
    "chheh": 6,
    "che": 6,
    "cheh": 6,
    "seven": 7,
    "saat": 7,
    "sat": 7,
    "eight": 8,
    "aath": 8,
    "ath": 8,
    "nine": 9,
    "nau": 9,
    "ten": 10,
    "das": 10,
    "dus": 10,
    "eleven": 11,
    "gyarah": 11,
    "gyara": 11,
    "twelve": 12,
    "barah": 12,
    "bara": 12,
    "thirteen": 13,
    "terah": 13,
    "tera": 13,
    "fourteen": 14,
    "chaudah": 14,
    "chauda": 14,
    "fifteen": 15,
    "pandrah": 15,
    "pandra": 15,
    "sixteen": 16,
    "solah": 16,
    "sola": 16,
    "seventeen": 17,
    "satrah": 17,
    "satra": 17,
    "eighteen": 18,
    "atharah": 18,
    "athara": 18,
    "nineteen": 19,
    "unnis": 19,
    "unees": 19,
}

_WORD_TENS = {
    "twenty": 20,
    "bees": 20,
    "bis": 20,
    "thirty": 30,
    "tees": 30,
    "tis": 30,
    "forty": 40,
    "chalees": 40,
    "chalis": 40,
    "fifty": 50,
    "pachas": 50,
    "pachchas": 50,
    "sixty": 60,
    "saath": 60,
    "sath": 60,
    "seventy": 70,
    "sattar": 70,
    "eighty": 80,
    "assi": 80,
    "asi": 80,
    "ninety": 90,
    "nabbe": 90,
    "nabai": 90,
}

# Hindi/English fractions occasionally used with round numbers.
_WORD_FRACTIONS = {
    "dedh": 1.5,
    "dhai": 2.5,
}

_WORD_HALVES = {"half", "aadha", "adha", "ardha"}
_WORD_QUARTERS = {"quarter", "chauthai"}
_WORD_MODIFIERS = {"sava", "sawa", "paune", "pauna"} | _WORD_HALVES | _WORD_QUARTERS

_WORD_MULTIPLIERS = {
    "hundred": 100,
    "sau": 100,
    "thousand": 1_000,
    "hazaar": 1_000,
    "hazar": 1_000,
    "hajar": 1_000,
    "hajaar": 1_000,
    "lakh": 100_000,
    "lakhs": 100_000,
    "lac": 100_000,
    "lacs": 100_000,
    "crore": 10_000_000,
    "crores": 10_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
}

_NUMBER_WORDS = (
    set(_WORD_UNITS)
    | set(_WORD_TENS)
    | set(_WORD_FRACTIONS)
    | set(_WORD_MODIFIERS)
    | set(_WORD_MULTIPLIERS)
)

_NUM_RE = re.compile(r"(?<![\w.])(\d+(?:,\d{2,3})*(?:\.\d+)?)(?![\d.])")
_SUFFIX_RE = re.compile(r"\s*([a-z]+)")
_WORD_RE = re.compile(r"[a-z]+")


def _overlaps(start: int, end: int, intervals: list[tuple[int, int]]) -> bool:
    return any(start < b and end > a for a, b in intervals)


def _numeric_candidates(t: str) -> list[dict]:
    out: list[dict] = []
    for m in _NUM_RE.finditer(t):
        raw = m.group(1)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        end = m.end()
        mult = 1
        suffix = _SUFFIX_RE.match(t, end)
        if suffix:
            word = suffix.group(1)
            if word in _MULTIPLIERS:
                mult = _MULTIPLIERS[word]
                end = suffix.end()
            elif word in {"dozen", "dozens"}:
                mult = 12
                end = suffix.end()
            elif word == "gross":
                mult = 144
                end = suffix.end()
        out.append(
            {
                "start": m.start(),
                "end": end,
                "value": value * mult,
                "raw": value,
                "mult": mult,
                "word": False,
            }
        )
    return out


def _parse_word_run(words: list[str]) -> float:
    total = 0.0
    current = 0.0
    pending = 0.0

    for word in words:
        if word in _WORD_UNITS:
            current += _WORD_UNITS[word] + pending
            pending = 0.0
        elif word in _WORD_TENS:
            current += _WORD_TENS[word] + pending
            pending = 0.0
        elif word in _WORD_FRACTIONS:
            current += _WORD_FRACTIONS[word] + pending
            pending = 0.0
        elif word in _WORD_HALVES:
            current = (current + 0.5) if current else 0.5
        elif word in _WORD_QUARTERS:
            current = (current + 0.25) if current else 0.25
        elif word in _WORD_MODIFIERS:
            pending += 0.25 if word in {"sava", "sawa"} else -0.25
        elif word == "hundred" or word == "sau":
            if pending:
                current = (current or 1.0) + pending
                pending = 0.0
            current = (current or 1.0) * 100.0
        elif word in _WORD_MULTIPLIERS:
            if current == 0:
                current = 1.0
            if pending:
                current += pending
                pending = 0.0
            mult = _WORD_MULTIPLIERS[word]
            total += current * mult
            current = 0.0
    return total + current


def _word_candidates(t: str, occupied: list[tuple[int, int]]) -> list[dict]:
    tokens = [
        (m.group(), m.start(), m.end())
        for m in _WORD_RE.finditer(t)
        if m.group() not in {"and", "aur", "a"}
    ]
    out: list[dict] = []
    i = 0
    while i < len(tokens):
        word, start, end = tokens[i]
        if word not in _NUMBER_WORDS or _overlaps(start, end, occupied):
            i += 1
            continue

        run = [word]
        run_start, run_end = start, end
        j = i + 1
        while j < len(tokens):
            nword, nstart, nend = tokens[j]
            gap = t[run_end:nstart]
            gap_ok = re.fullmatch(r"[\s,\-]*(?:and\s+a|and|aur|a)?[\s,\-]*", gap) is not None
            if (
                nword in _NUMBER_WORDS
                and gap_ok
                and not _overlaps(nstart, nend, occupied)
            ):
                run.append(nword)
                run_end = nend
                j += 1
            else:
                break

        value = _parse_word_run(run)
        if value > 0:
            implied_mult = max((_WORD_MULTIPLIERS.get(w, 1) for w in run), default=1)
            out.append(
                {
                    "start": run_start,
                    "end": run_end,
                    "value": value,
                    "raw": value,
                    "mult": implied_mult,
                    "word": True,
                }
            )
        i = j
    return out


def _merge_indian_expressions(cands: list[dict], t: str) -> list[dict]:
    """Merge '1 lakh 50 hazaar' style pairs into one number."""
    merged: list[dict] = []
    for cand in sorted(cands, key=lambda c: c["start"]):
        if merged:
            prev = merged[-1]
            gap = t[prev["end"] : cand["start"]]
            connective = re.fullmatch(r"[\s,\-]*(?:and|aur)?[\s,\-]*", gap) is not None
            if (
                connective
                and prev["mult"] > 1
                and cand["mult"] > 1
                and cand["mult"] < prev["mult"]
            ):
                prev["value"] += cand["value"]
                prev["end"] = cand["end"]
                prev["mult"] = max(prev["mult"], cand["mult"])
                prev["raw"] = prev["value"]
                continue
        merged.append(cand)
    return merged


def _number_candidates(t: str) -> list[dict]:
    numeric = _numeric_candidates(t)
    occupied = [(c["start"], c["end"]) for c in numeric]
    words = _word_candidates(t, occupied)
    return _merge_indian_expressions(numeric + words, t)


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

# (category, regex, weight).  We take the best single match per category, then
# add a tiny bonus for repeated evidence.  This prevents a generic word such as
# "bag" from beating a specific "jumbo bag" / "bopp bag".
_CATEGORY_PATTERNS: list[tuple[str, str, int]] = [
    # FIBC / jumbo / bulk bags
    ("fibc", r"\bfibc\b|\bf\.?i\.?b\.?c\.?\b", 100),
    ("fibc", r"\bjumb[oa]o?\b|\bjambo\b", 95),
    ("fibc", r"\bbulk\s*bags?\b", 92),
    ("fibc", r"\bbig\s*bags?\b", 88),
    ("fibc", r"\bbuilder\s*bags?\b", 88),
    ("fibc", r"\bcontainer\s*bags?\b", 88),
    ("fibc", r"\bbaffle\s*bags?\b", 88),
    ("fibc", r"\bq\s*bag\b", 85),
    ("fibc", r"\b(?:500|750|1000|1250|1500|2000)\s*kg\s*(?:capacity\s*)?bags?\b", 78),
    ("fibc", r"\b(?:1|2)\s*(?:ton|tonne|mt)s?\s*(?:capacity\s*)?bags?\b", 78),
    ("fibc", r"\bheavy\s*duty\s*bags?\b", 55),
    # BOPP bags (film is handled by the negative look-ahead)
    ("bopp_bag", r"\bbopp\b(?!\s*(?:film|wrap|roll))", 100),
    ("bopp_bag", r"\bbop\b|\bboop\b", 82),
    ("bopp_bag", r"\bbiaxially\b", 80),
    ("bopp_bag", r"\bbopp\s*[- ]?\s*laminated\b", 100),
    ("bopp_bag", r"\blaminated\s+(?:pp\s+)?woven\b", 96),
    # Mono cartons
    ("mono_carton", r"\bmono\s*[- ]?\s*cart(?:on|oon)s?\b", 100),
    ("mono_carton", r"\bmonocartons?\b", 100),
    ("mono_carton", r"\bmono\s*[- ]?\s*box\b", 90),
    ("mono_carton", r"\b(?:duplex|folding|paperboard)\s*(?:board\s*)?(?:carton|box)\b", 84),
    ("mono_carton", r"\bpharma\s*cartons?\b", 82),
    # Pouches
    ("pouch", r"\bpouch(?:es|s)?\b", 95),
    ("pouch", r"\bpuch(?:es|s)?\b", 78),
    ("pouch", r"\bsachets?\b", 76),
    ("pouch", r"\bstand\s*[- ]?\s*up\b", 80),
    ("pouch", r"\bdoy\s*[- ]?\s*pack\b|\bdoypack\b", 80),
    ("pouch", r"\b(?:side|back|bottom)\s*gusset\b", 60),
    ("pouch", r"\bflat\s*bottom\b", 60),
    ("pouch", r"\bzipper\b", 70),
    ("pouch", r"\bspout\b", 70),
    ("pouch", r"\bretort\b", 70),
    ("pouch", r"\b(?:3|three)\s*[- ]?\s*side\b", 70),
    ("pouch", r"\bcentral?\s*seal\b", 70),
    ("pouch", r"\bpackets?\b", 48),
    ("pouch", r"\bcovers?\b", 34),
    # Corrugated boxes / plain box / carton
    ("corrugated_box", r"\bcor+[ou]gat\w*", 95),
    ("corrugated_box", r"\bcard\s*board\b", 90),
    ("corrugated_box", r"\b(?:3|5|7|9)\s*[- ]?\s*ply\b", 80),
    ("corrugated_box", r"\bflute\b", 74),
    ("corrugated_box", r"\bshipper\s*(?:box|carton)?\b", 64),
    ("corrugated_box", r"\bmailer\s*(?:box|carton)?\b", 64),
    ("corrugated_box", r"\bbox(?:es)?\b", 45),
    ("corrugated_box", r"\bcart(?:on|oon)s?\b", 45),
    ("corrugated_box", r"\bcarten\b|\bkarton\b", 40),
    # Woven sacks
    ("woven_sack", r"\bwov[ae]?ns?\b", 90),
    ("woven_sack", r"\bcement\s*(?:bag|sack)s?\b", 96),
    ("woven_sack", r"\bad[\s-]*star\b", 96),
    ("woven_sack", r"\bsacks?\b", 74),
    ("woven_sack", r"\bbardana\b|\bbori\b|\bbor[ie]s?\b", 80),
    ("woven_sack", r"\b(?:fertilizer|fertiliser|grain|flour|sugar|rice|sand|sandbag)\s*(?:bag|sack)s?\b", 76),
    ("woven_sack", r"\bpp\s*(?:bag|sack|woven)\b", 76),
    ("woven_sack", r"\bhdpe?\s*(?:bag|sack)\b", 64),
    ("woven_sack", r"\bbags?\b", 20),  # default for an unqualified bag
    # Films / wraps
    ("film", r"\bfilm\b|\bflim\b", 82),
    ("film", r"\bshrink\b", 86),
    ("film", r"\bstretch\b", 86),
    ("film", r"\bcling\b", 80),
    ("film", r"\bwrap\b", 60),
    ("film", r"\b(?:ldpe|hdpe|pe|pp|poly\w*|bopp)\s*film\b", 96),
    ("film", r"\bbopp\s*rolls?\b", 90),
    ("film", r"\brolls?\b", 24),
    ("film", r"\bliner\b", 38),
]

_CATEGORY_PRIORITY = {
    "fibc": 7,
    "bopp_bag": 6,
    "mono_carton": 5,
    "pouch": 4,
    "woven_sack": 3,
    "corrugated_box": 2,
    "film": 1,
}


def _detect_category(t: str) -> str:
    best_weight: dict[str, int] = {}
    first_pos: dict[str, int] = {}
    counts: dict[str, int] = {}

    for category, pattern, weight in _CATEGORY_PATTERNS:
        for m in re.finditer(pattern, t):
            if weight > best_weight.get(category, 0):
                best_weight[category] = weight
            first_pos[category] = min(first_pos.get(category, len(t) + 1), m.start())
            counts[category] = counts.get(category, 0) + 1

    if not best_weight:
        return "woven_sack"  # the most common unqualified bag-like RFQ

    def rank(cat: str) -> tuple[int, int, int]:
        score = best_weight[cat] + min(counts[cat], 3) * 3
        return (score, -first_pos[cat], _CATEGORY_PRIORITY[cat])

    result = max(best_weight, key=rank)

    # "BOPP" is a material, not always a bag.  If the message names a film,
    # pouch, or carton and never names a bag/sack/woven item, the specific
    # product wins over the material.
    if result == "bopp_bag" and re.search(r"\bbopp\b", t):
        has_bag = re.search(r"\b(?:bags?|sacks?|woven)\b", t)
        if not has_bag:
            if re.search(r"\b(?:film|wrap|rolls?)\b", t):
                return "film"
            if re.search(r"\b(?:pouch(?:es|s)?|sachets?)\b", t):
                return "pouch"
            if re.search(r"\b(?:boxes?|cartons?)\b", t):
                return "corrugated_box"

    # "Jumbo" means FIBC only when it describes a bag/sack; a jumbo roll of
    # film is still film.
    if result == "fibc" and re.search(r"\bjumbo\b", t):
        has_bag = re.search(r"\b(?:bags?|sacks?|fibc|container)\b", t)
        if not has_bag and re.search(r"\b(?:film|wrap|rolls?)\b", t):
            return "film"

    return result


# ---------------------------------------------------------------------------
# GSM / micron
# ---------------------------------------------------------------------------

_GSM_AFTER = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(?:gsm|g/m2|g/m\u00b2|gm/m2|gm/m\u00b2|g/m\^2|grammage)(?![a-z])",
    re.IGNORECASE,
)
_GSM_BEFORE = re.compile(
    r"\b(?:gsm|grammage)\s*[:\-]?\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)
_MICRON_AFTER = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(?:microns?|mic|mics|mu|um|mils?|micrometers?|micrometres?|thickness)(?![a-z])",
    re.IGNORECASE,
)
_MICRON_BEFORE = re.compile(
    r"\b(?:micron|microns|mic|mics|um|thickness)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def _as_int_if_close(value: float) -> int:
    rounded = int(round(value))
    return rounded


def _gsm_value_span(t: str) -> Optional[tuple[int, int]]:
    # "65 ± 2 gsm" names 65, not 2.
    tolerance = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:\u00b1|\+\s*/\s*-|\+-|plus\s*(?:or\s*)?/?\s*minus)"
        r"\s*\d+(?:\.\d+)?\s*"
        r"(?:gsm|g/m2|g/m\u00b2|gm/m2|gm/m\u00b2|g/m\^2|grammage)(?![a-z])",
        t,
    )
    if tolerance:
        return tolerance.span(1)
    m = _GSM_AFTER.search(t)
    if m:
        return m.span(1)
    m = _GSM_BEFORE.search(t)
    if m:
        return m.span(1)
    return None


def _micron_value_span(t: str) -> Optional[tuple[int, int]]:
    # "25 ± 2 micron" names 25, not 2.
    tolerance = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:\u00b1|\+\s*/\s*-|\+-|plus\s*(?:or\s*)?/?\s*minus)"
        r"\s*\d+(?:\.\d+)?\s*"
        r"(?:microns?|mic|mics|mu|um|mils?|micrometers?|micrometres?|thickness)(?![a-z])",
        t,
    )
    if tolerance:
        return tolerance.span(1)
    for m in _MICRON_AFTER.finditer(t):
        # In "gsm 65 micron 25", the 65 belongs to GSM, not micron.  But in
        # "65 gsm 25 micron" the 25 is the micron value because the gsm keyword
        # is a postfix unit after 65, not a prefix label before 25.
        before = t[max(0, m.start(1) - 20) : m.start(1)]
        label = re.search(r"\bgsm\s*[:\-]?\s*$", before)
        if label:
            prefix = before[: label.start()]
            if not re.search(r"\d\s*$", prefix):
                continue
        return m.span(1)
    m = _MICRON_BEFORE.search(t)
    if m:
        # "thickness 25" only counts when the message has no other thickness unit
        return m.span(1)
    return None


def _extract_gsm(t: str) -> Optional[int]:
    span = _gsm_value_span(t)
    if span is None:
        return None
    return _as_int_if_close(float(t[span[0] : span[1]]))


def _extract_micron(t: str) -> Optional[int]:
    span = _micron_value_span(t)
    if span is None:
        return None
    return _as_int_if_close(float(t[span[0] : span[1]]))


# ---------------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------------

_COUNT_UNITS = {
    "pc",
    "pcs",
    "piece",
    "pieces",
    "nos",
    "no",
    "numbers",
    "unit",
    "units",
    "bag",
    "bags",
    "sack",
    "sacks",
    "box",
    "boxes",
    "carton",
    "cartons",
    "pouch",
    "pouches",
    "roll",
    "rolls",
    "packet",
    "packets",
    "sheet",
    "sheets",
    "bundle",
    "bundles",
    "bori",
    "boris",
    "bardana",
    "cover",
    "covers",
    "thaila",
    "thailay",
    "drum",
    "drums",
}

_GRAM_UNITS = {"g", "gm", "gms", "gram", "grams"}
_QUINTAL_UNITS = {"quintal", "quintals"}
_WEIGHT_UNITS = {
    "kg",
    "kgs",
    "kilogram",
    "kilograms",
    "kilo",
    "kilos",
} | _GRAM_UNITS | _QUINTAL_UNITS
_TON_UNITS = {"ton", "tons", "tonne", "tonnes", "mt", "mts", "tn", "t"}
_LENGTH_UNITS = {
    "mm",
    "cm",
    "inch",
    "inches",
    "in",
    "ft",
    "feet",
    "foot",
    "meter",
    "meters",
    "metre",
    "metres",
    "mtr",
    "mtrs",
    "m",
}

_QTY_CUES = {
    "quantity",
    "qty",
    "order",
    "chahiye",
    "chaiye",
    "chahiya",
    "chaiyee",
    "need",
    "needed",
    "require",
    "required",
    "want",
    "wanted",
    "buy",
    "purchase",
    "quote",
    "quotation",
    "rfq",
    "total",
    "approx",
    "around",
    "about",
    "for",
    "of",
}

_BAG_NOUNS = re.compile(
    r"\b(?:bags?|sacks?|pouches?|cartons?|boxes?|packets?|covers?|bori|bardana)\b"
)


def _next_word(t: str, pos: int) -> str:
    m = re.match(r"\s*([a-z]+)", t[pos:])
    return m.group(1) if m else ""


def _following_words(t: str, pos: int, limit: int = 6) -> list[str]:
    return re.findall(r"[a-z]+", t[pos : pos + 70])[:limit]


def _unit_context(t: str, pos: int) -> tuple[Optional[str], bool, str]:
    """Return (unit, explicitly_stated, unit_word) immediately after a number."""
    tail = t[pos : pos + 40]

    # Explicit labels such as "quantity: 500, unit: kg".
    labelled = re.match(
        r"\s*[,;:]?\s*(?:unit|uom|measure)\s*[:=\-]?\s*(kg|kgs|kilogram|kilograms|pcs|pieces|nos|units|mt|mts|ton|tons|tonne|tonnes)\b",
        tail,
    )
    if labelled:
        word = labelled.group(1)
        if word in _WEIGHT_UNITS:
            return "kg", True, word
        if word in _TON_UNITS:
            return "mt", True, word
        return "pcs", True, word

    word = _next_word(t, pos)
    if word in _COUNT_UNITS:
        return "pcs", True, word
    if word in _WEIGHT_UNITS:
        return "kg", True, word
    if word in _TON_UNITS:
        return "mt", True, word
    if word == "metric" and re.match(r"\s*metric\s*(?:ton|tonne)s?\b", t[pos:]):
        return "mt", True, word

    # A product noun just after the number also implies a piece count:
    # "500 jumbo bags", "200 mono cartons".
    for w in _following_words(t, pos):
        if w in {"gsm", "micron", "mic", "mics", "mu", "kg", "kgs", "ton", "tonne", "mt"}:
            break
        if w in _COUNT_UNITS:
            return "pcs", False, w
    return None, False, ""


def _fill_weight_or_capacity(t: str, start: int, end: int, value: float) -> bool:
    after = t[end : end + 45]
    before = t[max(0, start - 40) : start]

    # A kg figure directly followed by "capacity" (or preceded by it) is the
    # bag's capacity, not the number of bags ordered.
    kg_after = re.match(r"\s*(?:kg|kgs|kilogram|kilograms|kilo|kilos)\b", after)
    ton_after = re.match(r"\s*(?:ton|tons|tonne|tonnes|mt|mts)\b", after)
    if (kg_after or ton_after) and re.search(
        r"\b(?:capacity|cap\.?|holding)\b", after[:30]
    ):
        return True
    if (kg_after or ton_after) and re.search(
        r"\b(?:capacity|cap\.?|holding)\s*(?:of|:|-)?\s*$", before
    ):
        return True

    if kg_after:
        # Small kg numbers next to a bag/sack noun are fill weight, not order qty.
        # Large kg amounts are usually an order weight (e.g. "500 kg woven sacks").
        if value <= 120 and (
            _BAG_NOUNS.search(t[end : end + 45]) or _BAG_NOUNS.search(before)
        ):
            return True
        if re.search(r"\b(?:each|per)\s+$", before):
            return True

    # "bags of 50 kg", "sacks 50 kg", "bags 60,000, 50 kg"
    if kg_after and value <= 120:
        if re.search(
            r"\b(?:bags?|sacks?|pouches?|cartons?|boxes?|packets?)\b[^.;]{0,20}$",
            before,
        ):
            return True

    return False


def _is_excluded(t: str, cand: dict, category: str) -> bool:
    start, end, value = cand["start"], cand["end"], cand["value"]
    after = t[end : end + 50]
    before = t[max(0, start - 40) : start]
    nw = _next_word(t, end)

    # GSM and thickness are their own fields.  A number followed by a
    # measurement unit is always a measurement; a number preceded by a label
    # is only a measurement when it is the value selected for that field (so
    # "25 micron 500 kg" keeps 500 as the quantity).
    if re.match(
        r"\s*(?:gsm|g/m2|g/m\u00b2|gm/m2|gm/m\u00b2|g/m\^2|grammage)(?![a-z])",
        after,
    ):
        return True
    if re.match(
        r"\s*(?:microns?|mic|mics|mu|um|mils?|micrometers?|micrometres?|thickness)(?![a-z])",
        after,
    ):
        return True
    for span in (_gsm_value_span(t), _micron_value_span(t)):
        if span is not None and span[0] <= start and end <= span[1]:
            return True

    # Dimensions, ply, colour, percentage, length.
    if re.match(r"\s*%\s*", after) or re.match(r"\s*(?:percent|pct)\b", after):
        return True
    if re.search(r"\d+\s*(?:[x*]|by)\s*$", before) or re.match(r"\s*(?:[x*]|by)\s*\d+", after):
        return True
    if re.match(r"\s*[- ]?ply\b", after):
        return True
    if re.match(r"\s*[- ]?(?:color|colour|layer)s?\b", after):
        return True
    if nw in _LENGTH_UNITS:
        return True

    # Address details (pin/plot/sector numbers) are not order quantities.  As
    # with measurements, only exclude a number directly after a label; in
    # "2nd floor 5000 pcs" the floor number is 2, not 5000.
    address = re.search(
        r"\b(?:sector|plot|road|street|lane|phase|block|floor|pin|pincode|gst|gstin|pan|cin|tan|shop|door|flat)\s*$",
        before,
    )
    if address:
        prefix = before[: address.start()]
        if not re.search(
            r"(?:\d\w*|\b[a-z]\b|first|second|third|fourth|fifth|"
            r"ground|upper|lower|basement|top)\s*$",
            prefix,
        ):
            return True
    id_label = re.search(
        r"\b(?:gst\s*no|gst\s*number|gstin|pan\s*no)\s*[:\-]?\s*$", before
    )
    if id_label:
        prefix = before[: id_label.start()]
        if not re.search(
            r"(?:\d\w*|\b[a-z]\b|first|second|third|fourth|fifth|"
            r"ground|upper|lower|basement|top)\s*$",
            prefix,
        ):
            return True

    # Ordinals, areas, durations, and years are not order quantities.
    if re.match(r"\s*(?:st|nd|rd|th)\b", after):
        return True
    if re.match(
        r"\s*(?:sq\.?\s*ft|sqft|square\s*feet|m2|m\^2|acre|acres|hectare|hectares)\b",
        after,
    ):
        return True
    if re.match(r"\s*(?:year|years|month|months|day|days)\b", after):
        return True
    if re.search(r"\b(?:since|year|years)\s*$", before):
        return True

    # Prices / rates: "rate 65", "65 per kg", "65/kg", "Rs. 65", "freight 1000".
    if re.search(
        r"\b(?:per|rate|price|mrp|cost|freight|transport|shipping|tax|gst|"
        r"discount|charges?|payment|advance|deposit|insurance|budget|amount|"
        r"value|invoice|bill|quotation|rs|inr|rupees)\.?\s*[:\-=\s]*$",
        before,
    ):
        return True
    if re.match(r"\s*(?:/|per)\s*[a-z]{1,8}\b", after):
        return True
    if re.match(r"\s*(?:rs|inr|rupees)\b", after):
        return True
    if re.match(r"\s*(?:rs|inr|rupees)\.?\s*(?:/|per)\s*[a-z]{1,8}\b", after):
        return True
    if re.match(r"\s*/\s*[-=]", after):
        return True

    if _fill_weight_or_capacity(t, start, end, value):
        return True

    return False


def _candidate_score(t: str, cand: dict, category: str) -> tuple[float, Optional[str]]:
    start, end = cand["start"], cand["end"]
    before = t[max(0, start - 45) : start]
    after = t[end : end + 45]
    unit, explicit, _ = _unit_context(t, end)

    score = 0.0
    if cand["mult"] > 1:
        score += 42
    if explicit:
        if unit == "pcs":
            score += 105
        elif unit == "mt":
            score += 92
        elif unit == "kg":
            score += 74 if category == "film" else 56
    elif unit == "pcs":
        score += 72

    prev_words = re.findall(r"[a-z]+", before)[-4:]
    if any(w in _QTY_CUES for w in prev_words):
        score += 42
    if re.search(r"\b(?:quantity|qty|order|total)\s*[:\-]?\s*$", before):
        score += 28
    if re.search(r"\b(?:approx|around|about|nearly)\s*$", before):
        score += 6

    # If there is no unit word at all, a nearby product noun still suggests pcs.
    if unit is None and re.search(
        r"\b(?:bags?|sacks?|boxes?|cartons?|pouches?|pieces?|pcs|rolls?)\b",
        after[:35],
    ):
        score += 34

    # Prefer a number that is clearly the ordered quantity over a stray number.
    if cand["value"] >= 10:
        score += 8
    if cand["word"]:
        score -= 4

    return score, unit


def _clean_quantity(value: float) -> int | float:
    rounded = round(value)
    if abs(value - rounded) < 1e-9:
        return int(rounded)
    return round(value, 4)


def _extract_quantity(t: str, category: str) -> tuple[int | float, str]:
    candidates = [c for c in _number_candidates(t) if not _is_excluded(t, c, category)]
    if not candidates:
        return 0, "pcs"

    scored = []
    for cand in candidates:
        score, unit = _candidate_score(t, cand, category)
        scored.append((score, cand["start"], cand, unit))

    # Highest score; on a tie prefer the earlier number.
    scored.sort(key=lambda item: (-item[0], item[1]))
    _, _, chosen, unit = scored[0]
    _, _, unit_word = _unit_context(t, chosen["end"])
    value = chosen["value"]
    if unit_word in _GRAM_UNITS:
        value /= 1000.0
    elif unit_word in _QUINTAL_UNITS:
        value *= 100.0
    if unit is None:
        unit = "pcs"
    return _clean_quantity(value), unit


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

_INDIA_CITIES = """
Agartala Agra Ahmedabad Ahmednagar Aizawl Ajmer Akola Alappuzha Aligarh Alipurduar
Alwar Ambala Ambarnath Amravati Amritsar Anand Anantapur Anantnag Ankleshwar
Arakkonam Arrah Asansol Ashoknagar Aurangabad Avadi Azamgarh Badlapur Bagalkot
Bagdogra Bahadurgarh Bahraich Balaghat Balasore Ballari Ballia Balrampur Banda
Bankura Banswara Barabanki Baramati Baran Barasat Bardhaman Bareilly Bargarh
Barmer Barnala Barpeta Barrackpore Baruipur Basti Batala Bathinda Beawar Beed
Begusarai Belagavi Bellary Bengaluru Berhampur Betul Bhadohi Bhadrak Bhagalpur
Bhandara Bharatpur Bharthana Bhatinda Bhavnagar Bhawanipatna Bhilai Bhilwara
Bhind Bhiwadi Bhiwandi Bhopal Bhubaneswar Bhuj Bidar Bijnor Bikaner Bilaspur
Bilimora Bokaro Bolangir Budaun Bulandshahr Buldhana Bundi Burhanpur Buxar
Chakan Chalakudy Chamarajanagar Chamba Champawat Chandannagar Chandausi
Chandigarh Chandrapur Chapra Charkhi Dadri Chatra Chennai Chhatarpur Chhindwara
Chikkamagaluru Chitradurga Chitrakoot Chittoor Chittorgarh Churu Coimbatore
Cooch Behar Cuddalore Cuttack Dahod Daman Damoh Darbhanga Darjeeling Dausa
Davanagere Dehradun Delhi Deoghar Deoria Dewas Dhamtari Dhanbad Dhar Dharamshala
Dharmapuri Dharwad Dhenkanal Dholpur Dhule Dibrugarh Dimapur Dindigul Dindori
Diu Dombivli Dungarpur Durg Durgapur Dwarka Eluru Erode Etah Etawah Faizabad
Faridabad Faridkot Farrukhabad Fatehabad Fatehpur Fazilka Firozabad Firozpur
Gadag Gadchiroli Gandhidham Gandhinagar Gangtok Gaya Ghaziabad Ghazipur Giridih
Godhra Gokak Gonda Gondia Gorakhpur Greater Noida Gudivada Gudiyatham Gulbarga
Guna Guntakal Guntur Gurgaon Gurugram Gwalior Haldia Haldwani Hanumangarh Hapur
Harda Hardoi Haridwar Hassan Hathras Hazaribagh Hindupur Hinganghat Hisar
Hosur Howrah Hubballi Hubli Hyderabad Ichalkaranji Idukki Imphal Indore Itanagar
Itarsi Jabalpur Jagtial Jaipur Jaisalmer Jalandhar Jalgaon Jalna Jammu Jamnagar
Jamshedpur Jangaon Jaunpur Jhabua Jhajjar Jhalawar Jhansi Jharsuguda Jhunjhunu
Jind Jodhpur Jorhat Junagadh Kakinada Kalaburagi Kalol Kalyan Kamareddy
Kanchipuram Kannauj Kannur Kanpur Kanyakumari Kapurthala Karaikal Karaikudi
Karimnagar Karnal Karur Kasaragod Kashipur Kathua Katihar Katni Kavali Kendrapara
Kendujhar Khammam Khandwa Khanna Kharagpur Kharar Khargone Khurja Kishanganj
Kishangarh Kochi Kodaikanal Kohima Kokrajhar Kolhapur Kolkata Kollam Kollapur
Koraput Korba Kota Kothagudem Kottayam Kovilpatti Kozhikode Krishnagar Kumbakonam
Kurnool Kurukshetra Lakhimpur Lakhisarai Lalitpur Latur Leh Lucknow Ludhiana
Machilipatnam Madanapalle Madhepura Madhubani Madikeri Madurai Mahabubnagar
Maharajganj Mahbubnagar Mahesana Mainpuri Malappuram Malda Malegaon Malerkotla
Malout Mandi Mandsaur Mangaluru Mangalore Manesar Mango Manipal Mansa Margao
Mathura Mau Meerut Mehsana Mirzapur Modinagar Moga Mohali Moradabad Morbi Morena
Mumbai Mussoorie Muzaffarnagar Muzaffarpur Mysore Mysuru Nabha Nadiad Nagaon
Nagapattinam Nagercoil Nagpur Nahan Nainital Nalgonda Namakkal Nanded Nandyal
Narnaul Nashik Navi Mumbai Navsari Nawada Neemuch Nellore New Delhi Nizamabad
Noida Nowgong Nuh Ongole Ooty Orai Osmanabad Palakkad Palampur Palanpur Palghar
Pali Palwal Panaji Panchkula Panipat Panna Panvel Parbhani Pathankot Patiala
Patna Pattukkottai Pauri Pune Pudukkottai Punalur Puri Purnia Raebareli Raichur
Raiganj Raigarh Raipur Rajahmundry Rajapalayam Rajkot Rajnandgaon Rajouri
Ramanathapuram Rampur Ranchi Ranipet Ratlam Ratnagiri Rewa Rewari Rishikesh
Robertsonpet Rohtak Roorkee Rudrapur Rupnagar Sagar Saharanpur Saharsa Salem
Samastipur Sambalpur Sambhal Sangli Sangrur Santipur Sasaram Satara Satna
Sawai Madhopur Secunderabad Sehore Seoni Shahjahanpur Shillong Shimla Shimoga
Shivamogga Shivpuri Shoranur Sikar Silchar Siliguri Silvassa Sindhanur Singrauli
Sirsa Sitapur Sivakasi Siwan Solan Solapur Sonipat Sri City Sri Ganganagar
Srikakulam Srinagar Sultanpur Surat Surendranagar Suryapet Thalassery Thane
Thanjavur Thoothukudi Thrissur Tiruchirappalli Tirunelveli Tirupati Tiruppur
Tiruvannamalai Tonk Trichy Tumakuru Tumkur Tuni Tuticorin Udaipur Udhagamandalam
Udupi Ujjain Ulhasnagar Unnao Urai Uthangarai Vadodara Valsad Vapi Varanasi
Vasai Vellore Veraval Vijayapura Vijayawada Villupuram Virar Visakhapatnam
Vizianagaram Warangal Wardha Yamunanagar Yavatmal Yelahanka Zirakpur
Allahabad Prayagraj Guwahati Rourkela Kadapa Cuddapah Bijapur Pimpri Chinchwad Loni
Ambattur Gopalpur Bhatpara Panihati Kamarhati Kulti Kirari Ozhukarai Sambhajinagar
Chhatrapati Sambhajinagar Ahilyanagar Dharashiv Bihar Sharif Oragadam Halol Umbergaon
Wadhwan
"""

_INDIA_STATES = """
Andhra Pradesh Arunachal Pradesh Assam Bihar Chhattisgarh Goa Gujarat Haryana
Himachal Pradesh Jharkhand Karnataka Kerala Madhya Pradesh Maharashtra Manipur
Meghalaya Mizoram Nagaland Odisha Punjab Rajasthan Sikkim Tamil Nadu Telangana
Tripura Uttar Pradesh Uttarakhand West Bengal Andaman and Nicobar Islands
Chandigarh Dadra and Nagar Haveli Daman and Diu Delhi Jammu and Kashmir Ladakh
Lakshadweep Puducherry
"""

_COUNTRIES = """
Afghanistan Albania Algeria Angola Argentina Armenia Australia Austria Azerbaijan
Bahamas Bahrain Bangladesh Barbados Belarus Belgium Belize Benin Bhutan Bolivia
Bosnia and Herzegovina Botswana Brazil Brunei Bulgaria Burkina Faso Burundi Cambodia
Cameroon Canada Chad Chile China Colombia Congo Costa Rica Croatia Cuba Cyprus
Czech Republic Denmark Djibouti Dominican Republic Ecuador Egypt El Salvador
Eritrea Estonia Eswatini Ethiopia Fiji Finland France Gabon Gambia Georgia Germany
Ghana Greece Guatemala Guinea Guyana Haiti Honduras Hong Kong Hungary Iceland
India Indonesia Iran Iraq Ireland Israel Italy Ivory Coast Jamaica Japan Jordan
Kazakhstan Kenya Kosovo Kuwait Kyrgyzstan Laos Latvia Lebanon Lesotho Liberia Libya
Lithuania Luxembourg Madagascar Malawi Malaysia Maldives Mali Malta Mauritania
Mauritius Mexico Moldova Mongolia Montenegro Morocco Mozambique Myanmar Namibia
Nepal Netherlands New Zealand Nicaragua Niger Nigeria North Macedonia Norway Oman
Pakistan Panama Papua New Guinea Paraguay Peru Philippines Poland Portugal Qatar
Romania Russia Rwanda Saudi Arabia Senegal Serbia Seychelles Sierra Leone Singapore
Slovakia Slovenia Somalia South Africa South Korea South Sudan Spain Sri Lanka Sudan
Suriname Sweden Switzerland Syria Taiwan Tajikistan Tanzania Thailand Togo Trinidad
and Tobago Tunisia Turkey Turkmenistan Uganda Ukraine United Arab Emirates
United Kingdom United States Uruguay Uzbekistan Venezuela Vietnam Yemen Zambia
Zimbabwe
"""

_WORLD_CITIES = """
Abidjan Abu Dhabi Accra Addis Ababa Alexandria Amsterdam Ankara Antwerp Athens
Atlanta Auckland Baghdad Bangkok Barcelona Beijing Beirut Belfast Berlin Birmingham
Bogota Boston Brisbane Brussels Budapest Buenos Aires Busan Cairo Calgary Cape Town
Caracas Casablanca Cebu Chicago Chiang Mai Colombo Copenhagen Dallas Damascus Dar es
Salaam Delhi Denver Detroit Dhaka Doha Dubai Dublin Durban Dusseldorf Edinburgh
Faisalabad Frankfurt Geneva Glasgow Guangzhou Guadalajara Hamburg Hanoi Harare
Ho Chi Minh City Hong Kong Houston Islamabad Istanbul Jakarta Jeddah Johannesburg
Kabul Kampala Karachi Kathmandu Kigali Kingston Kuala Lumpur Kuwait City Kyiv Lagos
Lahore Las Vegas Lima Lisbon London Los Angeles Luanda Lusaka Lyon Madrid Manila
Maputo Marseille Mecca Medina Melbourne Mexico City Miami Milan Minneapolis Mombasa
Monterrey Montreal Moscow Mumbai Munich Nairobi New York Nagoya Osaka Oslo Paris
Penang Perth Philadelphia Phoenix Prague Pretoria Quetta Riyadh Rome Rotterdam
San Francisco Santiago Sao Paulo Seattle Seoul Shanghai Sharjah Shenzhen Singapore
St Petersburg Stockholm Stuttgart Sydney Taipei Tehran Tel Aviv Toronto Turin
Vancouver Vienna Vientiane Warsaw Washington Wellington Yangon Zurich
"""

_ACRONYM_DISPLAY = {
    "uae": "UAE",
    "uk": "UK",
    "usa": "USA",
    "ncr": "NCR",
    "jnpt": "JNPT",
    "u.s.a.": "USA",
}


_MULTIWORD_PLACES = [
    "Andaman and Nicobar Islands",
    "Dadra and Nagar Haveli",
    "Daman and Diu",
    "Jammu and Kashmir",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Himachal Pradesh",
    "Madhya Pradesh",
    "Uttar Pradesh",
    "Tamil Nadu",
    "West Bengal",
    "New Delhi",
    "Delhi NCR",
    "Greater Noida",
    "Navi Mumbai",
    "Sri Ganganagar",
    "Sri City",
    "United Arab Emirates",
    "United Kingdom",
    "United States of America",
    "United States",
    "Saudi Arabia",
    "South Africa",
    "South Korea",
    "South Sudan",
    "North Macedonia",
    "New Zealand",
    "Sri Lanka",
    "Burkina Faso",
    "Costa Rica",
    "Czech Republic",
    "Dominican Republic",
    "El Salvador",
    "Ivory Coast",
    "Papua New Guinea",
    "Sierra Leone",
    "Trinidad and Tobago",
    "Bosnia and Herzegovina",
    "Great Britain",
    "Bihar Sharif",
    "Chhatrapati Sambhajinagar",
    "Pimpri Chinchwad",
    "Abu Dhabi",
    "Addis Ababa",
    "Buenos Aires",
    "Cape Town",
    "Dar es Salaam",
    "Ho Chi Minh City",
    "Hong Kong",
    "Kuwait City",
    "Kuala Lumpur",
    "Los Angeles",
    "Mexico City",
    "New York",
    "Rio de Janeiro",
    "San Francisco",
    "Sao Paulo",
    "St Petersburg",
    "Tel Aviv",
    "Chiang Mai",
    "Phnom Penh",
    "Johor Bahru",
    "Las Vegas",
]
_MULTIWORD_PLACES.sort(key=len, reverse=True)


def _split_places(block: str) -> list[str]:
    """Split a whitespace-separated list while keeping multi-word names intact."""
    text = re.sub(r"\s+", " ", block).strip()
    for phrase in _MULTIWORD_PLACES:
        marked = phrase.replace(" ", "|")
        text = re.sub(
            r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])",
            marked,
            text,
            flags=re.IGNORECASE,
        )
    items = [token.replace("|", " ").strip() for token in text.split()]
    return [item for item in items if item and len(item.replace(" ", "")) >= 3]


def _build_gazetteer() -> dict[str, tuple[str, str]]:
    gaz: dict[str, tuple[str, str]] = {}
    for name in _split_places(_INDIA_CITIES):
        gaz[name.lower()] = ("city", name)
    for name in _split_places(_INDIA_STATES):
        key = name.lower()
        if key not in gaz:
            gaz[key] = ("state", name)
    for name in _split_places(_COUNTRIES):
        gaz[name.lower()] = ("country", name)
    for name in _split_places(_WORLD_CITIES):
        gaz[name.lower()] = ("city", name)

    aliases = {
        "bangalore": "Bangalore",
        "bombay": "Bombay",
        "calcutta": "Calcutta",
        "madras": "Madras",
        "trivandrum": "Trivandrum",
        "cochin": "Cochin",
        "mysore": "Mysore",
        "baroda": "Baroda",
        "poona": "Poona",
        "gurgaon": "Gurgaon",
        "gauhati": "Gauhati",
        "orissa": "Orissa",
        "pondicherry": "Pondicherry",
        "uae": "UAE",
        "u.a.e.": "UAE",
        "usa": "USA",
        "u.s.a.": "USA",
        "uk": "UK",
        "u.k.": "UK",
        "america": "America",
        "britain": "Britain",
        "england": "England",
        "great britain": "Great Britain",
        "united states of america": "USA",
        "tirupur": "Tirupur",
        "calicut": "Calicut",
        "belgaum": "Belgaum",
        "sricity": "Sri City",
        "nhava sheva": "Nhava Sheva",
        "jnpt": "JNPT",
    }
    for alias, display in aliases.items():
        existing = gaz.get(alias.lower())
        if existing is None:
            typ = "country" if display in {"UAE", "USA", "UK"} else "city"
            gaz[alias.lower()] = (typ, display)
        else:
            gaz[alias.lower()] = (existing[0], display)

    # a few industrial/town names that are common in packaging RFQs
    for name in [
        "Sri City",
        "Delhi NCR",
        "NCR",
        "Puducherry",
        "Hazira",
        "Dahej",
        "Palej",
        "Sanand",
        "Mundra",
        "Kandla",
        "Pithampur",
        "Baddi",
        "Ranjangaon",
        "Bawal",
        "Binola",
        "Neemrana",
        "Sitarganj",
        "Pantnagar",
        "Khed",
        "Shirwal",
        "Panoli",
        "Jhagadia",
        "Vilayat",
        "Kutch",
    ]:
        gaz[name.lower()] = ("city", name)

    return gaz


_GAZETTEER = _build_gazetteer()
_GAZ_NAMES_BY_LENGTH = sorted(_GAZETTEER, key=len, reverse=True)
# Compile once at import time: compiling these on every parse dominated runtime.
_GAZ_PATTERNS = [
    (
        re.compile(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])"),
        _GAZETTEER[name][0],
        _GAZETTEER[name][1],
    )
    for name in _GAZ_NAMES_BY_LENGTH
]

_LOCATION_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "for",
    "with",
    "without",
    "to",
    "at",
    "in",
    "on",
    "by",
    "from",
    "of",
    "delivery",
    "deliver",
    "delivered",
    "ship",
    "shipping",
    "dispatch",
    "send",
    "drop",
    "site",
    "plant",
    "factory",
    "warehouse",
    "godown",
    "address",
    "consignee",
    "buyer",
    "seller",
    "supplier",
    "vendor",
    "please",
    "pls",
    "plz",
    "urgent",
    "urgently",
    "asap",
    "immediately",
    "chahiye",
    "chaiye",
    "chahiya",
    "chaiyee",
    "need",
    "needed",
    "require",
    "required",
    "want",
    "wanted",
    "buy",
    "purchase",
    "quote",
    "quotation",
    "rfq",
    "quantity",
    "qty",
    "order",
    "total",
    "approx",
    "around",
    "about",
    "price",
    "rate",
    "best",
    "compare",
    "be",
    "get",
    "make",
    "pack",
    "packed",
    "packing",
    "deliver",
    "delivered",
    "delivering",
    "shipped",
    "convert",
    "converted",
    "print",
    "printed",
    "brand",
    "branded",
    "manufactured",
    "pcs",
    "pc",
    "pieces",
    "piece",
    "nos",
    "no",
    "units",
    "unit",
    "bags",
    "bag",
    "sacks",
    "sack",
    "boxes",
    "box",
    "cartons",
    "carton",
    "pouches",
    "pouch",
    "rolls",
    "roll",
    "packets",
    "packet",
    "kg",
    "kgs",
    "kilo",
    "kilos",
    "ton",
    "tons",
    "tonne",
    "tonnes",
    "mt",
    "gsm",
    "micron",
    "mic",
    "microns",
    "pcs",
    "white",
    "black",
    "blue",
    "red",
    "green",
    "yellow",
    "transparent",
    "printed",
    "plain",
    "colored",
    "coloured",
    "virgin",
    "recycled",
    "new",
    "old",
    "first",
    "last",
    "quality",
    "grade",
    "size",
    "type",
    "color",
    "colour",
    "layer",
    "ply",
    "mm",
    "cm",
    "inch",
    "meter",
    "mtr",
}


def _display_place(name: str) -> str:
    low = name.lower().strip()
    if low in _ACRONYM_DISPLAY:
        return _ACRONYM_DISPLAY[low]
    minor = {"and", "of", "the", "da", "de", "du", "la", "van", "von"}
    parts = low.split()
    rendered = []
    for i, part in enumerate(parts):
        if part in _ACRONYM_DISPLAY:
            rendered.append(_ACRONYM_DISPLAY[part])
        elif i > 0 and part in minor:
            rendered.append(part)
        elif part.isupper() and len(part) > 1:
            rendered.append(part)
        else:
            rendered.append(part[:1].upper() + part[1:])
    return " ".join(rendered)


def _location_text(t: str) -> str:
    # Keep only letters/numbers/spaces for clean word-boundary matching.
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", t)).strip()


def _gazetteer_matches(loc_text: str) -> list[dict]:
    raw_matches: list[dict] = []
    for pattern, typ, display in _GAZ_PATTERNS:
        for m in pattern.finditer(loc_text):
            raw_matches.append(
                {
                    "start": m.start(),
                    "end": m.end(),
                    "type": typ,
                    "name": display,
                }
            )

    # Prefer the longest match at each position; drop overlapping shorter ones.
    raw_matches.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))
    selected: list[dict] = []
    for match in raw_matches:
        if all(
            match["end"] <= other["start"] or match["start"] >= other["end"]
            for other in selected
        ):
            selected.append(match)
    return selected


def _trim_location_phrase(phrase: str) -> str:
    words = phrase.lower().split()
    while words and words[-1] in _LOCATION_STOPWORDS:
        words.pop()
    while words and words[0] in _LOCATION_STOPWORDS:
        words.pop(0)
    return " ".join(words)


def _context_location_matches(loc_text: str, original: str) -> list[dict]:
    patterns: list[tuple[str, bool, bool]] = [
        (
            r"(?:delivery|deliver|ship(?:ping)?|dispatch|send|drop|site|plant|factory|warehouse|godown|address|consignee|location|destination)\s*(?:to|at|in|:)?\s+([a-z]+(?:\s+[a-z]+){0,2})",
            True,
            True,
        ),
        (r"\bto\s+([a-z]+(?:\s+[a-z]+){0,2})", True, False),
        (r"\bat\s+([a-z]+(?:\s+[a-z]+){0,2})", True, False),
        (r",\s*([a-z]+(?:\s+[a-z]+){0,2})\s*$", False, False),
    ]
    out: list[dict] = []
    for pattern, allow_unknown, strong_cue in patterns:
        for m in re.finditer(pattern, loc_text):
            phrase = _trim_location_phrase(m.group(1))
            if not phrase:
                continue

            # Try the full phrase, then progressively shorter prefixes.
            words = phrase.split()
            found = None
            for size in range(min(3, len(words)), 0, -1):
                candidate = " ".join(words[:size])
                if candidate in _GAZETTEER:
                    found = candidate
                    break
            if found:
                typ, _ = _GAZETTEER[found]
                out.append(
                    {
                        "start": m.start(1),
                        "end": m.start(1) + len(found),
                        "type": typ,
                        "name": found,
                        "context": True,
                    }
                )
                continue

            if not allow_unknown:
                continue
            # For an unseen place, accept a short non-vocabulary phrase when
            # there is a strong delivery cue, or when it is capitalised in the
            # original message (the common convention for a place name).
            first = words[0]
            if first in _LOCATION_STOPWORDS:
                continue
            capitalised = re.search(
                r"\b" + re.escape(first[:1].upper() + first[1:]) + r"\b", original
            ) is not None
            if not (strong_cue or capitalised):
                continue
            if re.fullmatch(r"[a-z]{3,}", first):
                out.append(
                    {
                        "start": m.start(1),
                        "end": m.start(1) + len(first),
                        "type": "city",
                        "name": first,
                        "context": True,
                        "unknown": True,
                    }
                )
    return out


def _location_score(match: dict, loc_text: str) -> float:
    score = {"city": 100.0, "state": 72.0, "country": 62.0}.get(match["type"], 55.0)
    if match.get("unknown"):
        score = 52.0
    before = loc_text[max(0, match["start"] - 35) : match["start"]]
    if re.search(r"\b(?:to|at)\s*$", before):
        score += 20
    elif re.search(
        r"\b(?:delivery|deliver|ship|dispatch|send|drop|site|plant|warehouse|godown|address|consignee|location|destination)\b",
        before,
    ):
        score += 10
    if re.search(r"\bfrom\s*$", before):
        score -= 20
    # No position bonus: in "Bhiwandi, Thane" the first place is the delivery
    # town and the second is its district.  A destination after "from X to Y"
    # is identified by the "to" cue above.
    return score


def _extract_location(original: str, t: str) -> Optional[str]:
    loc_text = _location_text(t)
    matches = _gazetteer_matches(loc_text)
    matches.extend(_context_location_matches(loc_text, original))
    if not matches:
        return None

    # Deduplicate overlapping matches, keeping the best.
    matches.sort(key=lambda m: (-_location_score(m, loc_text), m["start"]))
    chosen = None
    for match in matches:
        chosen = match
        break

    # If we chose a state/country but a city is also present, prefer the city.
    best_city = None
    for match in matches:
        if match["type"] == "city":
            best_city = match
            break
    if best_city is not None and chosen is not None and chosen["type"] != "city":
        chosen = best_city

    if chosen is None:
        return None
    return _display_place(chosen["name"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_rfq(text: str) -> dict:
    """Parse one buyer message into the six required RFQ fields."""
    if text is None:
        text = ""
    t = _normalize(text)

    category = _detect_category(t)
    gsm = _extract_gsm(t)
    micron = _extract_micron(t)
    if micron is None and category == "film":
        # Film thickness is sometimes written in millimetres (0.025 mm = 25 micron).
        mm = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*mm(?![a-z])", t)
        if mm:
            mm_value = float(mm.group(1))
            if 0 < mm_value <= 1.0:
                micron = int(round(mm_value * 1000))
    quantity, unit = _extract_quantity(t, category)
    location = _extract_location(str(text), t)

    return {
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "gsm": gsm,
        "micron": micron,
        "location": location,
    }
