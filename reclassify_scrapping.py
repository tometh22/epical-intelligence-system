#!/usr/bin/env python3
"""
RECLASIFICADOR DE SCRAPPING - Todas las pestañas unificadas
Corre: python3 -u reclassify_scrapping.py
"""

import pandas as pd
import anthropic
import json
import time
import re
import os

# ============ CONFIGURACIÓN ============
SCRAPPING_PATH = "/Users/tomi/epical-intelligence-system/inputs/Scrapped Comments.xlsx"
OUTPUT_PATH = "/Users/tomi/Desktop/scrapping_reclassified.csv"
BATCH_SIZE = 50
MODEL = "claude-haiku-4-5-20251001"

client = anthropic.Anthropic()

# ============ PASO 1: UNIFICAR TODAS LAS PESTAÑAS ============
print("Cargando y unificando pestañas del scrapping...")
xls = pd.ExcelFile(SCRAPPING_PATH)

all_comments = []

# Comentarios relevantes (curated)
rel = pd.read_excel(xls, sheet_name='Comentarios relevantes', header=0)
rel.columns = ['text','date','engagement','platform','profile','url','post_url','username','col8']
for _, r in rel.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['date'])[:10] if pd.notna(r['date']) else None,
        'platform': r['platform'], 'profile_source': r['profile'], 'engagement': r['engagement'], 'sheet': 'relevantes'})

# Cossio IG
cig = pd.read_excel(xls, sheet_name='Comentarios Cossio IG', header=0)
cig.columns = ['url','likes','username','text','timestamp','post_url']
for _, r in cig.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['timestamp'])[:10] if pd.notna(r['timestamp']) else None,
        'platform': 'Instagram', 'profile_source': 'Cossio', 'engagement': r['likes'] if pd.notna(r['likes']) else 0, 'sheet': 'cossio_ig'})

# Avianca IG
aig = pd.read_excel(xls, sheet_name='Comentarios Avianca IG', header=0)
aig.columns = ['url','likes','username','text','timestamp','post_url']
for _, r in aig.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['timestamp'])[:10] if pd.notna(r['timestamp']) else None,
        'platform': 'Instagram', 'profile_source': 'Avianca', 'engagement': r['likes'] if pd.notna(r['likes']) else 0, 'sheet': 'avianca_ig'})

# TikTok Avianca
tta = pd.read_excel(xls, sheet_name='Comentarios Tiktok Avianca', header=0)
tta.columns = ['likes','text','user','timestamp','source_url']
for _, r in tta.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['timestamp'])[:10] if pd.notna(r['timestamp']) else None,
        'platform': 'TikTok', 'profile_source': 'Avianca', 'engagement': r['likes'] if pd.notna(r['likes']) else 0, 'sheet': 'tiktok_avianca'})

# Facebook Cossio
fbc = pd.read_excel(xls, sheet_name='Comentarios Facebook Cossio', header=0)
fbc.columns = ['pic','author','text','timestamp','reactions','replies','parent','srctype','srcurl','scraped']
for _, r in fbc.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['timestamp'])[:10] if pd.notna(r['timestamp']) else None,
        'platform': 'Facebook', 'profile_source': 'Cossio', 'engagement': r['reactions'] if pd.notna(r['reactions']) else 0, 'sheet': 'facebook_cossio'})

# Facebook Avianca
fba = pd.read_excel(xls, sheet_name='Comentarios Facebbok Avianca', header=0)
fba.columns = ['pic','author','text','timestamp','reactions','replies','parent','srctype','srcurl','scraped']
for _, r in fba.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['timestamp'])[:10] if pd.notna(r['timestamp']) else None,
        'platform': 'Facebook', 'profile_source': 'Avianca', 'engagement': r['reactions'] if pd.notna(r['reactions']) else 0, 'sheet': 'facebook_avianca'})

# TikTok Cossio
ttc = pd.read_excel(xls, sheet_name='Comentarios TikTok Cossio', header=0)
ttc.columns = ['likes','text','user','timestamp','source_url']
for _, r in ttc.iterrows():
    all_comments.append({'text': r['text'], 'date': str(r['timestamp'])[:10] if pd.notna(r['timestamp']) else None,
        'platform': 'TikTok', 'profile_source': 'Cossio', 'engagement': r['likes'] if pd.notna(r['likes']) else 0, 'sheet': 'tiktok_cossio'})

df = pd.DataFrame(all_comments)
print("Total unificado: {}".format(len(df)))

# ============ PASO 2: FILTRAR RUIDO OBVIO ============
print("\nFiltrando ruido obvio...")

def is_empty(text):
    if pd.isna(text): return True
    clean = re.sub(r'[^\w\s]', '', str(text)).strip()
    return len(clean) < 5

def is_real_estate(text):
    if pd.isna(text): return False
    t = str(text).lower()
    return any(kw in t for kw in ['lote', 'loteo', 'inversiones lindallanura', 'acacias', 'terreno', 'proyecto damasco', 'escritura', 'porcentaje'])

def has_conflict_ref(text):
    if pd.isna(text): return False
    t = str(text).lower()
    return any(kw in t for kw in ['avianca','cossio','yeferson','vuelo','avion','aerolinea',
        'olor','quimico','broma','incidente','demanda','legal','seguridad','pasajero','terroris',
        'pedo','bomba','artefacto','irresponsab','payaso','accidente','tripulante','azafata','cabina'])

empty = df['text'].apply(is_empty)
realestate = df['text'].apply(is_real_estate) & ~df['text'].apply(has_conflict_ref)

noise_mask = empty | realestate
df['is_noise'] = noise_mask
df_clean = df[~noise_mask].copy()

