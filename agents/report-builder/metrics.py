"""Metrics calculation and anomaly detection for social intelligence data.

Provides the MetricsCalculator class with 8 spec methods plus legacy
compatibility functions used by the existing pipeline.
"""

from collections import Counter
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from agents.shared.logger import get_logger

logger = get_logger("report-builder")


class MetricsCalculator:
    """Computes all metrics required by the Epical Intelligence System spec.

    Operates on a unified-schema DataFrame with columns:
        date, text, sentiment, author, platform, engagement,
        likes, comments, shares, reach, country, actor,
        actor_subcategory, data_source, url
    """

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.copy()
        self._normalize_actors()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_actors(self) -> None:
        """Replace unknown/empty actor values with 'otros'."""
        if "actor" in self.df.columns:
            unknown = {"unknown", "<na>", "nan", "n/a", "none", ""}
            self.df["actor"] = self.df["actor"].astype(str).str.strip().str.lower()
            self.df.loc[self.df["actor"].isin(unknown), "actor"] = "otros"

    @staticmethod
    def _safe_div(num: float, den: float, decimals: int = 1) -> float:
        if den == 0:
            return 0.0
        return round(num / den * 100, decimals)

    @staticmethod
    def _format_big_number(n: float) -> str:
        """Format large numbers for display: 692K, 29M, 233M."""
        abs_n = abs(n)
        if abs_n >= 1_000_000_000:
            return f"{n / 1_000_000_000:.1f}B"
        if abs_n >= 1_000_000:
            return f"{n / 1_000_000:.0f}M" if abs_n >= 10_000_000 else f"{n / 1_000_000:.1f}M"
        if abs_n >= 1_000:
            return f"{n / 1_000:.0f}K" if abs_n >= 10_000 else f"{n / 1_000:.1f}K"
        return str(int(n))

    def _engagement_sum(self, subset: pd.DataFrame) -> int:
        """Total engagement = likes + comments + shares (fallback to engagement col)."""
        total = 0
        for col in ("likes", "comments", "shares"):
            if col in subset.columns:
                total += int(subset[col].fillna(0).sum())
        if total == 0 and "engagement" in subset.columns:
            total = int(subset["engagement"].fillna(0).sum())
        return total

    # ------------------------------------------------------------------
    # 1. Co-occurrence of concepts for narrative graphs
    # ------------------------------------------------------------------

    def compute_cooccurrence(
        self,
        concepts: List[str],
        min_cooccurrence: int = 3,
        top_n: int = 50,
    ) -> Dict[str, Any]:
        """Compute co-occurrence matrix from mention texts for narrative graphs.

        Each mention's text is scanned for concept keywords. When two concepts
        appear in the same mention, their edge weight increases by 1.

        Args:
            concepts: List of concept keywords/phrases to look for.
            min_cooccurrence: Minimum co-occurrences to include an edge.
            top_n: Max number of edges to return (by weight descending).

        Returns:
            {
                "nodes": [{"id": str, "mentions": int, "sentiment_pct": {...}}],
                "edges": [{"source": str, "target": str, "weight": int}],
                "total_mentions_analyzed": int
            }
        """
        if "text" not in self.df.columns or not concepts:
            return {"nodes": [], "edges": [], "total_mentions_analyzed": 0}

        import re

        # Precompile patterns — case insensitive, word boundaries where possible
        patterns = {}
        for c in concepts:
            try:
                patterns[c] = re.compile(r"(?i)\b" + re.escape(c) + r"\b")
            except re.error:
                patterns[c] = re.compile(re.escape(c), re.IGNORECASE)

        # Scan texts
        concept_mentions: Dict[str, List[int]] = {c: [] for c in concepts}
        edge_counter: Counter = Counter()
        texts = self.df["text"].astype(str)

        for idx, text in texts.items():
            found = [c for c, pat in patterns.items() if pat.search(text)]
            for c in found:
                concept_mentions[c].append(idx)
            for a, b in combinations(sorted(found), 2):
                edge_counter[(a, b)] += 1

        # Build nodes
        nodes = []
        for c in concepts:
            idxs = concept_mentions[c]
            if not idxs:
                continue
            node_data: Dict[str, Any] = {"id": c, "mentions": len(idxs)}
            if "sentiment" in self.df.columns:
                subset = self.df.loc[self.df.index.isin(idxs)]
                sent_counts = subset["sentiment"].value_counts()
                total = len(subset)
                node_data["sentiment_pct"] = {
                    str(k): self._safe_div(v, total) for k, v in sent_counts.items()
                }
            nodes.append(node_data)

        # Build edges (filtered)
        edges = [
            {"source": pair[0], "target": pair[1], "weight": w}
            for pair, w in edge_counter.most_common(top_n)
            if w >= min_cooccurrence
        ]

        logger.info(
            "Co-occurrence: %d nodes, %d edges from %d concepts",
            len(nodes), len(edges), len(concepts),
        )
        return {
            "nodes": nodes,
            "edges": edges,
            "total_mentions_analyzed": len(texts),
        }

    # ------------------------------------------------------------------
    # 2. Engagement by platform
    # ------------------------------------------------------------------

    def compute_engagement_by_platform(self) -> List[Dict[str, Any]]:
        """Compute engagement metrics broken down by platform.

        Returns list sorted by total engagement descending:
        [
            {
                "platform": str,
                "mentions": int,
                "total_engagement": int,
                "avg_engagement": float,
                "engagement_share": float,  # % of total engagement
                "total_likes": int,
                "total_comments": int,
                "total_shares": int,
                "total_reach": int,
                "avg_reach": float,
                "reach_share": float,
                "sentiment_breakdown": {...}
            }
        ]
        """
        col = "platform" if "platform" in self.df.columns else "source"
        if col not in self.df.columns:
            return []

        grand_engagement = max(self._engagement_sum(self.df), 1)
        grand_reach = max(int(self.df["reach"].fillna(0).sum()) if "reach" in self.df.columns else 1, 1)

        results = []
        for platform, group in self.df.groupby(col, dropna=True):
            platform_str = str(platform).strip()
            if not platform_str:
                continue

            eng = self._engagement_sum(group)
            mentions = len(group)
            reach = int(group["reach"].fillna(0).sum()) if "reach" in group.columns else 0

            entry: Dict[str, Any] = {
                "platform": platform_str,
                "mentions": mentions,
                "total_engagement": eng,
                "avg_engagement": round(eng / max(mentions, 1), 1),
                "engagement_share": self._safe_div(eng, grand_engagement),
                "total_likes": int(group["likes"].fillna(0).sum()) if "likes" in group.columns else 0,
                "total_comments": int(group["comments"].fillna(0).sum()) if "comments" in group.columns else 0,
                "total_shares": int(group["shares"].fillna(0).sum()) if "shares" in group.columns else 0,
                "total_reach": reach,
                "avg_reach": round(reach / max(mentions, 1), 1),
                "reach_share": self._safe_div(reach, grand_reach),
            }

            # Sentiment breakdown per platform
            if "sentiment" in group.columns:
                sent = group["sentiment"].value_counts()
                entry["sentiment_breakdown"] = {
                    str(k): {"count": int(v), "percentage": self._safe_div(v, mentions)}
                    for k, v in sent.items()
                }

            results.append(entry)

        results.sort(key=lambda x: x["total_engagement"], reverse=True)
        logger.info("Engagement by platform: %d platforms", len(results))
        return results

    # ------------------------------------------------------------------
    # 3. Timeline with daily data
    # ------------------------------------------------------------------

    def compute_timeline(self) -> Dict[str, Any]:
        """Compute daily timeline with volume, engagement, and sentiment.

        Returns:
            {
                "daily": [
                    {
                        "date": "YYYY-MM-DD",
                        "mentions": int,
                        "engagement": int,
                        "sentiment": {"positive": int, "negative": int, ...},
                        "top_platform": str
                    }
                ],
                "period_start": str,
                "period_end": str,
                "total_days": int
            }
        """
        if "date" not in self.df.columns:
            return {"daily": [], "period_start": None, "period_end": None, "total_days": 0}

        df = self.df.dropna(subset=["date"]).copy()
        if df.empty:
            return {"daily": [], "period_start": None, "period_end": None, "total_days": 0}

        df["date_only"] = df["date"].dt.date
        dates_sorted = sorted(df["date_only"].unique())

        daily = []
        for d in dates_sorted:
            day_df = df[df["date_only"] == d]
            entry: Dict[str, Any] = {
                "date": str(d),
                "mentions": len(day_df),
                "engagement": self._engagement_sum(day_df),
            }

            if "sentiment" in day_df.columns:
                entry["sentiment"] = {
                    str(k): int(v) for k, v in day_df["sentiment"].value_counts().items()
                }

            pcol = "platform" if "platform" in day_df.columns else "source"
            if pcol in day_df.columns:
                top = day_df[pcol].value_counts()
                entry["top_platform"] = str(top.index[0]) if not top.empty else None

            daily.append(entry)

        return {
            "daily": daily,
            "period_start": str(dates_sorted[0]),
            "period_end": str(dates_sorted[-1]),
            "total_days": len(dates_sorted),
        }

    # ------------------------------------------------------------------
    # 4. Comunicado / event impact analysis
    # ------------------------------------------------------------------

    def compute_comunicado_impact(
        self,
        event_date: str,
        window_days: int = 7,
    ) -> Dict[str, Any]:
        """Analyze impact before vs after a specific event/comunicado date.

        Args:
            event_date: Date string (YYYY-MM-DD) of the event.
            window_days: Number of days before/after to analyze.

        Returns:
            {
                "event_date": str,
                "pre": {"mentions": int, "engagement": int, "sentiment": {...}, "avg_daily_mentions": float},
                "post": {"mentions": int, "engagement": int, "sentiment": {...}, "avg_daily_mentions": float},
                "delta": {"mentions_pct": float, "engagement_pct": float, "negative_shift": float},
                "peak_day": {"date": str, "mentions": int},
                "recovery_days": int | None
            }
        """
        if "date" not in self.df.columns:
            return {"event_date": event_date, "pre": {}, "post": {}, "delta": {}}

        event_dt = pd.Timestamp(event_date).date()
        df = self.df.dropna(subset=["date"]).copy()
        df["date_only"] = df["date"].dt.date

        pre_start = event_dt - pd.Timedelta(days=window_days)
        post_end = event_dt + pd.Timedelta(days=window_days)

        pre_df = df[(df["date_only"] >= pre_start) & (df["date_only"] < event_dt)]
        post_df = df[(df["date_only"] >= event_dt) & (df["date_only"] <= post_end)]

        def _period_stats(subset: pd.DataFrame, num_days: int) -> Dict[str, Any]:
            stats: Dict[str, Any] = {
                "mentions": len(subset),
                "engagement": self._engagement_sum(subset),
                "avg_daily_mentions": round(len(subset) / max(num_days, 1), 1),
            }
            if "sentiment" in subset.columns and not subset.empty:
                sent = subset["sentiment"].value_counts()
                total = len(subset)
                stats["sentiment"] = {
                    str(k): {"count": int(v), "percentage": self._safe_div(v, total)}
                    for k, v in sent.items()
                }
            else:
                stats["sentiment"] = {}
            return stats

        pre_days = max(len(pre_df["date_only"].unique()), 1) if not pre_df.empty else 1
        post_days = max(len(post_df["date_only"].unique()), 1) if not post_df.empty else 1

        pre_stats = _period_stats(pre_df, pre_days)
        post_stats = _period_stats(post_df, post_days)

        # Deltas
        delta: Dict[str, Any] = {
            "mentions_pct": self._safe_div(
                post_stats["mentions"] - pre_stats["mentions"],
                max(pre_stats["mentions"], 1),
            ),
            "engagement_pct": self._safe_div(
                post_stats["engagement"] - pre_stats["engagement"],
                max(pre_stats["engagement"], 1),
            ),
        }

        # Negative sentiment shift
        def _neg_pct(stats: Dict) -> float:
            for key in ("negative", "negativo"):
                if key in stats.get("sentiment", {}):
                    return stats["sentiment"][key].get("percentage", 0.0)
            return 0.0

        delta["negative_shift"] = round(_neg_pct(post_stats) - _neg_pct(pre_stats), 1)

        # Peak day in post period
        peak_day: Dict[str, Any] = {"date": None, "mentions": 0}
        if not post_df.empty:
            day_counts = post_df["date_only"].value_counts()
            if not day_counts.empty:
                peak = day_counts.idxmax()
                peak_day = {"date": str(peak), "mentions": int(day_counts.max())}

        # Recovery: first day post-event where daily volume drops below pre-avg
        recovery_days = None
        if not post_df.empty and pre_stats["avg_daily_mentions"] > 0:
            post_daily = post_df.groupby("date_only").size()
            pre_avg = pre_stats["avg_daily_mentions"]
            for d in sorted(post_daily.index):
                if d > event_dt and post_daily[d] <= pre_avg * 1.2:
                    recovery_days = (d - event_dt).days
                    break

        logger.info(
            "Comunicado impact: pre=%d mentions, post=%d mentions, delta=%.1f%%",
            pre_stats["mentions"], post_stats["mentions"], delta["mentions_pct"],
        )

        return {
            "event_date": event_date,
            "window_days": window_days,
            "pre": pre_stats,
            "post": post_stats,
            "delta": delta,
            "peak_day": peak_day,
            "recovery_days": recovery_days,
        }

    # ------------------------------------------------------------------
    # 5. Tangential / catalyst effect analysis
    # ------------------------------------------------------------------

    def compute_tangential_analysis(
        self,
        tangential_mentions: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Analyze tangential mentions for catalyst effect detection.

        The catalyst effect: did the incident amplify pre-existing dissatisfaction?
        Tangential mentions = those classified as tangential/indirectly related.

        Args:
            tangential_mentions: Subset of tangential mentions. If None, attempts
                to filter from self.df using sentiment == 'tangential' or
                a 'relevance' column.

        Returns:
            {
                "total_tangential": int,
                "negative_tangential": int,
                "negative_tangential_pct": float,
                "catalyst_detected": bool,
                "catalyst_strength": "high" | "medium" | "low" | "none",
                "top_themes": [{"theme": str, "count": int, "pct": float}],
                "temporal_correlation": {...},
                "pre_existing_issues": [str]
            }
        """
        if tangential_mentions is not None:
            tang_df = tangential_mentions.copy()
        elif "relevance" in self.df.columns:
            tang_df = self.df[self.df["relevance"].astype(str).str.lower() == "tangential"].copy()
        else:
            # No tangential data available
            return {
                "total_tangential": 0,
                "negative_tangential": 0,
                "negative_tangential_pct": 0.0,
                "catalyst_detected": False,
                "catalyst_strength": "none",
                "top_themes": [],
                "temporal_correlation": {},
                "pre_existing_issues": [],
            }

        total = len(tang_df)
        if total == 0:
            return {
                "total_tangential": 0,
                "negative_tangential": 0,
                "negative_tangential_pct": 0.0,
                "catalyst_detected": False,
                "catalyst_strength": "none",
                "top_themes": [],
                "temporal_correlation": {},
                "pre_existing_issues": [],
            }

        # Count negative tangentials
        neg_count = 0
        if "sentiment" in tang_df.columns:
            neg_mask = tang_df["sentiment"].astype(str).str.lower().isin(["negative", "negativo"])
            neg_count = int(neg_mask.sum())
        neg_pct = self._safe_div(neg_count, total)

        # Catalyst strength based on % negative tangentials
        if neg_pct >= 60:
            strength = "high"
        elif neg_pct >= 35:
            strength = "medium"
        elif neg_pct >= 15:
            strength = "low"
        else:
            strength = "none"

        catalyst_detected = strength in ("high", "medium")

        # Extract themes from tangential mentions via word frequency
        top_themes: List[Dict[str, Any]] = []
        if "text" in tang_df.columns:
            from collections import Counter as _Counter
            import re as _re

            stopwords = {
                "de", "la", "el", "en", "que", "y", "a", "los", "las", "del",
                "un", "una", "por", "con", "para", "es", "se", "no", "lo",
                "al", "le", "su", "como", "más", "pero", "sus", "ya", "o",
                "fue", "ser", "son", "está", "ha", "me", "si", "sobre",
                "todo", "esta", "hay", "muy", "sin", "este", "the", "and",
                "is", "to", "of", "in", "for", "on", "with", "https", "http",
                "com", "www", "rt", "via",
            }

            words = _Counter()
            for text in tang_df["text"].astype(str):
                tokens = _re.findall(r"\b[a-záéíóúñü]{4,}\b", text.lower())
                words.update(t for t in tokens if t not in stopwords)

            for word, count in words.most_common(10):
                top_themes.append({
                    "theme": word,
                    "count": count,
                    "pct": self._safe_div(count, total),
                })

        # Temporal correlation: did tangentials spike after main event?
        temporal: Dict[str, Any] = {}
        if "date" in tang_df.columns:
            tang_dated = tang_df.dropna(subset=["date"]).copy()
            if not tang_dated.empty:
                tang_dated["date_only"] = tang_dated["date"].dt.date
                daily = tang_dated.groupby("date_only").size()
                if len(daily) >= 2:
                    dates = sorted(daily.index)
                    mid = len(dates) // 2
                    first_half = daily[daily.index.isin(dates[:mid])].sum()
                    second_half = daily[daily.index.isin(dates[mid:])].sum()
                    temporal = {
                        "first_half_mentions": int(first_half),
                        "second_half_mentions": int(second_half),
                        "trend": "increasing" if second_half > first_half * 1.3 else (
                            "decreasing" if first_half > second_half * 1.3 else "stable"
                        ),
                    }

        # Pre-existing issues = negative tangential themes
        pre_existing = [t["theme"] for t in top_themes[:5] if neg_pct > 20]

        logger.info(
            "Tangential analysis: %d total, %d negative (%.1f%%), catalyst=%s (%s)",
            total, neg_count, neg_pct, catalyst_detected, strength,
        )

        return {
            "total_tangential": total,
            "negative_tangential": neg_count,
            "negative_tangential_pct": neg_pct,
            "catalyst_detected": catalyst_detected,
            "catalyst_strength": strength,
            "top_themes": top_themes,
            "temporal_correlation": temporal,
            "pre_existing_issues": pre_existing,
        }

    # ------------------------------------------------------------------
    # 6. Deduplicated reach by unique account
    # ------------------------------------------------------------------

    def compute_reach_deduplicated(self) -> Dict[str, Any]:
        """Compute deduplicated potential reach by unique account.

        Rule 3 from spec: ALWAYS deduplicate reach by unique account.
        If the same author posts 5 times with 100K followers, reach = 100K not 500K.

        Returns:
            {
                "total_reach_raw": int,
                "total_reach_deduplicated": int,
                "unique_accounts": int,
                "inflation_factor": float,
                "reach_by_platform": [{platform, reach_dedup, unique_accounts}],
                "top_accounts": [{author, reach, mentions, platform}]
            }
        """
        raw_reach = int(self.df["reach"].fillna(0).sum()) if "reach" in self.df.columns else 0

        if "author" not in self.df.columns or "reach" not in self.df.columns:
            return {
                "total_reach_raw": raw_reach,
                "total_reach_deduplicated": raw_reach,
                "unique_accounts": self.df["author"].nunique() if "author" in self.df.columns else 0,
                "inflation_factor": 1.0,
                "reach_by_platform": [],
                "top_accounts": [],
            }

        # Deduplicate: take max reach per unique author (their follower count)
        author_reach = (
            self.df.groupby("author", dropna=True)["reach"]
            .max()
            .fillna(0)
        )
        dedup_reach = int(author_reach.sum())
        unique_accounts = len(author_reach)

        # Reach by platform (deduplicated within each platform)
        reach_by_platform = []
        pcol = "platform" if "platform" in self.df.columns else "source"
        if pcol in self.df.columns:
            for platform, group in self.df.groupby(pcol, dropna=True):
                plat_author_reach = group.groupby("author", dropna=True)["reach"].max().fillna(0)
                reach_by_platform.append({
                    "platform": str(platform),
                    "reach_deduplicated": int(plat_author_reach.sum()),
                    "unique_accounts": len(plat_author_reach),
                    "reach_formatted": self._format_big_number(plat_author_reach.sum()),
                })
            reach_by_platform.sort(key=lambda x: x["reach_deduplicated"], reverse=True)

        # Top accounts by reach
        top_accounts = []
        author_info = self.df.groupby("author", dropna=True).agg(
            reach=("reach", "max"),
            mentions=("text", "size"),
            platform=(pcol if pcol in self.df.columns else "author", "first"),
        ).sort_values("reach", ascending=False).head(15)

        for author, row in author_info.iterrows():
            top_accounts.append({
                "author": str(author),
                "reach": int(row["reach"]),
                "reach_formatted": self._format_big_number(row["reach"]),
                "mentions": int(row["mentions"]),
                "platform": str(row["platform"]),
            })

        inflation = round(raw_reach / max(dedup_reach, 1), 2)

        logger.info(
            "Reach dedup: raw=%s, dedup=%s, unique_accounts=%d, inflation=%.2fx",
            self._format_big_number(raw_reach),
            self._format_big_number(dedup_reach),
            unique_accounts, inflation,
        )

        return {
            "total_reach_raw": raw_reach,
            "total_reach_deduplicated": dedup_reach,
            "total_reach_formatted": self._format_big_number(dedup_reach),
            "unique_accounts": unique_accounts,
            "inflation_factor": inflation,
            "reach_by_platform": reach_by_platform,
            "top_accounts": top_accounts,
        }

    # ------------------------------------------------------------------
    # 7. Spike detection
    # ------------------------------------------------------------------

    def detect_spikes(
        self,
        daily_data: Optional[List[Dict[str, Any]]] = None,
        threshold_pct: float = 50.0,
    ) -> List[Dict[str, Any]]:
        """Detect volume spikes in daily timeline data.

        A spike = day-over-day increase exceeding threshold_pct.

        Args:
            daily_data: Output of compute_timeline()["daily"]. If None,
                computes timeline internally.
            threshold_pct: Minimum % increase to flag as spike (default 50%).

        Returns:
            [
                {
                    "date": str,
                    "mentions": int,
                    "previous_mentions": int,
                    "pct_change": float,
                    "severity": "critical" | "warning",
                    "engagement": int,
                    "top_sentiment": str,
                    "description": str
                }
            ]
        """
        if daily_data is None:
            timeline = self.compute_timeline()
            daily_data = timeline.get("daily", [])

        if len(daily_data) < 2:
            return []

        spikes = []
        for i in range(1, len(daily_data)):
            prev = daily_data[i - 1]
            curr = daily_data[i]
            prev_mentions = prev.get("mentions", 0)
            curr_mentions = curr.get("mentions", 0)

            if prev_mentions <= 0:
                continue

            pct_change = (curr_mentions - prev_mentions) / prev_mentions * 100

            if pct_change >= threshold_pct:
                severity = "critical" if pct_change > 100 else "warning"

                # Top sentiment on spike day
                sent = curr.get("sentiment", {})
                top_sentiment = max(sent, key=sent.get, default="unknown") if sent else "unknown"

                spikes.append({
                    "date": curr["date"],
                    "mentions": curr_mentions,
                    "previous_mentions": prev_mentions,
                    "pct_change": round(pct_change, 1),
                    "severity": severity,
                    "engagement": curr.get("engagement", 0),
                    "top_sentiment": top_sentiment,
                    "description": (
                        f"Incremento de {pct_change:.0f}% entre "
                        f"{prev['date']} ({prev_mentions}) y {curr['date']} ({curr_mentions})"
                    ),
                })

        spikes.sort(key=lambda x: x["pct_change"], reverse=True)
        logger.info("Detected %d spikes (threshold=%.0f%%)", len(spikes), threshold_pct)
        return spikes

    # ------------------------------------------------------------------
    # 8. Brand criticism categorization
    # ------------------------------------------------------------------

    def categorize_brand_criticism(
        self,
        negative_toward_brand: Optional[pd.DataFrame] = None,
        brand_name: str = "",
    ) -> Dict[str, Any]:
        """Categorize negative mentions directed at the brand.

        Spec rule 2: Separate direction of sentiment. 'Negative + brand mentioned'
        is NOT the same as 'negative TOWARD the brand'.

        Uses keyword-based categorization (no AI) to bucket criticism types.

        Args:
            negative_toward_brand: Subset of negative mentions directed at brand.
                If None, filters self.df for negative sentiment.
            brand_name: Brand name for relevance filtering.

        Returns:
            {
                "total_negative_brand": int,
                "categories": [
                    {"category": str, "count": int, "pct": float,
                     "sample_texts": [str]}
                ],
                "severity_distribution": {"high": int, "medium": int, "low": int}
            }
        """
        if negative_toward_brand is not None:
            neg_df = negative_toward_brand.copy()
        else:
            if "sentiment" not in self.df.columns:
                return {"total_negative_brand": 0, "categories": [], "severity_distribution": {}}
            neg_mask = self.df["sentiment"].astype(str).str.lower().isin(["negative", "negativo"])
            neg_df = self.df[neg_mask].copy()

        total = len(neg_df)
        if total == 0:
            return {"total_negative_brand": 0, "categories": [], "severity_distribution": {}}

        # Keyword-based categories for brand criticism
        category_keywords = {
            "servicio_al_cliente": [
                "servicio", "atención", "atencion", "cliente", "respuesta",
                "soporte", "ayuda", "reclamo", "queja", "espera",
            ],
            "producto_calidad": [
                "calidad", "producto", "funciona", "roto", "defecto",
                "malo", "peor", "terrible", "pésimo", "basura",
            ],
            "precio_valor": [
                "precio", "caro", "costoso", "valor", "dinero", "cobro",
                "estafa", "robo", "tarifa", "costo",
            ],
            "experiencia_usuario": [
                "experiencia", "app", "plataforma", "página", "pagina",
                "web", "sistema", "proceso", "complicado", "difícil",
            ],
            "reputacion_confianza": [
                "confianza", "reputación", "reputacion", "credibilidad",
                "mentira", "engaño", "fraude", "irresponsable", "vergüenza",
            ],
            "operacional": [
                "demora", "retraso", "cancelación", "cancelacion", "vuelo",
                "equipaje", "maleta", "perdido", "aeropuerto", "operación",
            ],
            "comunicacion": [
                "comunicado", "información", "informacion", "transparencia",
                "silencio", "responde", "explicación", "explicacion",
            ],
        }

        import re as _re

        # Classify each mention
        category_counts: Counter = Counter()
        category_samples: Dict[str, List[str]] = {cat: [] for cat in category_keywords}
        uncategorized = 0

        if "text" in neg_df.columns:
            for _, row in neg_df.iterrows():
                text = str(row.get("text", "")).lower()
                matched = False
                for cat, keywords in category_keywords.items():
                    if any(_re.search(r"\b" + _re.escape(kw) + r"\b", text) for kw in keywords):
                        category_counts[cat] += 1
                        if len(category_samples[cat]) < 3:
                            category_samples[cat].append(str(row.get("text", ""))[:200])
                        matched = True
                        break  # First match wins
                if not matched:
                    uncategorized += 1

        if uncategorized > 0:
            category_counts["otros"] = uncategorized

        categories = []
        for cat, count in category_counts.most_common():
            categories.append({
                "category": cat,
                "count": count,
                "pct": self._safe_div(count, total),
                "sample_texts": category_samples.get(cat, []),
            })

        # Severity distribution based on engagement
        severity = {"high": 0, "medium": 0, "low": 0}
        if "engagement" in neg_df.columns:
            for eng_val in neg_df["engagement"].fillna(0):
                if eng_val >= 1000:
                    severity["high"] += 1
                elif eng_val >= 100:
                    severity["medium"] += 1
                else:
                    severity["low"] += 1
        else:
            severity["low"] = total

        logger.info(
            "Brand criticism: %d negative mentions, %d categories",
            total, len(categories),
        )

        return {
            "total_negative_brand": total,
            "categories": categories,
            "severity_distribution": severity,
        }

    # ------------------------------------------------------------------
    # Legacy-compatible methods (used by existing pipeline)
    # ------------------------------------------------------------------

    def calculate_base_metrics(self) -> Dict[str, Any]:
        """Equivalent to the old calculate_metrics() function."""
        df = self.df
        metrics: Dict[str, Any] = {}

        metrics["total_mentions"] = len(df)

        # Sentiment breakdown
        if "sentiment" in df.columns:
            sent_series = df["sentiment"].dropna()
            sent_series = sent_series[sent_series.astype(str).str.strip() != ""]
            sentiment_counts = sent_series.value_counts().to_dict()
            total_with_sentiment = len(sent_series)
            metrics["sentiment_breakdown"] = {
                str(k): {
                    "count": int(v),
                    "percentage": self._safe_div(v, total_with_sentiment),
                }
                for k, v in sentiment_counts.items()
            }
        else:
            metrics["sentiment_breakdown"] = {}

        # Volume by date
        if "date" in df.columns:
            date_series = df["date"].dropna()
            if not date_series.empty:
                volume = date_series.dt.date.value_counts().sort_index().to_dict()
                metrics["volume_by_date"] = {str(k): int(v) for k, v in volume.items()}
            else:
                metrics["volume_by_date"] = {}
        else:
            metrics["volume_by_date"] = {}

        # Top sources
        pcol = "platform" if "platform" in df.columns else "source"
        if pcol in df.columns:
            metrics["top_sources"] = [
                (str(s), int(c)) for s, c in df[pcol].dropna().value_counts().head(10).items()
            ]
        else:
            metrics["top_sources"] = []

        # Top authors
        if "author" in df.columns:
            metrics["top_authors"] = [
                (str(a), int(c)) for a, c in df["author"].dropna().value_counts().head(10).items()
            ]
        else:
            metrics["top_authors"] = []

        # Top topics
        if "topic" in df.columns:
            metrics["top_topics"] = [
                (str(t), int(c)) for t, c in df["topic"].dropna().value_counts().head(10).items()
            ]
        else:
            metrics["top_topics"] = []

        # Actor breakdown
        if "actor" in df.columns:
            metrics["actor_breakdown"] = {str(k): int(v) for k, v in df["actor"].value_counts().to_dict().items()}
        else:
            metrics["actor_breakdown"] = {}

        # Reach and engagement averages
        if "reach" in df.columns:
            rv = df["reach"].dropna()
            metrics["avg_reach"] = round(float(rv.mean()), 2) if not rv.empty else 0.0
        else:
            metrics["avg_reach"] = None

        if "engagement" in df.columns:
            ev = df["engagement"].dropna()
            metrics["avg_engagement"] = round(float(ev.mean()), 2) if not ev.empty else 0.0
        else:
            metrics["avg_engagement"] = None

        for col in ("likes", "comments", "shares"):
            if col in df.columns:
                metrics[f"total_{col}"] = int(df[col].fillna(0).sum())

        logger.info("Base metrics: %d total mentions", metrics["total_mentions"])
        return metrics

    def calculate_all(
        self,
        concepts: Optional[List[str]] = None,
        event_date: Optional[str] = None,
        brand_name: str = "",
    ) -> Dict[str, Any]:
        """Run all calculations and return unified metrics dict.

        This is the main entry point for the new pipeline.
        """
        metrics = self.calculate_base_metrics()

        # Engagement by platform
        metrics["engagement_by_platform"] = self.compute_engagement_by_platform()

        # Timeline
        timeline = self.compute_timeline()
        metrics["timeline"] = timeline

        # Spikes
        metrics["spikes"] = self.detect_spikes(daily_data=timeline.get("daily"))

        # Deduplicated reach
        metrics["reach_deduplicated"] = self.compute_reach_deduplicated()

        # Co-occurrence (needs concepts from topic detection or config)
        if concepts:
            metrics["cooccurrence"] = self.compute_cooccurrence(concepts)

        # Comunicado impact (if event date provided)
        if event_date:
            metrics["comunicado_impact"] = self.compute_comunicado_impact(event_date)

        # Tangential analysis
        metrics["tangential_analysis"] = self.compute_tangential_analysis()

        # Brand criticism categorization
        metrics["brand_criticism"] = self.categorize_brand_criticism(brand_name=brand_name)

        return metrics


# ======================================================================
# Legacy compatibility functions — delegates to MetricsCalculator
# ======================================================================

def calculate_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    """Calculate key metrics from the cleaned DataFrame.

    Legacy wrapper — delegates to MetricsCalculator.calculate_base_metrics().
    """
    calc = MetricsCalculator(df)
    return calc.calculate_base_metrics()


def detect_anomalies(df: pd.DataFrame, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect anomalies in the data based on volume, sentiment, and sources."""
    anomalies: List[Dict[str, Any]] = []

    # --- Volume spikes (>50% day-over-day increase) ---
    volume_by_date = metrics.get("volume_by_date", {})
    if len(volume_by_date) >= 2:
        sorted_dates = sorted(volume_by_date.items())
        for i in range(1, len(sorted_dates)):
            prev_date, prev_count = sorted_dates[i - 1]
            curr_date, curr_count = sorted_dates[i]
            if prev_count > 0:
                pct_change = (curr_count - prev_count) / prev_count * 100
                if pct_change > 50:
                    severity = "critical" if pct_change > 100 else "warning"
                    anomalies.append({
                        "type": "volume_spike",
                        "description": (
                            f"Incremento de volumen del {pct_change:.0f}% entre "
                            f"{prev_date} ({prev_count}) y {curr_date} ({curr_count})"
                        ),
                        "severity": severity,
                        "data": {
                            "date": curr_date,
                            "previous_count": prev_count,
                            "current_count": curr_count,
                            "pct_change": round(pct_change, 1),
                        },
                    })

    # --- Sentiment shifts ---
    if "sentiment" in df.columns and "date" in df.columns:
        df_with_date = df.dropna(subset=["date"]).copy()
        sent_valid = df_with_date["sentiment"].dropna()
        sent_valid = sent_valid[sent_valid.astype(str).str.strip() != ""]

        if len(sent_valid) > 10:
            df_sent = df_with_date.loc[sent_valid.index].copy()
            df_sent["date_only"] = df_sent["date"].dt.date
            dates_sorted = sorted(df_sent["date_only"].unique())

            if len(dates_sorted) >= 2:
                mid = len(dates_sorted) // 2
                first_half_dates = set(dates_sorted[:mid])
                second_half_dates = set(dates_sorted[mid:])

                first_half = df_sent[df_sent["date_only"].isin(first_half_dates)]
                second_half = df_sent[df_sent["date_only"].isin(second_half_dates)]

                for sentiment_val in ("negative", "negativo"):
                    neg_first = (first_half["sentiment"] == sentiment_val).sum()
                    neg_second = (second_half["sentiment"] == sentiment_val).sum()
                    total_first = len(first_half)
                    total_second = len(second_half)

                    if total_first > 0 and total_second > 0:
                        pct_first = neg_first / total_first * 100
                        pct_second = neg_second / total_second * 100
                        diff = pct_second - pct_first

                        if abs(diff) > 10:
                            direction = "aumento" if diff > 0 else "disminucion"
                            severity = "critical" if abs(diff) > 25 else "warning"
                            anomalies.append({
                                "type": "sentiment_shift",
                                "description": (
                                    f"Cambio de sentimiento negativo: {direction} de "
                                    f"{pct_first:.1f}% a {pct_second:.1f}% entre la primera "
                                    f"y segunda mitad del periodo"
                                ),
                                "severity": severity,
                                "data": {
                                    "negative_pct_first_half": round(pct_first, 1),
                                    "negative_pct_second_half": round(pct_second, 1),
                                    "shift": round(diff, 1),
                                },
                            })
                            break

    # --- Source/platform concentration ---
    top_sources = metrics.get("top_sources", [])
    total = metrics.get("total_mentions", 0)
    if top_sources and total > 0:
        top_source_name, top_source_count = top_sources[0]
        concentration = top_source_count / total * 100
        if concentration > 60:
            severity = "critical" if concentration > 80 else "warning"
            anomalies.append({
                "type": "source_concentration",
                "description": (
                    f"Alta concentracion en una fuente: '{top_source_name}' representa "
                    f"el {concentration:.1f}% del total de menciones"
                ),
                "severity": severity,
                "data": {
                    "source": top_source_name,
                    "count": top_source_count,
                    "concentration_pct": round(concentration, 1),
                },
            })

    logger.info("Detected %d anomalies", len(anomalies))
    return anomalies


def calculate_actor_metrics(df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    """Calculate metrics separated by actor. Legacy wrapper."""
    result: Dict[str, Dict[str, Any]] = {}

    combined_metrics = calculate_metrics(df)
    combined_anomalies = detect_anomalies(df, combined_metrics)
    combined_metrics["anomalies"] = combined_anomalies
    result["combined"] = combined_metrics

    if "actor" not in df.columns:
        logger.info("No 'actor' column — skipping actor-separated metrics")
        return result

    # Normalize for filtering
    df_norm = df.copy()
    unknown = {"unknown", "<na>", "nan", "n/a", "none", ""}
    df_norm["actor"] = df_norm["actor"].astype(str).str.strip().str.lower()
    df_norm.loc[df_norm["actor"].isin(unknown), "actor"] = "otros"

    actor_names = [a for a in df_norm["actor"].unique() if a != "otros"]
    actor_names.sort(key=lambda a: len(df_norm[df_norm["actor"] == a]), reverse=True)

    for actor_name in actor_names[:5]:
        actor_df = df_norm[df_norm["actor"] == actor_name]
        if actor_df.empty:
            result[actor_name] = {"total_mentions": 0, "anomalies": []}
            continue

        actor_metrics = calculate_metrics(actor_df)
        actor_anomalies = detect_anomalies(actor_df, actor_metrics)
        actor_metrics["anomalies"] = actor_anomalies
        result[actor_name] = actor_metrics

        logger.info(
            "Actor '%s': %d mentions, sentiment: %s",
            actor_name,
            actor_metrics["total_mentions"],
            {k: v.get("percentage", 0) if isinstance(v, dict) else v
             for k, v in actor_metrics.get("sentiment_breakdown", {}).items()},
        )

    return result


def calculate_intersection_metrics(
    df: pd.DataFrame,
    brand_name: str = "avianca",
    actor_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Calculate intersection metrics: brand_only, actor_only, intersection. Legacy wrapper."""
    if actor_names is None:
        actor_names = ["cossio", "yeferson"]

    if "text" not in df.columns:
        return {"brand_only": 0, "actor_only": 0, "intersection": 0, "neither": 0, "total": 0}

    import re as _re
    brand_pattern = _re.compile(brand_name, _re.IGNORECASE)
    actor_pattern = _re.compile("|".join(actor_names), _re.IGNORECASE)

    text_col = df["text"].astype(str)
    has_brand = text_col.apply(lambda t: bool(brand_pattern.search(t)))
    has_actor = text_col.apply(lambda t: bool(actor_pattern.search(t)))

    intersection = int((has_brand & has_actor).sum())
    brand_only = int((has_brand & ~has_actor).sum())
    actor_only = int((~has_brand & has_actor).sum())
    neither = int((~has_brand & ~has_actor).sum())
    total = len(df)

    def _bucket_sentiment(mask):
        bucket = df[mask]
        if bucket.empty or "sentiment" not in bucket.columns:
            return {}
        counts = bucket["sentiment"].value_counts()
        n = len(bucket)
        return {str(k): round(v / n * 100, 1) for k, v in counts.items()}

    result = {
        "brand_only": brand_only,
        "brand_only_pct": round(brand_only / max(total, 1) * 100, 1),
        "brand_only_sentiment": _bucket_sentiment(has_brand & ~has_actor),
        "actor_only": actor_only,
        "actor_only_pct": round(actor_only / max(total, 1) * 100, 1),
        "actor_only_sentiment": _bucket_sentiment(~has_brand & has_actor),
        "intersection": intersection,
        "intersection_pct": round(intersection / max(total, 1) * 100, 1),
        "intersection_sentiment": _bucket_sentiment(has_brand & has_actor),
        "neither": neither,
        "neither_pct": round(neither / max(total, 1) * 100, 1),
        "total": total,
        "brand_label": brand_name.capitalize(),
        "actor_label": actor_names[0].capitalize() if actor_names else "Actor",
    }

    logger.info(
        "Intersection: brand_only=%d (%.1f%%), actor_only=%d (%.1f%%), "
        "intersection=%d (%.1f%%), neither=%d (%.1f%%)",
        brand_only, result["brand_only_pct"],
        actor_only, result["actor_only_pct"],
        intersection, result["intersection_pct"],
        neither, result["neither_pct"],
    )
    return result
