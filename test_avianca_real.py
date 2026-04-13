"""Real-data test: Avianca × Cossio crisis report via ReportBuilderAgent.

Loads the reclassified CSVs, runs the full Phase 1 pipeline,
and saves the generated HTML report.
"""

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from agents.report_builder.agent import ReportBuilderAgent

# ── Config ────────────────────────────────────────────────────────

YOUSCAN_CSV = Path.home() / "Desktop" / "youscan_reclassified.csv"
SCRAPPING_CSV = Path.home() / "Desktop" / "scrapping_reclassified.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "report-builder"

BRIEF = (
    "Avianca × Cossio: crisis por incidente de seguridad en vuelo AV46. "
    "Cossio lanzó un químico en la cabina. Avianca emitió comunicado 18 días después. "
    "Período marzo-abril 2026. "
    "Preparado para el Director de Comunicaciones Corporativas de Avianca. "
    "Queremos mostrar que la crisis no es lo que parece — Avianca salió fortalecida."
)

# ── Validate inputs ──────────────────────────────────────────────

for csv_path in [YOUSCAN_CSV, SCRAPPING_CSV]:
    if not csv_path.exists():
        print(f"ERROR: No se encontró {csv_path}")
        sys.exit(1)

print(f"YouScan CSV: {YOUSCAN_CSV} ({YOUSCAN_CSV.stat().st_size / 1_000_000:.1f} MB)")
print(f"Scrapping CSV: {SCRAPPING_CSV} ({SCRAPPING_CSV.stat().st_size / 1_000_000:.1f} MB)")

# ── Create agent ─────────────────────────────────────────────────

agent = ReportBuilderAgent(
    client_name="Avianca",
    period="Marzo — Abril 2026",
    brief=BRIEF,
    file_paths=[str(YOUSCAN_CSV), str(SCRAPPING_CSV)],
    brand="Avianca",
    actors=["Cossio", "Yeferson"],
    source_types=["youscan", "scrapping"],
    client_role="la Dirección de Comunicaciones Corporativas",
    event_date="2026-03-29",  # Comunicado date
    report_type="crisis",
    sentimia_mock=True,  # Skip SentimIA, use local data directly
    output_dir=str(OUTPUT_DIR),
)

# ── Run Phase 1 ──────────────────────────────────────────────────

print("\n" + "=" * 60)
print("FASE 1: PROCESAMIENTO AUTÓNOMO")
print("=" * 60)

start = time.time()

def on_progress(msg):
    elapsed = time.time() - start
    print(f"  [{elapsed:5.1f}s] {msg}")

checkpoint1 = agent.run_phase1(on_progress=on_progress)

elapsed = time.time() - start

# ── Report results ───────────────────────────────────────────────

print("\n" + "=" * 60)
print("CHECKPOINT 1: PRESENTACIÓN AL ANALISTA")
print("=" * 60)
print(checkpoint1.summary)

print("\n--- Detalles ---")
for k, v in checkpoint1.details.items():
    if k == "findings":
        print(f"  findings: {len(v)} hallazgos")
        for i, f in enumerate(v[:3], 1):
            print(f"    {i}. {f.get('text', f.get('title', ''))[:120]}...")
    else:
        print(f"  {k}: {v}")

print(f"\n--- Archivos ---")
for path in checkpoint1.attachments:
    p = Path(path)
    if p.exists():
        size = p.stat().st_size
        print(f"  {p.name}: {size:,} bytes ({size / 1024:.0f} KB)")

print(f"\n--- Validación de reglas ---")
print(checkpoint1.rule_violations)

print(f"\n--- Métricas ---")
m = agent.ctx.metrics
print(f"  Total menciones: {m.get('total_mentions', 0):,}")
print(f"  Sentimiento: {m.get('sentiment_breakdown', {})}")
print(f"  Plataformas: {len(m.get('engagement_by_platform', []))}")
print(f"  Spikes: {len(m.get('spikes', []))}")
print(f"  Reach dedup: {m.get('reach_deduplicated', {}).get('total_reach_formatted', 'N/A')}")
print(f"  Catalizador: {m.get('tangential_analysis', {}).get('catalyst_detected', False)}")
print(f"  Actores: {list(m.get('actor_metrics', {}).keys())}")

# ── Copy to known output path ────────────────────────────────────

if agent.ctx.html_path and Path(agent.ctx.html_path).exists():
    target = OUTPUT_DIR / "avianca_test_output.html"
    import shutil
    shutil.copy2(agent.ctx.html_path, target)
    print(f"\n✅ HTML copiado a: {target}")
    print(f"   Abrir en browser: file://{target}")

print(f"\n⏱️  Tiempo total: {elapsed:.1f}s ({elapsed / 60:.1f} min)")
print(f"🏁 Estado del agente: {agent.state.value}")