print("Ruido removido: {}".format(noise_mask.sum()))
print("  Textos vacios: {}".format(empty.sum()))
print("  Inmobiliarias: {}".format(realestate.sum()))
print("A clasificar: {}".format(len(df_clean)))

# ============ PASO 3: CLASIFICAR CON HAIKU ============
total_batches = len(df_clean) // BATCH_SIZE + 1
print("\nClasificando con Haiku ({} batches)...\n".format(total_batches))

SYSTEM_PROMPT = """Eres un analista de social listening especializado en crisis reputacionales en LATAM.

Contexto: conflicto entre Avianca (aerolínea colombiana) y Yeferson Cossio (influencer colombiano), marzo 2026. Cossio activó un artefacto de olor químico en un vuelo Bogotá-Madrid. Avianca le canceló el contrato y anunció acciones legales.

IMPORTANTE: Estos comentarios vienen de los perfiles de redes sociales de Cossio y Avianca. Muchos NO son sobre el conflicto — son sobre otros temas (mascotas, viajes, inmobiliarias, contenido general de fans).

Para CADA mención, responde SOLO con un JSON array. Cada elemento:
- "idx": índice de la mención
- "relevance": "relevant" (sobre el conflicto Avianca-Cossio), "tangential" (sobre avianca o cossio pero NO sobre el conflicto), "irrelevant" (nada que ver con el conflicto)
- "sentiment": "negativo", "positivo", "neutral"
- "sentiment_toward": quién recibe el sentimiento: "cossio", "avianca", "ambos", "otro" (si no es sobre el conflicto)
- "confidence": "high", "medium", "low"

REGLAS:
- Sarcasmo colombiano: "Que bien que le cancelaron por payaso" = NEGATIVO hacia Cossio
- Muerte de la perrita de Cossio / mascotas = irrelevant
- "te amo", "eres el mejor" sin referencia al conflicto = irrelevant
- Quejas de servicio de Avianca sin mención del incidente = tangential
- Comentarios sobre inmobiliarias/lotes de Cossio = irrelevant
- Posts de Cossio sobre su proyecto Damasco = irrelevant

Responde SOLO el JSON array, sin texto adicional, sin backticks."""

results = []
errors = 0
start_time = time.time()

for batch_start in range(0, len(df_clean), BATCH_SIZE):
    batch = df_clean.iloc[batch_start:batch_start + BATCH_SIZE]
    batch_num = batch_start // BATCH_SIZE + 1

    mentions_text = ""
    for i, (idx, row) in enumerate(batch.iterrows()):
        text = str(row['text'])[:300] if pd.notna(row['text']) else "[vacio]"
        profile = row.get('profile_source', '?')
        mentions_text += "[{}] (perfil:{}) {}\n".format(i, profile, text)

    retries = 0
    while retries < 3:
        try:
            response = client.messages.create(
                model=MODEL, max_tokens=4000, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": mentions_text}]
            )
            content = response.content[0].text.strip()
            content = re.sub(r'^```json\s*', '', content)
            content = re.sub(r'\s*```$', '', content)
            parsed = json.loads(content)
            for item in parsed:
                if item['idx'] < len(batch):
                    orig_idx = batch.index[item['idx']]
                    results.append({
                        'original_idx': orig_idx,
                        'relevance': item.get('relevance', 'unknown'),
                        'sentiment': item.get('sentiment', 'neutral'),
                        'sentiment_toward': item.get('sentiment_toward', 'otro'),
                        'confidence': item.get('confidence', 'medium'),
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
            results.append({'original_idx': idx, 'relevance': 'error', 'sentiment': 'unknown',
                'sentiment_toward': 'unknown', 'confidence': 'none'})

    if batch_num % 20 == 0:
        elapsed = time.time() - start_time
        rate = batch_num / elapsed * 60 if elapsed > 0 else 1
        remaining = (total_batches - batch_num) / rate if rate > 0 else 0
        print("  Batch {}/{} | {} clasificadas | ~{:.0f} min restantes".format(
            batch_num, total_batches, len(results), remaining))

    time.sleep(0.3)

# ============ PASO 4: EXPORTAR ============
print("\nExportando...")
results_df = pd.DataFrame(results).set_index('original_idx')
df_clean = df_clean.join(results_df)

noise_df = df[df['is_noise']].copy()
noise_df['relevance'] = 'noise'
noise_df['sentiment'] = 'removed'
noise_df['sentiment_toward'] = 'removed'
noise_df['confidence'] = 'n/a'

final = pd.concat([df_clean, noise_df]).sort_index()
final.to_csv(OUTPUT_PATH, index=False)

elapsed = time.time() - start_time
sep = "=" * 60
print("\n" + sep)
print("RESULTADO FINAL ({:.1f} min)".format(elapsed / 60))
print(sep)
print("Total: {} | Ruido: {} | Clasificadas: {} | Errores: {}".format(
    len(final), len(noise_df), len(df_clean), errors))

classified = final[final['relevance'].isin(['relevant','tangential'])]
rel_only = final[final['relevance'] == 'relevant']

print("\nRelevancia:")
print(final['relevance'].value_counts().to_string())

print("\nSentimiento (solo relevant, n={}):".format(len(rel_only)))
print(rel_only['sentiment'].value_counts().to_string())

print("\nSentimiento hacia quien (solo relevant):")
print(rel_only['sentiment_toward'].value_counts().to_string())

# Cross: sentiment x sentiment_toward
print("\nSentimiento x Hacia quien:")
cross = pd.crosstab(rel_only['sentiment_toward'], rel_only['sentiment'])
print(cross.to_string())

print("\nCSV: {}".format(OUTPUT_PATH))
