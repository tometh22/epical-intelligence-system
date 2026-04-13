"""AI-powered sentiment reclassification for unclassified mentions."""

import json
import os
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
MAX_AI_SAMPLE = 20000  # Classify ALL unclassified mentions
MIN_TEXT_LENGTH = 10

# ---------------------------------------------------------------------------
# Keyword dictionaries
# ---------------------------------------------------------------------------

POSITIVE_KEYWORDS = [
    "excelente", "gracias", "perfecto", "bien", "genial",
    "increíble", "feliz", "amor", "bueno", "mejor", "bravo",
    "correcto", "justo", "apoyo", "apoya", "razón tienen",
    "ótimo", "obrigado", "perfeito", "bom", "incrível",
    "bien hecho", "me encanta", "gran trabajo", "excelente servicio",
    "muy bien", "felicitaciones", "orgulloso",
]

NEGATIVE_KEYWORDS = [
    "terrible", "pésimo", "vergüenza", "malo", "peor",
    "horrible", "asco", "odio", "injusto", "exagerado",
    "ridículo", "abuso", "boicot", "nunca más", "fraude",
    "péssimo", "horrível", "vergonha",
    "pésima", "inaceptable", "vergonzoso", "desastre",
    "estafa", "robo", "basura", "indignante", "miserables",
]

NEUTRAL_INDICATORS = [
    "según", "informó", "reportó", "anunció", "declaró",
    "comunicó", "explicó", "notificó", "informou", "segundo",
    "fuente:", "según fuentes", "el comunicado", "se informó",
]


