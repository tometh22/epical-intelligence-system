"""Multi-source data merger for YouScan + Scrapping exports."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from agents.shared.logger import get_logger
from agents.report_builder.parser import parse_export

logger = get_logger("report-builder")

# Unified schema — every row must have these columns after normalization
UNIFIED_SCHEMA = [
    "date", "text", "sentiment", "author", "platform",
    "engagement", "likes", "comments", "shares", "reach",
    "country", "actor", "data_source", "url",
]

# Sheets to skip in the scrapping file
SKIP_SHEETS = {"Resumen Ejecutivo"}

# --------------------------------------------------------------------------
# YouScan parsing
# --------------------------------------------------------------------------

# Column mapping for YouScan "Menciones" sheet (58-column Spanish export)
YOUSCAN_COL_MAP = {
    "Fecha": "date",
    "Texto": "text",
    "Sentimiento": "sentiment",
    "Autor": "author",
    "Fuente": "platform",
    "Engagement": "engagement",
    "Me gusta": "likes",
    "Comentarios": "comments",
    "Republicaciones": "shares",
    "Visualizaciones": "views",
    "Alcance potencial": "reach",
    "País": "country",
}


def _parse_youscan(filepath: Union[str, Path]) -> Tuple[pd.DataFrame, List[str]]:
    """Parse a YouScan export file into the unified schema."""
    filepath = Path(filepath)
    issues = []  # type: List[str]

    # Read — try "Menciones" sheet first, fall back to first sheet
    ext = filepath.suffix.lower()
    if ext in (".xlsx", ".xls"):
        try:
            df_raw = pd.read_excel(filepath, sheet_name="Menciones", engine="openpyxl" if ext == ".xlsx" else None)
            logger.info("YouScan: read sheet 'Menciones': %d rows, %d cols", len(df_raw), len(df_raw.columns))
        except (ValueError, KeyError):
            df_raw = pd.read_excel(filepath, sheet_name=0, engine="openpyxl" if ext == ".xlsx" else None)
            logger.info("YouScan: sheet 'Menciones' not found, using first sheet: %d rows", len(df_raw))
            issues.append("Sheet 'Menciones' not found — used first sheet")
    else:
        df_raw = parse_export(filepath)

    logger.info("YouScan columns: %s", list(df_raw.columns))

    # Build normalized frame
    normalized = pd.DataFrame()

    # Build a reverse lookup: also try lowercase/English fallbacks
    _YOUSCAN_FALLBACKS = {
        "date": ["date", "fecha", "Date", "Fecha", "Published"],
        "text": ["text", "texto", "Text", "Texto", "Content"],
        "sentiment": ["sentiment", "sentimiento", "Sentiment", "Sentimiento"],
        "author": ["author", "autor", "Author", "Autor"],
        "platform": ["source", "fuente", "Source", "Fuente", "Platform"],
        "engagement": ["engagement", "Engagement"],
        "likes": ["likes", "Me gusta"],
        "comments": ["comments", "Comentarios"],
        "shares": ["shares", "Republicaciones"],
        "reach": ["reach", "Alcance potencial", "Reach"],
        "country": ["country", "País", "Country"],
    }

    for raw_col, std_col in YOUSCAN_COL_MAP.items():
        if raw_col in df_raw.columns:
            normalized[std_col] = df_raw[raw_col]
        else:
            # Try fallback column names
            found = False
            for fallback in _YOUSCAN_FALLBACKS.get(std_col, []):
                if fallback in df_raw.columns:
                    normalized[std_col] = df_raw[fallback]
                    found = True
                    break
            if not found:
                normalized[std_col] = pd.NA
                if std_col in ("date", "text"):
                    issues.append(f"YouScan: critical column '{raw_col}' not found")

    # Detect actor from Influencer/Marca columns
    normalized["actor"] = "unknown"
    # Look for columns matching "Influencer [...]" or "Marca [...]"
    influencer_cols = [c for c in df_raw.columns if c.lower().startswith("influencer")]
    marca_cols = [c for c in df_raw.columns if c.lower().startswith("marca")]

    for _, row_idx in enumerate(df_raw.index):
        actor = "unknown"
        for col in influencer_cols:
            val = df_raw.at[row_idx, col]
            if pd.notna(val) and str(val).strip():
                # Extract actor name from column bracket or value
                if "cossio" in col.lower() or "cossio" in str(val).lower():
                    actor = "cossio"
                    break
        if actor == "unknown":
            for col in marca_cols:
                val = df_raw.at[row_idx, col]
                if pd.notna(val) and str(val).strip():
                    if "avianca" in col.lower() or "avianca" in str(val).lower():
                        actor = "avianca"
                        break
        normalized.at[row_idx, "actor"] = actor

    normalized["data_source"] = "youscan"
    normalized["url"] = pd.NA

    # Look for URL column
    for candidate in ("URL", "url", "Link", "link", "URL de la mención"):
        if candidate in df_raw.columns:
            normalized["url"] = df_raw[candidate]
            break

    # Ensure all schema columns exist
    for col in UNIFIED_SCHEMA:
        if col not in normalized.columns:
            normalized[col] = pd.NA

    normalized = _clean_unified(normalized, issues, "youscan")
    return normalized, issues


# --------------------------------------------------------------------------
# Scrapping parsing — per-sheet handlers
# --------------------------------------------------------------------------

# Sheet configs: sheet_name -> {col_map, fixed_values}
SCRAPPING_SHEETS = {
    "Comentarios relevantes": {
        "col_map": {
            "Texto": "text",
            "Fecha": "date",
            "Engagement": "engagement",
            "Red social": "platform",
            "Username": "author",
            "URL": "url",
        },
        "actor_col": "Perfil posteo",
        "actor_rule": "detect",  # detect from value
    },
    "Comentarios Cossio IG": {
        "col_map": {
            "text": "text",
            "timestamp": "date",
            "likesCount": "likes",
            "ownerUsername": "author",
            "url": "url",
        },
        "fixed": {"platform": "instagram", "actor": "cossio"},
    },
    "Comentarios Avianca IG": {
        "col_map": {
            "text": "text",
            "timestamp": "date",
            "likesCount": "likes",
            "ownerUsername": "author",
            "url": "url",
        },
        "fixed": {"platform": "instagram", "actor": "avianca"},
    },
    "Comentarios Tiktok Avianca": {
        "col_map": {
            "text": "text",
            "createdAt": "date",
            "likeCount": "likes",
            "user": "author",
        },
        "fixed": {"platform": "tiktok", "actor": "avianca"},
    },
    "Comentarios TikTok Cossio": {
        "col_map": {
            "text": "text",
            "createdAt": "date",
            "likeCount": "likes",
            "user": "author",
        },
        "fixed": {"platform": "tiktok", "actor": "cossio"},
    },
    "Comentarios Facebook Cossio": {
        "col_map": {
            "comment.text": "text",
            "comment.created_at": "date",
            "comment.total_reactions": "engagement",
            "comment.author.name": "author",
        },
        "fixed": {"platform": "facebook", "actor": "cossio"},
    },
    "Comentarios Facebbok Avianca": {  # note: typo preserved from real file
        "col_map": {
            "comment.text": "text",
            "comment.created_at": "date",
            "comment.total_reactions": "engagement",
            "comment.author.name": "author",
        },
        "fixed": {"platform": "facebook", "actor": "avianca"},
    },
}


def _parse_scrapping_sheet(
    df_raw: pd.DataFrame,
    sheet_name: str,
    config: dict,
) -> Tuple[pd.DataFrame, List[str]]:
    """Parse a single scrapping sheet into the unified schema."""
    issues = []  # type: List[str]
    col_map = config["col_map"]

    normalized = pd.DataFrame()

    for raw_col, std_col in col_map.items():
        if raw_col in df_raw.columns:
            normalized[std_col] = df_raw[raw_col]
        else:
            normalized[std_col] = pd.NA
            if std_col == "text":
                issues.append(f"[{sheet_name}] Critical: column '{raw_col}' not found")

    # Apply fixed values
    fixed = config.get("fixed", {})
    for key, val in fixed.items():
        normalized[key] = val

    # Handle actor detection for "Comentarios relevantes"
    if config.get("actor_rule") == "detect":
        actor_col = config.get("actor_col", "")
        if actor_col and actor_col in df_raw.columns:
            normalized["actor"] = df_raw[actor_col].apply(
                lambda v: "cossio" if pd.notna(v) and "cossio" in str(v).lower()
                else ("avianca" if pd.notna(v) else "unknown")
            )
        else:
            normalized["actor"] = "unknown"
            issues.append(f"[{sheet_name}] Actor column '{actor_col}' not found")

    normalized["data_source"] = "scrapping"

    # Ensure all schema columns exist
    for col in UNIFIED_SCHEMA:
        if col not in normalized.columns:
            normalized[col] = pd.NA

    normalized = _clean_unified(normalized, issues, sheet_name)
    logger.info("Scrapping sheet '%s': %d rows", sheet_name, len(normalized))
    return normalized, issues


def _parse_scrapping(filepath: Union[str, Path]) -> Tuple[pd.DataFrame, List[str]]:
    """Parse a scrapping export file (multi-sheet Excel) into the unified schema."""
    filepath = Path(filepath)
    issues = []  # type: List[str]
    frames = []  # type: List[pd.DataFrame]

    ext = filepath.suffix.lower()
    engine = "openpyxl" if ext == ".xlsx" else None

    # Read all sheet names
    xls = pd.ExcelFile(filepath, engine=engine)
    sheet_names = xls.sheet_names
    logger.info("Scrapping file sheets: %s", sheet_names)

    for sheet_name in sheet_names:
        if sheet_name in SKIP_SHEETS:
            logger.info("Skipping sheet: %s", sheet_name)
            continue

        # Check if we have a config for this sheet
        config = SCRAPPING_SHEETS.get(sheet_name)
        if config is None:
            # Try case-insensitive match
            for cfg_name, cfg in SCRAPPING_SHEETS.items():
                if cfg_name.lower() == sheet_name.lower():
                    config = cfg
                    break

        if config is None:
            logger.warning("No config for sheet '%s' — skipping", sheet_name)
            issues.append(f"Unknown sheet '{sheet_name}' — skipped")
            continue

        try:
            df_sheet = pd.read_excel(xls, sheet_name=sheet_name)
            logger.info("Sheet '%s': %d rows, columns: %s", sheet_name, len(df_sheet), list(df_sheet.columns))

            if df_sheet.empty:
                issues.append(f"[{sheet_name}] Empty sheet — skipped")
                continue

            df_norm, sheet_issues = _parse_scrapping_sheet(df_sheet, sheet_name, config)
            issues.extend(sheet_issues)
            if not df_norm.empty:
                frames.append(df_norm)
        except Exception as e:
            msg = f"[{sheet_name}] Error parsing: {e}"
            logger.error(msg)
            issues.append(msg)

    if not frames:
        raise ValueError("No data could be parsed from scrapping file")

    merged = pd.concat(frames, ignore_index=True)
    logger.info("Scrapping total: %d rows from %d sheets", len(merged), len(frames))
    return merged, issues


# --------------------------------------------------------------------------
# Cleaning & dedup
# --------------------------------------------------------------------------

def _clean_unified(df: pd.DataFrame, issues: List[str], label: str) -> pd.DataFrame:
    """Apply standard cleaning to a unified-schema DataFrame."""
    # Parse dates
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
        null_dates = df["date"].isna().sum()
        if null_dates > 0:
            issues.append(f"[{label}] {null_dates} rows with unparseable dates")

    # Normalize sentiment
    if "sentiment" in df.columns:
        df["sentiment"] = df["sentiment"].astype(str).str.strip().str.lower()
        df["sentiment"] = df["sentiment"].replace({"nan": pd.NA, "none": pd.NA, "": pd.NA})

    # Numeric columns — fill with 0 for engagement fields, keep NA for reach
    for col in ("engagement", "likes", "comments", "shares"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    if "reach" in df.columns:
        df["reach"] = pd.to_numeric(df["reach"], errors="coerce")

    # Drop rows with no text
    if "text" in df.columns:
        before = len(df)
        df = df.dropna(subset=["text"])
        df = df[df["text"].astype(str).str.strip() != ""]
        dropped = before - len(df)
        if dropped > 0:
            issues.append(f"[{label}] Dropped {dropped} rows with empty text")

    return df


def _deduplicate(df: pd.DataFrame) -> Tuple[pd.DataFrame, int]:
    """Remove duplicates where first 80 chars of text + platform + date are identical."""
    if df.empty:
        return df, 0

    # Build dedup key: first 80 chars of text (lowered) + platform + date-only
    df = df.copy()
    df["_dedup_text"] = df["text"].astype(str).str[:80].str.lower().str.strip()
    df["_dedup_platform"] = df["platform"].astype(str).str.lower().str.strip()
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df["_dedup_date"] = df["date"].dt.date

    before = len(df)
    df = df.drop_duplicates(subset=["_dedup_text", "_dedup_platform", "_dedup_date"], keep="first")
    df = df.drop(columns=["_dedup_text", "_dedup_platform", "_dedup_date"])
    removed = before - len(df)

    return df, removed


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def merge_sources(
    file_paths: List[Union[str, Path]],
    source_labels: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, List[str], Dict[str, int]]:
    """Parse, normalize, merge, and deduplicate YouScan + Scrapping files.

    Args:
        file_paths: List of file paths. First is treated as YouScan, second as Scrapping.
        source_labels: Optional labels (default: ["youscan", "scrapping"]).

    Returns:
        (merged DataFrame in unified schema,
         list of all issues,
         dict with keys: youscan, scrapping, total_unified, duplicates_removed)
    """
    all_issues = []  # type: List[str]
    frames = []  # type: List[pd.DataFrame]
    merge_stats = {}  # type: Dict[str, int]

    labels = source_labels or []

    for i, fp in enumerate(file_paths):
        fp = Path(fp)
        label = labels[i] if i < len(labels) else ("youscan" if i == 0 else "scrapping")

        try:
            if label == "scrapping":
                logger.info("Parsing scrapping file: %s", fp.name)
                df, issues = _parse_scrapping(fp)
            else:
                logger.info("Parsing YouScan file: %s", fp.name)
                df, issues = _parse_youscan(fp)

            all_issues.extend(issues)
            merge_stats[label] = len(df)
            logger.info("Parsed '%s' (%s): %d rows", fp.name, label, len(df))
            frames.append(df)

        except Exception as e:
            msg = f"Failed to process '{fp.name}' ({label}): {e}"
            logger.error(msg, exc_info=True)
            all_issues.append(msg)
            merge_stats[label] = 0

    if not frames:
        raise ValueError("No data could be loaded from any input file")

    # Merge
    merged = pd.concat(frames, ignore_index=True)

    # Ensure column order
    for col in UNIFIED_SCHEMA:
        if col not in merged.columns:
            merged[col] = pd.NA

    merged = merged[UNIFIED_SCHEMA]

    total_before_dedup = len(merged)

    # Deduplicate
    merged, duplicates_removed = _deduplicate(merged)

    merge_stats["total_unified"] = len(merged)
    merge_stats["duplicates_removed"] = duplicates_removed

    if duplicates_removed > 0:
        all_issues.append(
            f"Removed {duplicates_removed} duplicate rows "
            f"(same first 80 chars of text + platform + date)"
        )
        logger.info("Dedup: %d -> %d rows (%d removed)", total_before_dedup, len(merged), duplicates_removed)
    else:
        logger.info("No duplicates found. Total: %d rows", len(merged))

    # Date range filtering: if dates span more than expected, warn and optionally filter
    if "date" in merged.columns:
        date_col = merged["date"].dropna()
        if not date_col.empty:
            min_date = date_col.min()
            max_date = date_col.max()
            date_range_days = (max_date - min_date).days
            if date_range_days > 90:
                # Data spans more than 3 months — likely a date parsing issue
                # Find the main cluster of dates (the period with most activity)
                daily_counts = date_col.dt.to_period('M').value_counts()
                peak_month = daily_counts.index[0]  # most active month
                # Keep data within the peak month ± 1 month
                peak_start = peak_month.start_time - pd.Timedelta(days=30)
                peak_end = peak_month.end_time + pd.Timedelta(days=30)
                before = len(merged)
                merged = merged[(merged["date"].isna()) | ((merged["date"] >= peak_start) & (merged["date"] <= peak_end))]
                filtered = before - len(merged)
                if filtered > 0:
                    all_issues.append(f"Filtered {filtered} rows with dates outside main period ({peak_month})")
                    logger.warning("Date filter: removed %d rows outside main period %s", filtered, peak_month)

    # Log summary
    for label, count in merge_stats.items():
        if label not in ("total_unified", "duplicates_removed"):
            logger.info("Source '%s': %d rows", label, count)
    logger.info(
        "Merge stats — YouScan: %d | Scrapping: %d | Total unified: %d | Duplicates removed: %d",
        merge_stats.get("youscan", 0),
        merge_stats.get("scrapping", 0),
        merge_stats.get("total_unified", 0),
        merge_stats.get("duplicates_removed", 0),
    )

    return merged, all_issues, merge_stats
