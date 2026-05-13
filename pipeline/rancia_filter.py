"""Rule-based 'rancia' (anti-petroleum/anti-fracking noise) filter.

Marks mentions that match domain blacklist OR contain enough rancia keywords
without referring to an identifiable political actor. Mentions are flagged
(is_rancia=True, rancia_reason=...) but never deleted — the orchestrator
splits them into a separate CSV for transparency reporting.

Constants at the top of this file are the editable contract: ampliar la
lista NO requiere tocar la lógica.
"""

from __future__ import annotations

import re
from typing import Tuple

import pandas as pd

from agents.shared.logger import get_logger

logger = get_logger("vista")

# ──────────────────────────────────────────────────────────────────────
# Editable constants — ampliable sin tocar lógica
# ──────────────────────────────────────────────────────────────────────

# Authors / handles / domains that we treat as rancia by default.
# Match is substring-based on the lowercased author (and url, if present).
RANCIA_DOMAINS: tuple[str, ...] = (
    "laizquierdadiario",
    "prensaobrera",
    "opsur",
    "ejes-org",
    "ejes.org",
    "fracking-no",
    "frackingno",
    "noalfracking",
)

# Keywords that count toward the threshold.
# Order matters only for readability; matching is by substring with word boundaries
# where the keyword is a single word, otherwise plain substring.
RANCIA_KEYWORDS: tuple[str, ...] = (
    "fracking asesino",
    "petroleras genocidas",
    "petrolera genocida",
    "extractivismo asesino",
    "extractivismo genocida",
    "fracking genocida",
    "veneno",
    "vendepatrias",
    "extractivismo",
    "genocida",
    "ecocidio",
    "saqueo",
)

# Names of political/business/public actors. Presence of any of these in the
# mention text signals "this is a political/business critique with rancia
# vocabulary, not pure rancia" → keep for Haiku to classify on the axes.
POLITICAL_ACTOR_NAMES: tuple[str, ...] = (
    "milei",
    "macri",
    "massa",
    "galuccio",
    "galperin",
    "cossio",
    "bulgheroni",
    "perez companc",
    "pérez companc",
    "rocca",
    "cristina",
    "kirchner",
    "kicillof",
    "larreta",
    "patricia bullrich",
    "caputo",
    "sturzenegger",
    "vidal",
    "scioli",
    "alberto fernandez",
    "alberto fernández",
)

# Generic role labels that imply an identifiable political/business actor
# even without naming them.
POLITICAL_ROLE_KEYWORDS: tuple[str, ...] = (
    "presidente",
    "ministro",
    "ministra",
    "diputado",
    "diputada",
    "senador",
    "senadora",
    "gobernador",
    "gobernadora",
    "intendente",
    "secretario",
    "secretaria",
    "fundador",
    "fundadora",
    "founder",
    "ceo",
    "directivo",
    "empresario",
    "empresaria",
)

RANCIA_KEYWORD_THRESHOLD: int = 2


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

def _lower(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).lower()


def _matches_rancia_domain(author_or_url: str) -> bool:
    if not author_or_url:
        return False
    return any(d in author_or_url for d in RANCIA_DOMAINS)


def _count_rancia_keywords(text: str) -> int:
    if not text:
        return 0
    count = 0
    for kw in RANCIA_KEYWORDS:
        if " " in kw:
            # Multi-word — plain substring match
            if kw in text:
                count += 1
        else:
            # Single word — require word boundary so "extractivismo" doesn't
            # match inside "preextractivista" by accident.
            if re.search(rf"\b{re.escape(kw)}\b", text):
                count += 1
    return count


def _has_political_actor(text: str) -> bool:
    if not text:
        return False
    for name in POLITICAL_ACTOR_NAMES:
        if name in text:
            return True
    for role in POLITICAL_ROLE_KEYWORDS:
        if re.search(rf"\b{re.escape(role)}\b", text):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def is_rancia(mention: dict) -> Tuple[bool, str]:
    """Return (is_rancia, reason) for a single mention dict.

    Lookup keys (all optional, lenient with NaN/None):
        text, author, url

    Logic:
        1. Author or URL matches a rancia domain → rancia (always).
        2. >=2 rancia keywords AND no political actor in text → rancia.
        3. Otherwise → not rancia (reason="").

    The reason string is short and stable; consumers can group on it.
    """
    text = _lower(mention.get("text"))
    author = _lower(mention.get("author"))
    url = _lower(mention.get("url"))

    if _matches_rancia_domain(author) or _matches_rancia_domain(url):
        return True, "rancia_domain"

    kw_count = _count_rancia_keywords(text)
    if kw_count < RANCIA_KEYWORD_THRESHOLD:
        return False, ""

    if _has_political_actor(text):
        return False, f"keywords={kw_count}_but_has_political_actor"

    return True, f"rancia_keywords={kw_count}"


def apply_rancia_filter(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Annotate a DataFrame with rancia flags and split it.

    Adds two columns to the input frame (in-place on a copy):
        is_rancia      bool
        rancia_reason  str

    Returns a tuple (df_no_rancia, df_rancia). Both reference rows from the
    same enriched frame; modifying one does not modify the other.

    Required columns: text. Optional: author, url. Missing columns are
    treated as empty strings.
    """
    if df is None or df.empty:
        empty = df.copy() if df is not None else pd.DataFrame()
        return empty, empty.copy()

    df = df.copy()

    # Normalize required columns
    if "text" not in df.columns:
        raise ValueError("apply_rancia_filter: input DataFrame must have a 'text' column")

    flags: list[bool] = []
    reasons: list[str] = []

    has_author = "author" in df.columns
    has_url = "url" in df.columns

    for idx in df.index:
        mention = {
            "text": df.at[idx, "text"],
            "author": df.at[idx, "author"] if has_author else "",
            "url": df.at[idx, "url"] if has_url else "",
        }
        flag, reason = is_rancia(mention)
        flags.append(flag)
        reasons.append(reason)

    df["is_rancia"] = flags
    df["rancia_reason"] = reasons

    df_rancia = df[df["is_rancia"]].copy()
    df_no_rancia = df[~df["is_rancia"]].copy()

    logger.info(
        "Rancia filter: %d input → %d kept, %d rancia (%.1f%%)",
        len(df), len(df_no_rancia), len(df_rancia),
        len(df_rancia) / max(len(df), 1) * 100,
    )

    return df_no_rancia, df_rancia
