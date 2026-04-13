#!/usr/bin/env python3
"""
RECLASIFICADOR DE YOUSCAN - Solo texto + timestamp
"""

import pandas as pd
import anthropic
import json
import time
import re
import os

YOUSCAN_PATH = "/Users/tomi/epical-intelligence-system/inputs/YouScan_MentionsWithFullText_Avianca_CO__Crisis_Cossio__06032026-07042026_48bfa.xlsx"
OUTPUT_PATH = "/Users/tomi/Desktop/youscan_reclassified.csv"
BATCH_SIZE = 50
MODEL = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic()

print("Cargando YouScan...")
ys = pd.read_excel(YOUSCAN_PATH, sheet_name="Menciones")
print("Total: {} menciones".format(len(ys)))

df = pd.DataFrame({
    "date": pd.to_datetime(ys["Fecha"], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d"),
    "text": ys["Texto"],
    "source_platform": ys["Fuente"],
    "page": ys["Lugar de publicación"],
    "engagement": ys["Engagement"],
    "url": ys["URL"],
    "youscan_sentiment": ys["Sentimiento"],
})

print("\nFiltrando ruido obvio...")

other_airlines = ["American Airlines", "JetBlue", "Copa Airlines"]

def has_conflict_ref(text):
    if pd.isna(text):
        return False
    t = str(text).lower()
    return any(kw in t for kw in ["avianca", "cossio", "yeferson", "incidente", "broma", "vuelo bogota"])

airline_noise = df["page"].isin(other_airlines) & ~df["text"].apply(has_conflict_ref)

def is_empty_text(text):
    if pd.isna(text):
        return True
    clean = re.sub(r"[^\w\s]", "", str(text)).strip()
    return len(clean) < 5

empty_noise = df["text"].apply(is_empty_text)

def is_gaming(text):
    if pd.isna(text):
        return False
    t = str(text).lower()
    return any(kw in t for kw in ["free fire", "freefire", "garena", "mini influencer", "mini_influencer"])

gaming_noise = df["text"].apply(is_gaming) & ~df["text"].apply(has_conflict_ref)

noise_mask = airline_noise | empty_noise | gaming_noise
df["is_noise"] = noise_mask
df_clean = df[~noise_mask].copy()

print("Ruido removido: {}".format(noise_mask.sum()))
print("  Otras aerolíneas: {}".format(airline_noise.sum()))
print("  Textos vacíos: {}".format(empty_noise.sum()))
print("  Gaming: {}".format(gaming_noise.sum()))
print("A clasificar: {}".format(len(df_clean)))

total_batches = len(df_clean) // BATCH_SIZE + 1
print("\nClasificando con Haiku ({} batches)...\n".format(total_batches))

SYSTEM_PROMPT = """Eres un analista de social listening especializado en crisis reputacionales en LATAM.

Contexto: conflicto entre Avianca (aerolínea colombiana) y Yeferson Cossio (influencer colombiano), marzo 2026. Cossio activó un artefacto de olor químico en un vuelo Bogotá-Madrid. Avianca le canceló el contrato y anunció acciones legales.

Para CADA mención, responde SOLO con un JSON array. Cada elemento:
- "idx": índice de la mención
- "relevance": "relevant" (sobre el conflicto), "tangential" (sobre avianca o cossio pero NO sobre el conflicto), "irrelevant" (nada que ver)
- "sentiment": "negativo", "positivo", "neutral" (hacia el actor principal mencionado)
- "actor": "avianca", "cossio", "ambos", "ninguno"
- "confidence": "high", "medium", "low"

REGLAS para español colombiano:
- Sarcasmo: "Que bien que le cancelaron por payaso" = NEGATIVO hacia Cossio
- "parcero", "nea", "mk" = neutro coloquial
- Muerte de la perrita de Cossio = tangential
- Quejas genéricas de servicio de Avianca sin mención del incidente = tangential
- Contenido de fans ("te amo", "eres el mejor") sin referencia al conflicto = tangential

Responde SOLO el JSON array, sin texto adicional, sin backticks."""

results = []
errors = 0
start_time = time.time()

for batch_start in range(0, len(df_clean), BATCH_SIZE):
    batch = df_clean.iloc[batch_start:batch_start + BATCH_SIZE]
    batch_num = batch_start // BATCH_SIZE + 1

    mentions_text = ""
    for i, (idx, row) in enumerate(batch.iterrows()):
        text = str(row["text"])[:300] if pd.notna(row["text"]) else "[vacío]"
        mentions_text += "[{}] {}\n".format(i, text)

    retries = 0
    while retries < 3:
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": mentions_text}]
            )

            content = response.content[0].text.strip()
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
            parsed = json.loads(content)

            for item in parsed:
                if item["idx"] < len(batch):
                    orig_idx = batch.index[item["idx"]]
                    results.append({
                        "original_idx": orig_idx,
                        "relevance": item.get("relevance", "unknown"),
                        "sentiment": item.get("sentiment", "neutral"),
                        "actor": item.get("actor", "ninguno"),
                        "confidence": item.get("confidence", "medium"),
                    })
            break

        except json.JSONDecodeError:
            retries += 1
            print("  Batch {}: JSON error, retry {}/3".format(batch_num, retries))
            time.sleep(3)
        except Exception as e:
            retries += 1
            print("  Batch {}: {}, retry {}/3".format(batch_num, str(e)[:80], retries))
            time.sleep(5)

    if retries == 3:
        errors += 1
        for i, (idx, row) in enumerate(batch.iterrows()):
            results.append({
                "original_idx": idx,
                "relevance": "error",
                "sentiment": "unknown",
                "actor": "unknown",
                "confidence": "none",
            })

    if batch_num % 20 == 0:
        elapsed = time.time() - start_time
        rate = batch_num / elapsed * 60 if elapsed > 0 else 1
        remaining = (total_batches - batch_num) / rate if rate > 0 else 0
        print("  Batch {}/{} | {} clasificadas | ~{:.0f} min restantes".format(
            batch_num, total_batches, len(results), remaining))

    time.sleep(0.3)

print("\nExportando...")
results_df = pd.DataFrame(results).set_index("original_idx")
df_clean = df_clean.join(results_df)

noise_df = df[df["is_noise"]].copy()
noise_df["relevance"] = "noise"
noise_df["sentiment"] = "removed"
noise_df["actor"] = "removed"
noise_df["confidence"] = "n/a"

final = pd.concat([df_clean, noise_df]).sort_index()
final.to_csv(OUTPUT_PATH, index=False)

elapsed = time.time() - start_time
sep = "=" * 60
print("\n" + sep)
print("RESULTADO FINAL ({:.1f} min)".format(elapsed / 60))
print(sep)
print("Total: {} | Ruido: {} | Clasificadas: {} | Errores: {}".format(
    len(final), len(noise_df), len(df_clean), errors))

classified = final[final["relevance"] != "noise"]
print("\nRelevancia:")
print(classified["relevance"].value_counts().to_string())

rel_only = classified[classified["relevance"] == "relevant"]
print("\nSentimiento (solo relevant, n={}):".format(len(rel_only)))
print(rel_only["sentiment"].value_counts().to_string())

print("\nActores (solo relevant):")
print(rel_only["actor"].value_counts().to_string())

print("\nCSV: {}".format(OUTPUT_PATH))
