"""Actor sub-classification for unclassified mentions."""

import os
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from anthropic import Anthropic
from dotenv import load_dotenv

from agents.shared.logger import get_logger

load_dotenv()

logger = get_logger("report-builder")

HAIKU_MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 50
MAX_AI_SAMPLE = 1500

# ---------------------------------------------------------------------------
# Rule-based classification
# ---------------------------------------------------------------------------

MEDIA_KEYWORDS = [
    "noticias", "news", "prensa", "periodist", "reportero", "corresponsal",
    "editor", "medio", "diario", "periódico", "tv", "canal", "noticiero",
    "agencia", "reuters", "efe", "afp", "cnn", "bbc",
]

MEDIA_DOMAINS = [
    "msn", "cnn", "bbc", "reuters", "efe", "semana", "eltiempo",
    "elespectador", "caracol", "rcn", "infobae", "pulzo", "bluradio",
    "wradio", "portafolio", "larepublica", "dinero",
]

MEDIA_TEXT_PATTERNS = [
    r"\bsegún\b", r"\binformó\b", r"\breportó\b", r"\banunció\b",
    r"\bcomunicado\b", r"\bfuentes\b", r"\bconfirmó\b", r"\bdeclaró\b",
]

HUMOR_INDICATORS = [
    "😂", "🤣", "💀", "😭", "jajaj", "JAJAJ", "jajá", "lmao", "lol",
    "meme", "xd", "XD", "😆", "🤡", "bruh", "jsjsj",
]

AVIATION_KEYWORDS = [
    "pilot", "tripulant", "cabina", "copilot", "aviación", "aviation",
    "aeronáutic", "seguridad aérea", "FAA", "IATA", "controlador",
    "torre de control", "sobrecargo", "auxiliar de vuelo",
]

INFLUENCER_INDICATORS = [
    "influencer", "youtuber", "tiktoker", "streamer", "creador de contenido",
    "creator", "blogger", "vlogger",
]


def _rule_classify_actor(
    text: str,
    author: str,
    platform: str,
) -> Optional[str]:
    """Classify an unclassified mention by rules. Returns None if uncertain."""
    text_lower = (text or "").lower()
    author_lower = (author or "").lower()

    # Media detection
    if any(d in author_lower for d in MEDIA_DOMAINS):
        return "medios"
    if any(kw in author_lower for kw in MEDIA_KEYWORDS):
        return "medios"
    if sum(1 for p in MEDIA_TEXT_PATTERNS if re.search(p, text_lower)) >= 2:
        return "medios"

    # Humor/memes
    humor_count = sum(1 for h in HUMOR_INDICATORS if h in text or h in text_lower)
    if humor_count >= 2:
        return "humor_memes"

    # Aviation industry
    if any(kw in text_lower for kw in AVIATION_KEYWORDS):
        return "aviacion_industria"

    # Other influencers (if the author has high follower-like signals)
    if any(kw in text_lower for kw in INFLUENCER_INDICATORS):
        return "otros_influencers"

    # Default: opinion publica (regular user expressing opinion)
    # Only if the text has some opinion markers
    opinion_markers = [
        "creo que", "me parece", "opino", "pienso que", "según yo",
        "para mí", "en mi opinión", "yo creo", "la verdad",
        "!", "?", "bien hecho", "mal", "pésimo", "excelente",
        "apoyo", "rechazo", "vergüenza", "orgullo",
    ]
    if any(m in text_lower for m in opinion_markers):
        return "opinion_publica"

    # If text is short and has emojis or exclamation, likely opinion
    if len(text) < 200 and ("!" in text or "?" in text):
        return "opinion_publica"

    return None


def _ai_classify_actors_batch(
    texts: List[str],
    platforms: List[str],
    authors: List[str],
    client: Anthropic,
) -> List[Optional[str]]:
    """Use Haiku to classify a batch of mentions into actor sub-categories."""
    if not texts:
        return []

    items = []
    for i, (t, p, a) in enumerate(zip(texts, platforms, authors)):
        items.append(f'{i+1}. [{p}] @{a}: "{t[:200]}"')
    numbered = "\n".join(items)

    system = (
        "Classify each social media mention into ONE category:\n"
        "medios: news coverage, journalism, media reporting\n"
        "opinion_publica: regular person expressing opinion\n"
        "humor_memes: joke, meme, satire, parody\n"
        "aviacion_industria: aviation professional, safety expert\n"
        "otros_influencers: another public figure commenting\n"
        "otros: cannot determine\n\n"
        "Respond ONLY with a JSON array of category names.\n"
        'Example: ["opinion_publica", "medios", "humor_memes"]\n'
        "No other text."
    )

    try:
        message = client.messages.create(
            model=HAIKU_MODEL, max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": f"Classify:\n{numbered}"}],
        )
        response = message.content[0].text.strip()
        cleaned = re.sub(r'^```json\s*', '', response)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        results = json.loads(cleaned)

        valid = {"medios", "opinion_publica", "humor_memes", "aviacion_industria", "otros_influencers", "otros"}
        normalized = []
        for r in (results if isinstance(results, list) else []):
            val = str(r).strip().lower() if r else None
            normalized.append(val if val in valid else None)

        while len(normalized) < len(texts):
            normalized.append(None)
        return normalized[:len(texts)]

    except Exception as e:
        logger.error("AI actor classification batch failed: %s", e)
        return [None] * len(texts)


