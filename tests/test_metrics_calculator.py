"""Tests for the MetricsCalculator class (8 spec methods).

Run with: python -m pytest tests/test_metrics_calculator.py -v
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import pytest

from agents.report_builder.metrics import MetricsCalculator


@pytest.fixture
def sample_df():
    """Realistic DataFrame simulating merged social intelligence data."""
    dates = (
        ["2026-03-01"] * 20
        + ["2026-03-02"] * 10
        + ["2026-03-03"] * 50  # spike day
        + ["2026-03-04"] * 15
        + ["2026-03-05"] * 5
    )
    n = len(dates)

    texts = []
    sentiments = []
    platforms = []
    authors = []
    actors = []

    for i in range(n):
        if i % 5 == 0:
            texts.append("Avianca tiene un servicio terrible, el peor vuelo de mi vida")
            sentiments.append("negativo")
        elif i % 5 == 1:
            texts.append("Cossio tiene razón sobre Avianca, el equipaje fue un desastre")
            sentiments.append("negativo")
        elif i % 5 == 2:
            texts.append("Me encanta volar con Avianca, excelente experiencia")
            sentiments.append("positivo")
        elif i % 5 == 3:
            texts.append("Según medios, la crisis del sector aéreo afecta a todos")
            sentiments.append("neutral")
        else:
            texts.append("Cossio publicó un video viral criticando a Avianca")
            sentiments.append("negativo")

        platforms.append(["Twitter", "Instagram", "Facebook", "TikTok", "YouTube"][i % 5])
        authors.append(f"@user_{i % 25}")  # 25 unique authors
        actors.append(["avianca", "cossio", "avianca", "otros", "cossio"][i % 5])

    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "text": texts,
        "sentiment": sentiments,
        "platform": platforms,
        "author": authors,
        "actor": actors,
        "engagement": [100 + i * 10 for i in range(n)],
        "likes": [50 + i * 5 for i in range(n)],
        "comments": [10 + i for i in range(n)],
        "shares": [5 + i for i in range(n)],
        "reach": [(i % 25 + 1) * 10000 for i in range(n)],  # Follower-based reach
    })


@pytest.fixture
def calc(sample_df):
    return MetricsCalculator(sample_df)


# ------------------------------------------------------------------
# 1. compute_cooccurrence
# ------------------------------------------------------------------

class TestComputeCooccurrence:
    def test_basic_cooccurrence(self, calc):
        result = calc.compute_cooccurrence(["avianca", "cossio", "servicio", "equipaje"])
        assert "nodes" in result
        assert "edges" in result
        assert result["total_mentions_analyzed"] == 100

        node_ids = {n["id"] for n in result["nodes"]}
        assert "avianca" in node_ids
        assert "cossio" in node_ids

    def test_nodes_have_sentiment(self, calc):
        result = calc.compute_cooccurrence(["avianca", "servicio"])
        for node in result["nodes"]:
            if node["mentions"] > 0:
                assert "sentiment_pct" in node

    def test_edge_weight_minimum(self, calc):
        result = calc.compute_cooccurrence(
            ["avianca", "cossio", "servicio"], min_cooccurrence=5,
        )
        for edge in result["edges"]:
            assert edge["weight"] >= 5

    def test_empty_concepts(self, calc):
        result = calc.compute_cooccurrence([])
        assert result["nodes"] == []
        assert result["edges"] == []

    def test_no_text_column(self):
        df = pd.DataFrame({"sentiment": ["positive"]})
        calc = MetricsCalculator(df)
        result = calc.compute_cooccurrence(["test"])
        assert result["total_mentions_analyzed"] == 0


# ------------------------------------------------------------------
# 2. compute_engagement_by_platform
# ------------------------------------------------------------------

class TestComputeEngagementByPlatform:
    def test_returns_all_platforms(self, calc):
        result = calc.compute_engagement_by_platform()
        platform_names = {r["platform"] for r in result}
        assert "Twitter" in platform_names
        assert "Instagram" in platform_names
        assert len(result) == 5  # 5 platforms in fixture

    def test_engagement_share_sums_to_100(self, calc):
        result = calc.compute_engagement_by_platform()
        total_share = sum(r["engagement_share"] for r in result)
        assert abs(total_share - 100.0) < 1.0  # rounding tolerance

    def test_has_required_fields(self, calc):
        result = calc.compute_engagement_by_platform()
        required = {
            "platform", "mentions", "total_engagement", "avg_engagement",
            "engagement_share", "total_likes", "total_comments", "total_shares",
            "total_reach", "avg_reach", "reach_share",
        }
        for entry in result:
            assert required.issubset(entry.keys()), f"Missing fields: {required - entry.keys()}"

    def test_sorted_by_engagement(self, calc):
        result = calc.compute_engagement_by_platform()
        engagements = [r["total_engagement"] for r in result]
        assert engagements == sorted(engagements, reverse=True)

    def test_sentiment_per_platform(self, calc):
        result = calc.compute_engagement_by_platform()
        for entry in result:
            assert "sentiment_breakdown" in entry


# ------------------------------------------------------------------
# 3. compute_timeline
# ------------------------------------------------------------------

class TestComputeTimeline:
    def test_daily_data(self, calc):
        result = calc.compute_timeline()
        assert len(result["daily"]) == 5  # 5 distinct days
        assert result["period_start"] == "2026-03-01"
        assert result["period_end"] == "2026-03-05"
        assert result["total_days"] == 5

    def test_spike_day_has_most_mentions(self, calc):
        result = calc.compute_timeline()
        march_3 = next(d for d in result["daily"] if d["date"] == "2026-03-03")
        assert march_3["mentions"] == 50

    def test_daily_has_sentiment(self, calc):
        result = calc.compute_timeline()
        for day in result["daily"]:
            assert "sentiment" in day
            assert isinstance(day["sentiment"], dict)

    def test_daily_has_engagement(self, calc):
        result = calc.compute_timeline()
        for day in result["daily"]:
            assert "engagement" in day
            assert day["engagement"] > 0

    def test_no_date_column(self):
        df = pd.DataFrame({"text": ["hello"], "sentiment": ["positive"]})
        calc = MetricsCalculator(df)
        result = calc.compute_timeline()
        assert result["daily"] == []
        assert result["total_days"] == 0


# ------------------------------------------------------------------
# 4. compute_comunicado_impact
# ------------------------------------------------------------------

class TestComputeComunicadoImpact:
    def test_pre_post_split(self, calc):
        result = calc.compute_comunicado_impact("2026-03-03", window_days=2)
        assert result["event_date"] == "2026-03-03"
        assert result["pre"]["mentions"] > 0
        assert result["post"]["mentions"] > 0

    def test_delta_calculated(self, calc):
        result = calc.compute_comunicado_impact("2026-03-03", window_days=3)
        assert "mentions_pct" in result["delta"]
        assert "engagement_pct" in result["delta"]
        assert "negative_shift" in result["delta"]

    def test_peak_day(self, calc):
        result = calc.compute_comunicado_impact("2026-03-03", window_days=3)
        assert result["peak_day"]["date"] is not None
        assert result["peak_day"]["mentions"] > 0

    def test_pre_has_sentiment(self, calc):
        result = calc.compute_comunicado_impact("2026-03-03")
        assert "sentiment" in result["pre"]
        assert "sentiment" in result["post"]


# ------------------------------------------------------------------
# 5. compute_tangential_analysis
# ------------------------------------------------------------------

class TestComputeTangentialAnalysis:
    def test_with_tangential_df(self, sample_df):
        tang_df = sample_df.head(20).copy()
        tang_df["sentiment"] = "negativo"
        calc = MetricsCalculator(sample_df)
        result = calc.compute_tangential_analysis(tangential_mentions=tang_df)

        assert result["total_tangential"] == 20
        assert result["negative_tangential"] == 20
        assert result["negative_tangential_pct"] == 100.0
        assert result["catalyst_detected"] is True
        assert result["catalyst_strength"] == "high"

    def test_no_catalyst(self, sample_df):
        tang_df = sample_df.head(10).copy()
        tang_df["sentiment"] = "positivo"
        calc = MetricsCalculator(sample_df)
        result = calc.compute_tangential_analysis(tangential_mentions=tang_df)

        assert result["catalyst_detected"] is False
        assert result["catalyst_strength"] == "none"

    def test_top_themes_extracted(self, sample_df):
        tang_df = sample_df.head(30).copy()
        calc = MetricsCalculator(sample_df)
        result = calc.compute_tangential_analysis(tangential_mentions=tang_df)

        assert isinstance(result["top_themes"], list)
        if result["top_themes"]:
            assert "theme" in result["top_themes"][0]
            assert "count" in result["top_themes"][0]

    def test_empty_tangential(self):
        df = pd.DataFrame({"text": ["hello"], "sentiment": ["positive"]})
        calc = MetricsCalculator(df)
        result = calc.compute_tangential_analysis(tangential_mentions=pd.DataFrame())
        assert result["total_tangential"] == 0
        assert result["catalyst_detected"] is False


# ------------------------------------------------------------------
# 6. compute_reach_deduplicated
# ------------------------------------------------------------------

class TestComputeReachDeduplicated:
    def test_deduplication_reduces_reach(self, calc):
        result = calc.compute_reach_deduplicated()
        assert result["total_reach_deduplicated"] <= result["total_reach_raw"]
        assert result["inflation_factor"] >= 1.0

    def test_unique_accounts(self, calc):
        result = calc.compute_reach_deduplicated()
        assert result["unique_accounts"] == 25  # 25 unique @user_N

    def test_reach_by_platform(self, calc):
        result = calc.compute_reach_deduplicated()
        assert len(result["reach_by_platform"]) > 0
        for plat in result["reach_by_platform"]:
            assert "platform" in plat
            assert "reach_deduplicated" in plat
            assert "unique_accounts" in plat

    def test_top_accounts(self, calc):
        result = calc.compute_reach_deduplicated()
        assert len(result["top_accounts"]) > 0
        assert len(result["top_accounts"]) <= 15
        for acc in result["top_accounts"]:
            assert "author" in acc
            assert "reach" in acc
            assert "reach_formatted" in acc

    def test_formatted_numbers(self, calc):
        result = calc.compute_reach_deduplicated()
        assert "total_reach_formatted" in result
        # Should be a string like "3.2M" or "250K"
        assert isinstance(result["total_reach_formatted"], str)


# ------------------------------------------------------------------
# 7. detect_spikes
# ------------------------------------------------------------------

class TestDetectSpikes:
    def test_detects_march_3_spike(self, calc):
        timeline = calc.compute_timeline()
        spikes = calc.detect_spikes(daily_data=timeline["daily"])

        # March 3 has 50 mentions vs March 2 with 10 = 400% increase
        spike_dates = [s["date"] for s in spikes]
        assert "2026-03-03" in spike_dates

    def test_spike_severity(self, calc):
        timeline = calc.compute_timeline()
        spikes = calc.detect_spikes(daily_data=timeline["daily"])

        march_3 = next(s for s in spikes if s["date"] == "2026-03-03")
        assert march_3["severity"] == "critical"  # 400% > 100%
        assert march_3["pct_change"] == 400.0

    def test_spike_has_required_fields(self, calc):
        timeline = calc.compute_timeline()
        spikes = calc.detect_spikes(daily_data=timeline["daily"])
        required = {"date", "mentions", "previous_mentions", "pct_change", "severity", "description"}
        for spike in spikes:
            assert required.issubset(spike.keys())

    def test_custom_threshold(self, calc):
        timeline = calc.compute_timeline()
        spikes_low = calc.detect_spikes(daily_data=timeline["daily"], threshold_pct=10.0)
        spikes_high = calc.detect_spikes(daily_data=timeline["daily"], threshold_pct=200.0)
        assert len(spikes_low) >= len(spikes_high)

    def test_auto_computes_timeline(self, calc):
        spikes = calc.detect_spikes()
        assert isinstance(spikes, list)
        assert len(spikes) > 0


# ------------------------------------------------------------------
# 8. categorize_brand_criticism
# ------------------------------------------------------------------

class TestCategorizeBrandCriticism:
    def test_categorizes_service_issues(self):
        df = pd.DataFrame({
            "text": [
                "El servicio al cliente de Avianca es terrible",
                "La atención fue pésima, nunca más",
                "El precio del vuelo es un robo",
                "La app no funciona, experiencia horrible",
                "Qué vergüenza de empresa irresponsable",
            ],
            "sentiment": ["negativo"] * 5,
            "engagement": [500, 1200, 50, 200, 3000],
        })
        calc = MetricsCalculator(df)
        result = calc.categorize_brand_criticism()

        assert result["total_negative_brand"] == 5
        cats = {c["category"] for c in result["categories"]}
        assert "servicio_al_cliente" in cats

    def test_severity_distribution(self):
        df = pd.DataFrame({
            "text": ["queja " * 10] * 10,
            "sentiment": ["negativo"] * 10,
            "engagement": [50, 150, 1500, 20, 300, 2000, 10, 100, 500, 5000],
        })
        calc = MetricsCalculator(df)
        result = calc.categorize_brand_criticism()

        sev = result["severity_distribution"]
        assert sev["high"] > 0  # engagement >= 1000
        assert sev["medium"] > 0  # 100 <= engagement < 1000
        assert sev["low"] > 0  # engagement < 100

    def test_sample_texts_capped(self):
        df = pd.DataFrame({
            "text": ["servicio malo"] * 20,
            "sentiment": ["negativo"] * 20,
            "engagement": [10] * 20,
        })
        calc = MetricsCalculator(df)
        result = calc.categorize_brand_criticism()

        for cat in result["categories"]:
            assert len(cat["sample_texts"]) <= 3

    def test_empty_negative(self):
        df = pd.DataFrame({
            "text": ["todo bien"],
            "sentiment": ["positivo"],
            "engagement": [10],
        })
        calc = MetricsCalculator(df)
        result = calc.categorize_brand_criticism()
        assert result["total_negative_brand"] == 0
        assert result["categories"] == []


# ------------------------------------------------------------------
# Integration: calculate_all
# ------------------------------------------------------------------

class TestCalculateAll:
    def test_returns_all_keys(self, calc):
        result = calc.calculate_all(
            concepts=["avianca", "cossio", "servicio"],
            event_date="2026-03-03",
            brand_name="avianca",
        )

        expected_keys = {
            "total_mentions", "sentiment_breakdown", "volume_by_date",
            "engagement_by_platform", "timeline", "spikes",
            "reach_deduplicated", "cooccurrence", "comunicado_impact",
            "tangential_analysis", "brand_criticism",
        }
        assert expected_keys.issubset(result.keys()), f"Missing: {expected_keys - result.keys()}"

    def test_without_optional_params(self, calc):
        result = calc.calculate_all()
        assert "cooccurrence" not in result  # no concepts provided
        assert "comunicado_impact" not in result  # no event_date
        assert "engagement_by_platform" in result
        assert "spikes" in result


# ------------------------------------------------------------------
# Legacy compatibility
# ------------------------------------------------------------------

class TestLegacyCompat:
    def test_calculate_metrics_function(self, sample_df):
        from agents.report_builder.metrics import calculate_metrics
        result = calculate_metrics(sample_df)
        assert result["total_mentions"] == 100
        assert "sentiment_breakdown" in result

    def test_detect_anomalies_function(self, sample_df):
        from agents.report_builder.metrics import calculate_metrics, detect_anomalies
        metrics = calculate_metrics(sample_df)
        anomalies = detect_anomalies(sample_df, metrics)
        assert isinstance(anomalies, list)

    def test_calculate_actor_metrics_function(self, sample_df):
        from agents.report_builder.metrics import calculate_actor_metrics
        result = calculate_actor_metrics(sample_df)
        assert "combined" in result

    def test_calculate_intersection_metrics_function(self, sample_df):
        from agents.report_builder.metrics import calculate_intersection_metrics
        result = calculate_intersection_metrics(sample_df, "avianca", ["cossio"])
        assert result["total"] == 100


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

class TestFormatBigNumber:
    def test_thousands(self):
        assert MetricsCalculator._format_big_number(692000) == "692K"
        assert MetricsCalculator._format_big_number(5400) == "5.4K"

    def test_millions(self):
        assert MetricsCalculator._format_big_number(29000000) == "29M"
        assert MetricsCalculator._format_big_number(1500000) == "1.5M"

    def test_billions(self):
        assert MetricsCalculator._format_big_number(2300000000) == "2.3B"

    def test_small_numbers(self):
        assert MetricsCalculator._format_big_number(500) == "500"
        assert MetricsCalculator._format_big_number(0) == "0"
