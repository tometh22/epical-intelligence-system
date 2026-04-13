"""Topic-aware relevance-based mention sampling for Claude's context input."""

import random
import re
from typing import Any, Dict, List, Tuple

import pandas as pd

from agents.shared.logger import get_logger

logger = get_logger("report-builder")

MAX_SAMPLE = 150

# Budget allocation
BUDGET_TOPIC = 80       # up to 80 for topic-representative samples (10 per topic × 8)
BUDGET_ENGAGEMENT = 40  # top by engagement
BUDGET_SPIKE = 20       # from spike days
BUDGET_SENTIMENT = 10   # 5 negative + 5 positive extremes


def build_relevance_sample(
    df: pd.DataFrame,
    metrics: Dict[str, Any],
    topic_clusters: List[Dict[str, Any]] = None,
) -> Tuple[List[str], str]:
    """Build a topic-aware relevance-weighted sample of mentions for Claude.

    Sampling strategy:
    1. Topic-representative: 8-10 mentions per detected topic cluster
    2. Top 40 by engagement (likes + comments + shares)
    3. Top 20 from spike days (volume > 2x daily average)
    4. Top 5 most negative + Top 5 most positive
    5. Top 10 from scrapping source
    6. Up to 20 Cossio/cossío mentions
    7. 10 random for diversity

    Deduplication between steps. Capped at 150.

    Args:
        df: Full cleaned DataFrame.
        metrics: Calculated metrics dict.
        topic_clusters: Optional pre-computed topic clusters from topics.detect_topic_clusters.

    Returns:
        (list of mention texts with metadata, composition summary string)
    """
    if "text" not in df.columns or df.empty:
        return [], "No text data available"

    df = df.copy()
    df["_eng_score"] = (
        df["likes"].fillna(0) + df["comments"].fillna(0) + df["shares"].fillna(0)
    )
    if "engagement" in df.columns:
        eng_col = df["engagement"].fillna(0)
        df["_eng_score"] = df[["_eng_score"]].join(eng_col.rename("_e")).max(axis=1)

    collected = pd.Index([], dtype="int64")
    composition = []  # type: List[str]

    # ------------------------------------------------------------------
    # 1. Topic-representative sampling
    # ------------------------------------------------------------------
    count_topic = 0
    topic_details = []  # type: List[str]
    if topic_clusters:
        n_topics = len(topic_clusters)
        per_topic = min(10, BUDGET_TOPIC // max(n_topics, 1))

        for cluster in topic_clusters:
            cluster_idx = pd.Index(cluster.get("mention_indices", []), dtype="int64")
            cluster_idx = cluster_idx.intersection(df.index)
            if cluster_idx.empty:
                continue

            remaining = cluster_idx.difference(collected)
            if remaining.empty:
                continue

            # Pick top by engagement within cluster, plus a couple random for diversity
            cluster_df = df.loc[remaining].sort_values("_eng_score", ascending=False)
            n_eng = min(per_topic - 2, len(cluster_df))
            top_indices = cluster_df.head(max(n_eng, 1)).index

            # Add 2 random from cluster for variety
            leftover = cluster_df.index.difference(top_indices)
            n_random = min(2, len(leftover))
            if n_random > 0:
                random_from_cluster = pd.Index(random.sample(list(leftover), n_random))
                top_indices = top_indices.append(random_from_cluster)

            # Cap per cluster
            top_indices = top_indices[:per_topic]

            new_idx = top_indices.difference(collected)
            collected = collected.append(new_idx)
            added = len(new_idx)
            count_topic += added
            topic_details.append(f"{cluster['label'][:30]}({added})")

    if topic_details:
        composition.append(f"{count_topic} topic-aware [{', '.join(topic_details)}]")
    else:
        composition.append("0 topic-aware")

    # ------------------------------------------------------------------
    # 2. Top 40 by engagement
    # ------------------------------------------------------------------
    top_eng = df["_eng_score"].nlargest(BUDGET_ENGAGEMENT).index
    new_idx = top_eng.difference(collected)
    collected = collected.append(new_idx)
    composition.append(f"{len(new_idx)} high engagement")

    # ------------------------------------------------------------------
    # 3. Top 20 from spike days
    # ------------------------------------------------------------------
    count_spike = 0
    if "date" in df.columns:
        date_col = df["date"].dropna()
        if not date_col.empty:
            daily_counts = date_col.dt.date.value_counts()
            avg_daily = daily_counts.mean()
            spike_days = daily_counts[daily_counts > 2 * avg_daily].index.tolist()

            spike_collected = 0
            for day in sorted(spike_days, key=lambda d: daily_counts[d], reverse=True):
                if spike_collected >= BUDGET_SPIKE:
                    break
                day_mask = df["date"].dt.date == day
                day_df = df[day_mask].sort_values("_eng_score", ascending=False)
                day_top = day_df.head(min(BUDGET_SPIKE - spike_collected, 10)).index
                new_idx = day_top.difference(collected)
                collected = collected.append(new_idx)
                spike_collected += len(new_idx)
            count_spike = spike_collected
    composition.append(f"{count_spike} spike day")

    # ------------------------------------------------------------------
    # 4. Sentiment extremes: 5 negative + 5 positive
    # ------------------------------------------------------------------
    count_neg = 0
    count_pos = 0
    if "sentiment" in df.columns:
        neg_mask = df["sentiment"].isin(["negative", "negativo", "neg"])
        neg_df = df[neg_mask].sort_values("_eng_score", ascending=False)
        if not neg_df.empty:
            neg_top = neg_df.head(5).index.difference(collected)
            collected = collected.append(neg_top)
            count_neg = len(neg_top)

        pos_mask = df["sentiment"].isin(["positive", "positivo", "pos"])
        pos_df = df[pos_mask].sort_values("_eng_score", ascending=False)
        if not pos_df.empty:
            pos_top = pos_df.head(5).index.difference(collected)
            collected = collected.append(pos_top)
            count_pos = len(pos_top)
    composition.append(f"{count_neg} negative + {count_pos} positive")

    # ------------------------------------------------------------------
    # 5. Top 10 from scrapping
    # ------------------------------------------------------------------
    count_scr = 0
    if "data_source" in df.columns:
        scr_df = df[df["data_source"] == "scrapping"].sort_values("_eng_score", ascending=False)
        if not scr_df.empty:
            scr_top = scr_df.head(10).index.difference(collected)
            collected = collected.append(scr_top)
            count_scr = len(scr_top)
    composition.append(f"{count_scr} scrapping")

    # ------------------------------------------------------------------
    # 6. Cossio mentions, max 20
    # ------------------------------------------------------------------
    count_cossio = 0
    cossio_pattern = re.compile(r"cossi[oó]", re.IGNORECASE)
    cossio_mask = df["text"].astype(str).apply(lambda t: bool(cossio_pattern.search(t)))
    cossio_df = df[cossio_mask].sort_values("_eng_score", ascending=False)
    if not cossio_df.empty:
        cossio_top = cossio_df.head(20).index.difference(collected)
        collected = collected.append(cossio_top)
        count_cossio = len(cossio_top)
    composition.append(f"{count_cossio} cossio")

    # ------------------------------------------------------------------
    # 7. Random for diversity
    # ------------------------------------------------------------------
    count_random = 0
    leftover = df.index.difference(collected)
    if len(leftover) > 0:
        n = min(10, len(leftover))
        random_idx = pd.Index(random.sample(list(leftover), n))
        collected = collected.append(random_idx)
        count_random = n
    composition.append(f"{count_random} random")

    # ------------------------------------------------------------------
    # Cap & format
    # ------------------------------------------------------------------
    if len(collected) > MAX_SAMPLE:
        collected = collected[:MAX_SAMPLE]

    sample_df = df.loc[collected]
    mentions = []  # type: List[str]
    for _, row in sample_df.iterrows():
        text = str(row.get("text", ""))[:500]

        # Build rich metadata header
        date_str = ""
        if pd.notna(row.get("date")):
            try:
                date_str = str(row["date"])[:10]
            except Exception:
                pass
        platform_str = str(row.get("platform", "")) if pd.notna(row.get("platform")) else ""
        actor_str = str(row.get("actor", "")) if pd.notna(row.get("actor")) else ""
        if actor_str.lower() in ("otros", "unknown", "nan", ""):
            subcat = str(row.get("actor_subcategory", "")) if pd.notna(row.get("actor_subcategory")) else ""
            actor_str = subcat if subcat else "general"
        sent_str = str(row.get("sentiment", "")) if pd.notna(row.get("sentiment")) and str(row.get("sentiment")) not in ("", "nan") else ""
        eng = int(row.get("_eng_score", 0))
        author_str = str(row.get("author", "")) if pd.notna(row.get("author")) else ""

        # Format: [date | platform | actor | sentiment | engagement]
        # "Full mention text here"
        header_parts = [p for p in [date_str, platform_str, actor_str, sent_str, f"{eng} eng" if eng > 0 else ""] if p]
        header = " | ".join(header_parts)

        mention = f'[{header}]\n"{text}"'
        mentions.append(mention)

    total = len(mentions)
    comp_str = f"Topic-aware sample: {' + '.join(composition)} = {total} total (cap: {MAX_SAMPLE})"
    logger.info(comp_str)

    return mentions, comp_str