def classify_actors(
    df: pd.DataFrame,
    use_ai: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Reclassify 'otros'/'unknown' actors into sub-categories.

    Args:
        df: DataFrame with 'text', 'author', 'platform', 'actor' columns.
        use_ai: Whether to use Haiku for uncertain mentions.

    Returns:
        (updated DataFrame, classification stats dict)
    """
    if "actor" not in df.columns:
        return df, {"skipped": True}

    df = df.copy()

    # Ensure actor_subcategory column
    if "actor_subcategory" not in df.columns:
        df["actor_subcategory"] = ""

    # Find unclassified rows
    otros_mask = df["actor"].astype(str).str.lower().isin({"otros", "unknown", "<na>", "nan", "none", ""})
    original_otros = otros_mask.sum()
    logger.info("Actor classification: %d unclassified out of %d total", original_otros, len(df))

    if original_otros == 0:
        return df, {"original_otros": 0, "rules": 0, "ai": 0, "remaining_otros": 0}

    # Step 1: Rule-based
    rules_classified = 0
    for idx in df[otros_mask].index:
        text = str(df.at[idx, "text"]) if pd.notna(df.at[idx, "text"]) else ""
        author = str(df.at[idx, "author"]) if "author" in df.columns and pd.notna(df.at[idx, "author"]) else ""
        platform = str(df.at[idx, "platform"]) if "platform" in df.columns and pd.notna(df.at[idx, "platform"]) else ""

        result = _rule_classify_actor(text, author, platform)
        if result:
            df.at[idx, "actor_subcategory"] = result
            rules_classified += 1

    logger.info("Rule-based actor classification: %d classified", rules_classified)

    # Step 2: AI classification for remaining
    ai_classified = 0
    remaining_mask = otros_mask & (df["actor_subcategory"].astype(str).str.strip() == "")

    if use_ai and remaining_mask.sum() > 0:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            client = Anthropic(api_key=api_key)
            candidates = df[remaining_mask]

            if len(candidates) > MAX_AI_SAMPLE:
                candidates = candidates.sample(n=MAX_AI_SAMPLE, random_state=42)

            logger.info("AI actor classification: processing %d mentions", len(candidates))
            indices = list(candidates.index)

            for batch_start in range(0, len(indices), BATCH_SIZE):
                batch_idx = indices[batch_start:batch_start + BATCH_SIZE]
                batch_texts = [str(df.at[i, "text"])[:300] for i in batch_idx]
                batch_platforms = [str(df.at[i, "platform"]) if "platform" in df.columns else "" for i in batch_idx]
                batch_authors = [str(df.at[i, "author"]) if "author" in df.columns else "" for i in batch_idx]

                results = _ai_classify_actors_batch(batch_texts, batch_platforms, batch_authors, client)

                for idx, category in zip(batch_idx, results):
                    if category:
                        df.at[idx, "actor_subcategory"] = category
                        ai_classified += 1

    # Set remaining unclassified to "opinion_publica" (reasonable default)
    still_empty = otros_mask & (df["actor_subcategory"].astype(str).str.strip() == "")
    df.loc[still_empty, "actor_subcategory"] = "opinion_publica"
    default_assigned = still_empty.sum()

    # Stats
    final_otros = (df["actor_subcategory"] == "otros").sum()
    subcat_counts = df.loc[otros_mask, "actor_subcategory"].value_counts().to_dict()

    stats = {
        "original_otros": int(original_otros),
        "rules": int(rules_classified),
        "ai": int(ai_classified),
        "default_opinion": int(default_assigned),
        "remaining_otros": int(final_otros),
        "remaining_otros_pct": round(final_otros / max(len(df), 1) * 100, 1),
        "subcategory_breakdown": {str(k): int(v) for k, v in subcat_counts.items()},
    }

    logger.info(
        "Actor classification complete: rules=%d, ai=%d, default=%d, remaining_otros=%d (%.1f%%)\n"
        "  Subcategories: %s",
        rules_classified, ai_classified, default_assigned,
        final_otros, stats["remaining_otros_pct"],
        json.dumps(stats["subcategory_breakdown"], ensure_ascii=False),
    )

    return df, stats