def _count_keyword_matches(text: str, keywords: List[str]) -> int:
    """Count how many keywords appear in the text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw in text_lower)


def _rule_based_classify(text: str) -> Optional[str]:
    """Classify sentiment using keyword rules. Returns None if no clear match."""
    if not text or len(text.strip()) < MIN_TEXT_LENGTH:
        return None

    pos = _count_keyword_matches(text, POSITIVE_KEYWORDS)
    neg = _count_keyword_matches(text, NEGATIVE_KEYWORDS)
    neu = _count_keyword_matches(text, NEUTRAL_INDICATORS)

    if pos == 0 and neg == 0 and neu == 0:
        return None

    if pos > neg and pos > neu:
        return "positivo"
    elif neg > pos and neg > neu:
        return "negativo"
    elif neu > pos and neu > neg:
        return "neutral"
    elif pos == neg and pos > 0:
        return "neutral"  # tied pos/neg → neutral
    elif pos > 0 or neg > 0:
        return "positivo" if pos > neg else "negativo"
    return "neutral"


def _ai_classify_batch(
    texts: List[str],
    client: Anthropic,
) -> List[Optional[str]]:
    """Send a batch of texts to Haiku for sentiment classification."""
    if not texts:
        return []

    numbered = "\n".join(f"{i+1}. {t[:300]}" for i, t in enumerate(texts))
    user_prompt = f"Classify these {len(texts)} mentions:\n{numbered}"

    system_prompt = (
        "You are a sentiment classifier for social media mentions "
        "in Spanish and Portuguese about an airline crisis in "
        "Latin America. Classify each mention as exactly one of: "
        "POSITIVO, NEGATIVO, or NEUTRAL.\n\n"
        "POSITIVO: support, praise, agreement, satisfaction\n"
        "NEGATIVO: criticism, anger, complaint, rejection\n"
        "NEUTRAL: news, information, questions without clear valence\n\n"
        "Respond ONLY with a JSON array of classifications "
        "in the same order as input.\n"
        'Example: ["POSITIVO", "NEGATIVO", "NEUTRAL", "NEGATIVO"]\n'
        "No other text."
    )

    try:
        message = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        response_text = message.content[0].text.strip()

        # Parse JSON array from response
        # Handle case where model wraps in markdown code block
        cleaned = re.sub(r'^```json\s*', '', response_text)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        results = json.loads(cleaned)

        if not isinstance(results, list):
            logger.warning("AI response is not a list: %s", response_text[:100])
            return [None] * len(texts)

        # Normalize values
        valid = {"positivo", "negativo", "neutral"}
        normalized = []
        for r in results:
            val = str(r).strip().lower() if r else None
            normalized.append(val if val in valid else None)

        # Pad or truncate to match input length
        while len(normalized) < len(texts):
            normalized.append(None)
        return normalized[:len(texts)]

    except Exception as e:
        logger.error("AI classification batch failed: %s", e)
        return [None] * len(texts)


def reclassify_sentiment(
    df: pd.DataFrame,
    use_ai: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Reclassify unclassified sentiment using rules and optionally AI.

    Args:
        df: DataFrame with 'text' and 'sentiment' columns.
        use_ai: Whether to use Haiku API for remaining unclassified.

    Returns:
        (updated DataFrame, reclassification stats dict)
    """
    if "sentiment" not in df.columns or "text" not in df.columns:
        return df, {"skipped": True, "reason": "missing columns"}

    df = df.copy()

    # Ensure sentiment_source column
    if "sentiment_source" not in df.columns:
        df["sentiment_source"] = "original"

    # Identify unclassified rows
    unclassified_mask = (
        df["sentiment"].isna() |
        (df["sentiment"].astype(str).str.strip() == "") |
        (df["sentiment"].astype(str).str.lower().isin(["<na>", "nan", "none", "sin clasificar"]))
    )

    original_unclassified = unclassified_mask.sum()
    logger.info("Sentiment reclassification: %d unclassified out of %d total",
                original_unclassified, len(df))

    if original_unclassified == 0:
        return df, {"original_unclassified": 0, "rules": 0, "ai": 0, "remaining": 0}

    # STEP 1: Rule-based classification
    rules_classified = 0
    for idx in df[unclassified_mask].index:
        text = str(df.at[idx, "text"])
        result = _rule_based_classify(text)
        if result:
            df.at[idx, "sentiment"] = result
            df.at[idx, "sentiment_source"] = "rules"
            rules_classified += 1

    logger.info("Rule-based classification: %d reclassified", rules_classified)

    # Update unclassified mask
    unclassified_mask = (
        df["sentiment"].isna() |
        (df["sentiment"].astype(str).str.strip() == "") |
        (df["sentiment"].astype(str).str.lower().isin(["<na>", "nan", "none", "sin clasificar"]))
    )
    still_unclassified = unclassified_mask.sum()

    # STEP 2: AI classification
    ai_classified = 0
    if use_ai and still_unclassified > 0:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            logger.warning("No ANTHROPIC_API_KEY — skipping AI classification")
        else:
            client = Anthropic(api_key=api_key)

            # Build sample: prioritize high-engagement, filter short texts
            candidates = df[unclassified_mask].copy()
            candidates = candidates[candidates["text"].astype(str).str.len() >= MIN_TEXT_LENGTH]

            if len(candidates) > MAX_AI_SAMPLE:
                # Take all high-engagement first
                high_eng = candidates[candidates.get("engagement", pd.Series(0, index=candidates.index)).fillna(0) > 10]
                remaining = candidates.drop(high_eng.index)
                sample_size = min(MAX_AI_SAMPLE - len(high_eng), len(remaining))
                if sample_size > 0:
                    sampled = remaining.sample(n=sample_size, random_state=42)
                    candidates = pd.concat([high_eng, sampled])
                else:
                    candidates = high_eng.head(MAX_AI_SAMPLE)

            logger.info("AI classification: processing %d mentions in batches of %d",
                        len(candidates), BATCH_SIZE)

            # Process in batches
            indices = list(candidates.index)
            for batch_start in range(0, len(indices), BATCH_SIZE):
                batch_indices = indices[batch_start:batch_start + BATCH_SIZE]
                batch_texts = [str(df.at[idx, "text"]) for idx in batch_indices]

                results = _ai_classify_batch(batch_texts, client)

                for idx, sentiment in zip(batch_indices, results):
                    if sentiment:
                        df.at[idx, "sentiment"] = sentiment
                        df.at[idx, "sentiment_source"] = "ai_classified"
                        ai_classified += 1

                batch_num = batch_start // BATCH_SIZE + 1
                total_batches = (len(indices) + BATCH_SIZE - 1) // BATCH_SIZE
                logger.info("AI batch %d/%d complete (%d classified so far)",
                            batch_num, total_batches, ai_classified)

    # STEP 3: Re-evaluate "neutral" mentions — many are misclassified
    neutral_reclassified = 0
    if use_ai:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key:
            neutral_mask = df["sentiment"].astype(str).str.lower() == "neutral"
            neutral_candidates = df[neutral_mask].copy()
            # Only re-evaluate neutrals with text > 20 chars (short ones are likely truly neutral)
            neutral_candidates = neutral_candidates[
                neutral_candidates["text"].astype(str).str.len() > 20
            ]

            if len(neutral_candidates) > 0:
                logger.info("Re-evaluating %d 'neutral' mentions for false neutrals...", len(neutral_candidates))
                client = Anthropic(api_key=api_key)
                n_indices = list(neutral_candidates.index)

                for batch_start in range(0, len(n_indices), BATCH_SIZE):
                    batch_idx = n_indices[batch_start:batch_start + BATCH_SIZE]
                    batch_texts = [str(df.at[i, "text"]) for i in batch_idx]

                    results = _ai_classify_batch(batch_texts, client)

                    for idx, new_sent in zip(batch_idx, results):
                        if new_sent and new_sent != "neutral":
                            df.at[idx, "sentiment"] = new_sent
                            df.at[idx, "sentiment_source"] = "ai_neutral_review"
                            neutral_reclassified += 1

                    batch_num = batch_start // BATCH_SIZE + 1
                    total_batches = (len(n_indices) + BATCH_SIZE - 1) // BATCH_SIZE
                    if batch_num % 20 == 0 or batch_num == total_batches:
                        logger.info("Neutral review batch %d/%d (%d reclassified so far)",
                                    batch_num, total_batches, neutral_reclassified)

                logger.info("Neutral review complete: %d reclassified out of %d reviewed",
                            neutral_reclassified, len(neutral_candidates))

    # Final stats
    final_unclassified_mask = (
        df["sentiment"].isna() |
        (df["sentiment"].astype(str).str.strip() == "") |
        (df["sentiment"].astype(str).str.lower().isin(["<na>", "nan", "none", "sin clasificar"]))
    )
    remaining = final_unclassified_mask.sum()

    # Calculate new breakdown
    total = len(df)
    sent_counts = df["sentiment"].value_counts()
    new_breakdown = {}
    for val, count in sent_counts.items():
        val_str = str(val).lower().strip()
        if val_str not in ("", "nan", "none", "<na>", "sin clasificar"):
            new_breakdown[val_str] = {"count": int(count), "pct": round(count / total * 100, 1)}

    stats = {
        "original_unclassified": int(original_unclassified),
        "rules": int(rules_classified),
        "rules_pct": round(rules_classified / max(original_unclassified, 1) * 100, 1),
        "ai": int(ai_classified),
        "ai_pct": round(ai_classified / max(original_unclassified, 1) * 100, 1),
        "neutral_reviewed": int(neutral_reclassified),
        "remaining": int(remaining),
        "remaining_pct": round(remaining / total * 100, 1),
        "new_breakdown": new_breakdown,
    }

    logger.info(
        "Sentiment reclassification complete:\n"
        "  Original unclassified: %d\n"
        "  Reclassified by rules: %d (%.1f%%)\n"
        "  Reclassified by AI: %d (%.1f%%)\n"
        "  Still unclassified: %d (%.1f%%)\n"
        "  New breakdown: %s",
        stats["original_unclassified"],
        stats["rules"], stats["rules_pct"],
        stats["ai"], stats["ai_pct"],
        stats["remaining"], stats["remaining_pct"],
        json.dumps(stats["new_breakdown"], ensure_ascii=False),
    )

    return df, stats
