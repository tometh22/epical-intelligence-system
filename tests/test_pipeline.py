"""Basic test suite for the Report Builder pipeline.

Run with: python -m pytest tests/ -v
Or: python tests/test_pipeline.py
"""

import sys
from pathlib import Path

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd


def test_parser():
    """Test CSV/Excel parsing."""
    from agents.report_builder.parser import parse_export, clean_data
    from agents.report_builder.config import load_column_mapping, resolve_columns

    csv_path = PROJECT_ROOT / "inputs" / "test_data.csv"
    if not csv_path.exists():
        print("SKIP: test_data.csv not found")
        return

    df = parse_export(csv_path)
    assert len(df) > 0, "Parser returned empty DataFrame"
    assert "text" in df.columns or "Text" in df.columns or "Texto" in df.columns

    mapping = load_column_mapping("test")
    col_map = resolve_columns(df, mapping)
    df_clean, issues = clean_data(df, col_map)
    assert len(df_clean) > 0, "Clean data returned empty DataFrame"
    print(f"  PASS: parsed {len(df)} rows, cleaned to {len(df_clean)}, {len(issues)} issues")


def test_metrics():
    """Test metrics calculation."""
    from agents.report_builder.metrics import calculate_metrics, detect_anomalies

    df = pd.DataFrame({
        "date": pd.to_datetime(["2026-03-01", "2026-03-01", "2026-03-02", "2026-03-02", "2026-03-03"]),
        "text": ["good", "bad", "neutral", "great", "terrible"],
        "sentiment": ["positive", "negative", "neutral", "positive", "negative"],
        "platform": ["Twitter", "Instagram", "Twitter", "Facebook", "Twitter"],
        "engagement": [100, 50, 30, 200, 10],
        "likes": [80, 40, 20, 150, 5],
        "comments": [10, 5, 5, 30, 3],
        "shares": [10, 5, 5, 20, 2],
        "actor": ["avianca", "cossio", "unknown", "avianca", "cossio"],
    })

    metrics = calculate_metrics(df)
    assert metrics["total_mentions"] == 5
    assert "sentiment_breakdown" in metrics
    assert len(metrics["top_sources"]) > 0
    assert metrics.get("actor_breakdown", {}).get("avianca") == 2

    anomalies = detect_anomalies(df, metrics)
    assert isinstance(anomalies, list)
    print(f"  PASS: {metrics['total_mentions']} mentions, {len(anomalies)} anomalies")


def test_intersection_metrics():
    """Test Venn intersection calculation."""
    from agents.report_builder.metrics import calculate_intersection_metrics

    df = pd.DataFrame({
        "text": [
            "Avianca es genial",
            "Cossio tiene razón",
            "Avianca y Cossio en conflicto",
            "El clima está lindo",
        ],
        "actor": ["avianca", "cossio", "avianca", "unknown"],
        "sentiment": ["positive", "negative", "negative", "neutral"],
    })

    result = calculate_intersection_metrics(df, brand_name="avianca", actor_names=["cossio"])
    assert result["brand_only"] == 1  # "Avianca es genial"
    assert result["actor_only"] == 1  # "Cossio tiene razón"
    assert result["intersection"] == 1  # "Avianca y Cossio"
    assert result["neither"] == 1  # "El clima"
    print(f"  PASS: brand_only={result['brand_only']}, intersection={result['intersection']}")


def test_sentiment_classifier_rules():
    """Test rule-based sentiment classification."""
    from agents.report_builder.sentiment_classifier import reclassify_sentiment

    df = pd.DataFrame({
        "text": [
            "Excelente servicio, perfecto todo",
            "Terrible experiencia, pésimo",
            "Según informó el comunicado oficial",
            "Un día más",
        ],
        "sentiment": [pd.NA, pd.NA, pd.NA, pd.NA],
        "engagement": [10, 20, 5, 1],
    })

    df_out, stats = reclassify_sentiment(df, use_ai=False)
    assert stats["rules"] >= 2, f"Expected >=2 rules classified, got {stats['rules']}"
    assert df_out.at[0, "sentiment"] == "positivo"
    assert df_out.at[1, "sentiment"] == "negativo"
    print(f"  PASS: {stats['rules']} classified by rules")


