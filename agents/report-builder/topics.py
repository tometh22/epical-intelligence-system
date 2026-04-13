"""Keyword-based topic clustering for mention analysis."""

import re
from collections import Counter
from typing import Any, Dict, List, Tuple

import pandas as pd

from agents.shared.logger import get_logger

logger = get_logger("report-builder")

# Common Spanish stopwords to exclude from n-grams
_STOPWORDS = frozenset(
    "de la el en los las un una que es por del al se lo con no su para"
    " más como pero ya le fue son muy hay me mi nos da ser está esto"
    " todo esta bien tiene sus fue entre era sin sobre todo hasta"
    " este esto solo donde ser hacer cada dos tres otro otra otros"
    " también puede ser tiene ese eso esa van hay tan poco mucho"
    " aquí ahí así como cual qué cómo cuando donde porque porqué"
    " http https www com t co pic twitter instagram tiktok facebook"
    " rt via cc amp".split()
)

MAX_TOPICS = 8
MIN_CLUSTER_SIZE = 3


def detect_topic_clusters(
    df: pd.DataFrame,
    max_topics: int = MAX_TOPICS,
) -> List[Dict[str, Any]]:
    """Detect topic clusters from all mentions using bigram/trigram frequency.

    Runs on the full dataset (not a sample) to capture all narratives.

    Args:
        df: DataFrame with at least a 'text' column.
        max_topics: Maximum number of topic clusters to return.

    Returns:
        List of topic cluster dicts, each with:
        - keywords: list of top keywords/phrases for this cluster
        - label: short label string (top 3 keywords joined)
        - mention_count: number of mentions in this cluster
        - percentage: % of total mentions
        - mention_indices: pandas Index of rows belonging to this cluster
    """
    if "text" not in df.columns or df.empty:
        return []

    texts = df["text"].dropna().astype(str)
    if texts.empty:
        return []

    total = len(texts)
    logger.info("Running topic detection on %d mentions...", total)

    # Tokenize and count bigrams/trigrams across all texts
    bigram_counter = Counter()  # type: Counter
    trigram_counter = Counter()  # type: Counter
    # Also track which mentions contain which n-grams
    bigram_to_indices = {}  # type: Dict[str, List[int]]
    trigram_to_indices = {}  # type: Dict[str, List[int]]

    for idx, text in texts.items():
        tokens = _tokenize(text)
        if len(tokens) < 2:
            continue

        # Bigrams
        seen_bigrams = set()
        for i in range(len(tokens) - 1):
            bg = f"{tokens[i]} {tokens[i+1]}"
            if bg not in seen_bigrams:
                bigram_counter[bg] += 1
                bigram_to_indices.setdefault(bg, []).append(idx)
                seen_bigrams.add(bg)

        # Trigrams
        seen_trigrams = set()
        for i in range(len(tokens) - 2):
            tg = f"{tokens[i]} {tokens[i+1]} {tokens[i+2]}"
            if tg not in seen_trigrams:
                trigram_counter[tg] += 1
                trigram_to_indices.setdefault(tg, []).append(idx)
                seen_trigrams.add(tg)

    # Merge bigrams and trigrams — prefer trigrams when they're frequent enough
    # A trigram needs at least MIN_CLUSTER_SIZE occurrences to qualify
    candidates = []  # type: List[Tuple[str, int, List[int]]]

    for tg, count in trigram_counter.most_common(50):
        if count >= MIN_CLUSTER_SIZE:
            candidates.append((tg, count, trigram_to_indices[tg]))

    for bg, count in bigram_counter.most_common(80):
        if count >= MIN_CLUSTER_SIZE:
            candidates.append((bg, count, bigram_to_indices[bg]))

    if not candidates:
        logger.info("No topic clusters found (insufficient recurring n-grams)")
        return []

    # Greedy clustering: pick top n-gram, assign its mentions, remove overlap
    clusters = []  # type: List[Dict[str, Any]]
    assigned = set()  # type: set

    # Sort by count descending
    candidates.sort(key=lambda x: x[1], reverse=True)

    for phrase, count, indices in candidates:
        if len(clusters) >= max_topics:
            break

        # Filter out already-assigned indices
        remaining = [i for i in indices if i not in assigned]
        if len(remaining) < MIN_CLUSTER_SIZE:
            continue

        # Check this phrase isn't a substring of an already-picked cluster label
        skip = False
        for existing in clusters:
            for kw in existing["keywords"]:
                if phrase in kw or kw in phrase:
                    # Merge indices into existing cluster instead
                    existing_set = set(existing["mention_indices"])
                    new_additions = [i for i in remaining if i not in existing_set]
                    existing["mention_indices"] = list(existing_set | set(new_additions))
                    existing["mention_count"] = len(existing["mention_indices"])
                    existing["percentage"] = round(existing["mention_count"] / total * 100, 1)
                    assigned.update(new_additions)
                    skip = True
                    break
            if skip:
                break

        if skip:
            continue

        # Find additional representative keywords for this cluster
        cluster_indices = set(remaining)
        assigned.update(cluster_indices)
        extra_keywords = _find_cluster_keywords(texts, cluster_indices, phrase)

        cluster = {
            "keywords": [phrase] + extra_keywords[:2],
            "label": phrase,
            "mention_count": len(cluster_indices),
            "percentage": round(len(cluster_indices) / total * 100, 1),
            "mention_indices": list(cluster_indices),
        }
        clusters.append(cluster)

    # Sort by mention_count descending
    clusters.sort(key=lambda c: c["mention_count"], reverse=True)

    # Log results
    for i, c in enumerate(clusters, 1):
        logger.info(
            "Topic %d: [%s] — %d mentions (%.1f%%)",
            i, ", ".join(c["keywords"]), c["mention_count"], c["percentage"],
        )

    return clusters


def format_topic_summary(clusters: List[Dict[str, Any]]) -> str:
    """Format topic clusters into a string summary for Claude's context."""
    if not clusters:
        return "No se detectaron clusters temáticos claros."

    lines = ["Topic clusters detected:"]
    for i, c in enumerate(clusters, 1):
        kw_str = ", ".join(c["keywords"])
        lines.append(
            f"  {i}. [{kw_str}] — {c['mention_count']} mentions ({c['percentage']}%)"
        )

    return "\n".join(lines)


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase words, removing stopwords and short tokens."""
    # Remove URLs
    text = re.sub(r"https?://\S+", "", text)
    # Remove mentions and hashtags symbols (keep the word)
    text = re.sub(r"[@#]", "", text)
    # Keep only letters (including accented) and spaces
    text = re.sub(r"[^a-záéíóúüñA-ZÁÉÍÓÚÜÑ\s]", " ", text)
    tokens = text.lower().split()
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 2]


def _find_cluster_keywords(
    texts: pd.Series,
    cluster_indices: set,
    primary_phrase: str,
) -> List[str]:
    """Find additional keywords that are frequent within a cluster but not globally."""
    primary_tokens = set(primary_phrase.split())
    word_counter = Counter()  # type: Counter

    for idx in cluster_indices:
        if idx in texts.index:
            tokens = _tokenize(str(texts[idx]))
            for t in tokens:
                if t not in primary_tokens:
                    word_counter[t] += 1

    # Return top words that appear in at least 30% of cluster mentions
    threshold = max(2, len(cluster_indices) * 0.3)
    extra = [word for word, count in word_counter.most_common(10) if count >= threshold]
    return extra
