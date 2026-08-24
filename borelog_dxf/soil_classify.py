"""
Maps a free-text soil/rock description to a drawing category (which in
turn controls hatch pattern + colour in the DXF).

Rules are checked in order; first match wins. Keep the more specific
rules (e.g. "hard rock") above the generic ones (e.g. "rock").
Add new rules here as new soil/rock terminology shows up in reports -
nothing else in the pipeline needs to change.
"""
from __future__ import annotations

ROCK_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("hard_rock",      ("hard rock",)),
    ("weathered_rock", ("disintegrated", "disinitigrated", "weathered", "fractured")),
    ("soft_rock",      ("soft rock",)),
    ("rock",           ("rock", "boulder", "murrum")),
]

# soil-type keywords, checked against the LAST significant word of the
# description (standard geotech naming puts the dominant material last,
# e.g. "Clayey Gravels" = gravel with clay fines -> gravel, not clay)
SOIL_KEYWORDS: dict[str, str] = {
    "clay": "clay", "clayey": "clay",
    "silt": "silt", "silty": "silt",
    "sand": "sand", "sandy": "sand",
    "gravel": "gravel", "gravels": "gravel", "gravelly": "gravel",
}

DEFAULT_CATEGORY = "overburden"

# category -> (hatch pattern name, pattern scale, ACI colour index, legend label)
HATCH_STYLE: dict[str, dict] = {
    "overburden":     dict(pattern="GRAVEL", scale=0.6, color=3, label="Overburden (Soil)"),
    "gravel":         dict(pattern="GRAVEL", scale=0.6, color=3, label="Gravel"),
    "sand":           dict(pattern="DOTS",   scale=0.4, color=2, label="Sand"),
    "silt":           dict(pattern="DOTS",   scale=0.2, color=8, label="Silt"),
    "clay":           dict(pattern="ANSI37", scale=0.5, color=5, label="Clay"),
    "weathered_rock": dict(pattern="ANSI31", scale=0.6, color=2, label="Soft / Disintegrated Rock"),
    "soft_rock":      dict(pattern="DOLMIT", scale=1.5, color=4, label="Soft Rock"),
    "rock":           dict(pattern="GRAVEL", scale=0.4, color=4, label="Rock"),
    "hard_rock":      dict(pattern="GRAVEL", scale=0.3, color=6, label="Hard Rock"),
}


def classify(description: str) -> str:
    """Return a category key for `description`. Falls back to
    DEFAULT_CATEGORY (drawn as plain overburden) if nothing matches, so
    an unrecognised soil name never crashes the pipeline - it just
    won't get a distinctive hatch until a rule is added."""
    d = (description or "").lower()

    # rock terms are checked as substrings anywhere - they're rarely
    # ambiguous ("disintegrated rock", "hard rock", etc.)
    for category, keywords in ROCK_RULES:
        if any(k in d for k in keywords):
            return category

    # soil terms: use the LAST matching word in the text, since geotech
    # naming convention puts the dominant material last (e.g. "Clayey
    # Gravels" -> gravel is dominant, clay is just a qualifier)
    words = [w.strip('.,;:') for w in d.split()]
    for w in reversed(words):
        if w in SOIL_KEYWORDS:
            return SOIL_KEYWORDS[w]

    return DEFAULT_CATEGORY


def style_for(description: str) -> dict:
    return HATCH_STYLE[classify(description)]


def classify_and_style(description: str) -> tuple[str, dict]:
    cat = classify(description)
    return cat, HATCH_STYLE[cat]