def test_topics():
    """Test topic clustering."""
    from agents.report_builder.topics import detect_topic_clusters

    texts = []
    for _ in range(10):
        texts.append("servicio al cliente muy malo")
        texts.append("el nuevo producto es increíble")
        texts.append("la campaña publicitaria funciona")

    df = pd.DataFrame({"text": texts})
    clusters = detect_topic_clusters(df, max_topics=3)
    assert len(clusters) > 0, "No clusters detected"
    assert clusters[0]["mention_count"] > 0
    print(f"  PASS: {len(clusters)} clusters, top: '{clusters[0]['label']}' ({clusters[0]['mention_count']})")


def test_sampler():
    """Test sampling."""
    from agents.report_builder.sampler import build_relevance_sample

    df = pd.DataFrame({
        "text": [f"mention {i}" for i in range(200)],
        "date": pd.to_datetime("2026-03-01"),
        "platform": "Twitter",
        "sentiment": ["positive"] * 100 + ["negative"] * 100,
        "engagement": list(range(200)),
        "likes": list(range(200)),
        "comments": [0] * 200,
        "shares": [0] * 200,
        "data_source": "youscan",
        "actor": "unknown",
    })

    sample, comp = build_relevance_sample(df, {"total_mentions": 200})
    assert len(sample) <= 150, f"Sample exceeds cap: {len(sample)}"
    assert len(sample) > 0
    print(f"  PASS: sample size={len(sample)}, comp='{comp[:60]}...'")


def test_config_loading():
    """Test report_config.json auto-loading."""
    from agents.report_builder.main import _load_report_config

    cfg = _load_report_config()
    assert isinstance(cfg, dict)
    if cfg:
        print(f"  PASS: loaded config with {len(cfg)} keys: {list(cfg.keys())}")
    else:
        print("  PASS: empty config (file may not exist)")


def test_html_builder_basic():
    """Test HTML generation with minimal data."""
    from agents.report_builder.html_builder import build_report_html
    import tempfile, os

    metrics = {
        "total_mentions": 100,
        "sentiment_breakdown": {"positivo": {"count": 60, "percentage": 60.0}, "negativo": {"count": 40, "percentage": 40.0}},
        "volume_by_date": {"2026-03-01": 50, "2026-03-02": 50},
        "top_sources": [["Twitter", 60], ["Instagram", 40]],
        "top_authors": [["@user1", 30]],
        "actor_breakdown": {"brand": 60, "actor": 40},
        "avg_engagement": 25.0,
        "topic_clusters": [],
    }

    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        out_path = f.name

    try:
        path = build_report_html(
            client_name="Test Client",
            period="Marzo 2026",
            report_text="## RESUMEN EJECUTIVO\nTest report content.\n## NARRATIVAS PRINCIPALES\n### Tema 1\nContent here.",
            metrics=metrics,
            anomalies=[],
            output_path=out_path,
            theme="dark",
        )
        assert path.exists()
        size = path.stat().st_size
        assert size > 10000, f"HTML too small: {size} bytes"

        with open(str(path)) as fh:
            html = fh.read()
        assert "Test Client" in html
        assert "const THEME" in html
        print(f"  PASS: generated {size:,} bytes HTML")
    finally:
        os.unlink(out_path)


def test_qa_auditor_basic():
    """Test QA auditor with matching numbers."""
    from agents.report_builder.qa_auditor import _check_numerical_consistency

    metrics = {
        "total_mentions": 1000,
        "sentiment_breakdown": {"positivo": {"count": 600, "percentage": 60.0}},
        "avg_engagement": 25.5,
        "actor_breakdown": {},
        "intersection": {},
    }

    # Text with correct numbers
    text = "Se analizaron 1,000 menciones. El 60% fue positivo."
    checks = _check_numerical_consistency(text, metrics)
    errors = [c for c in checks if c["status"] == "ERROR"]
    assert len(errors) == 0, f"Got {len(errors)} errors on matching numbers: {errors}"
    print(f"  PASS: {len(checks)} checks, {len(errors)} errors")


if __name__ == "__main__":
    tests = [
        ("Parser", test_parser),
        ("Metrics", test_metrics),
        ("Intersection", test_intersection_metrics),
        ("Sentiment Rules", test_sentiment_classifier_rules),
        ("Topics", test_topics),
        ("Sampler", test_sampler),
        ("Config Loading", test_config_loading),
        ("HTML Builder", test_html_builder_basic),
        ("QA Auditor", test_qa_auditor_basic),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"\n[TEST] {name}")
            fn()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if failed:
        sys.exit(1)
