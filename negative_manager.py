#!/usr/bin/env python3
"""
google-ads-negative-keyword-manager/negative_manager.py

Analyzes Google Ads search term reports to suggest negative keywords.
Deduplicates against existing negatives and exports in Google Ads Editor format.

Author: Mehran Moghadasi
License: MIT
"""

import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# CONFIGURATION DEFAULTS
# ---------------------------------------------------------------------------
DEFAULT_MIN_IMPRESSIONS = 10
DEFAULT_MAX_CTR = 0.02           # 2% CTR threshold â below this = likely irrelevant
DEFAULT_HIGH_IMPRESSION_THRESHOLD = 50   # Flag as high-waste if >= 50 impressions + 0 conv
DEFAULT_MATCH_TYPES = ["exact", "phrase"]

# Google Ads search term report column names (standard export)
COL_SEARCH_TERM = "Search term"
COL_CAMPAIGN = "Campaign"
COL_AD_GROUP = "Ad group"
COL_IMPRESSIONS = "Impr."
COL_CLICKS = "Clicks"
COL_CONVERSIONS = "Conversions"
COL_COST = "Cost"
COL_CTR = "CTR"


# ---------------------------------------------------------------------------
# CSV LOADER
# ---------------------------------------------------------------------------
def load_search_term_report(filepath: str) -> pd.DataFrame:
    """
    Loads a Google Ads search term report CSV.
    Handles the standard export format which includes summary rows at the top/bottom.
    """
    # Google Ads reports often have header rows before the actual data
    # Try to auto-detect the header row
    with open(filepath, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()

    header_row = 0
    for i, line in enumerate(lines):
        if COL_SEARCH_TERM in line:
            header_row = i
            break

    df = pd.read_csv(filepath, skiprows=header_row, encoding="utf-8-sig")

    # Drop summary rows (Google adds total rows at the bottom)
    df = df[df[COL_SEARCH_TERM].notna()]
    df = df[~df[COL_SEARCH_TERM].str.startswith("Total", na=True)]

    # Normalize numeric columns
    for col in [COL_IMPRESSIONS, COL_CLICKS, COL_CONVERSIONS, COL_COST]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", "").str.replace("$", "").str.strip(),
                errors="coerce"
            ).fillna(0)

    # Normalize CTR
    if COL_CTR in df.columns:
        df[COL_CTR] = pd.to_numeric(
            df[COL_CTR].astype(str).str.replace("%", "").str.strip(),
            errors="coerce"
        ).fillna(0) / 100
    else:
        df[COL_CTR] = df[COL_CLICKS] / df[COL_IMPRESSIONS].replace(0, 1)

    return df


# ---------------------------------------------------------------------------
# EXISTING NEGATIVES LOADER
# ---------------------------------------------------------------------------
def load_existing_negatives(filepath: str) -> set:
    """
    Loads existing negative keywords from a CSV.
    Returns a set of lowercased keyword strings.
    """
    if not filepath or not os.path.exists(filepath):
        return set()

    negatives = set()
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Handle both Google Ads Editor format and simple keyword lists
            kw = row.get("Keyword", row.get("negative_keyword", "")).strip().lower()
            # Strip match type brackets: [exact] "phrase" broad
            kw = kw.strip("[]\"")
            if kw:
                negatives.add(kw)

    print(f"[info] Loaded {len(negatives)} existing negative keywords")
    return negatives


# ---------------------------------------------------------------------------
# FILTER: IDENTIFY NEGATIVE CANDIDATES
# ---------------------------------------------------------------------------
def identify_negative_candidates(
    df: pd.DataFrame,
    min_impressions: int,
    max_ctr: float,
    existing_negatives: set
) -> pd.DataFrame:
    """
    Applies filtering rules to identify search terms that should be negated.

    Rules:
    1. Zero conversions (always required)
    2. Impressions >= min_impressions (avoid acting on tiny samples)
    3. CTR < max_ctr OR impressions >= high_impression_threshold
    4. Not already in existing negatives list
    """
    candidates = df[
        (df[COL_CONVERSIONS] == 0) &
        (df[COL_IMPRESSIONS] >= min_impressions) &
        (
            (df[COL_CTR] < max_ctr) |
            (df[COL_IMPRESSIONS] >= DEFAULT_HIGH_IMPRESSION_THRESHOLD)
        )
    ].copy()

    # Deduplicate against existing negatives
    candidates["search_term_clean"] = candidates[COL_SEARCH_TERM].str.strip().str.lower()
    before_dedup = len(candidates)
    candidates = candidates[
        ~candidates["search_term_clean"].isin(existing_negatives)
    ]
    skipped = before_dedup - len(candidates)
    print(f"[info] Skipped {skipped} terms already in negative list")

    return candidates


# ---------------------------------------------------------------------------
# MATCH TYPE GENERATOR
# ---------------------------------------------------------------------------
def generate_match_type_variants(keyword: str, match_types: list) -> list:
    """
    Generates different match type variants for a keyword.
    - exact: [keyword]
    - phrase: "keyword"
    - broad: keyword
    """
    kw = keyword.strip().lower()
    variants = []
    if "exact" in match_types:
        variants.append({"keyword": f"[{kw}]", "match_type": "Exact"})
    if "phrase" in match_types:
        variants.append({"keyword": f'"{kw}"', "match_type": "Phrase"})
    if "broad" in match_types:
        variants.append({"keyword": kw, "match_type": "Broad"})
    return variants


# ---------------------------------------------------------------------------
# EXPORT TO GOOGLE ADS EDITOR FORMAT
# ---------------------------------------------------------------------------
def export_for_google_ads_editor(
    candidates: pd.DataFrame,
    match_types: list,
    output_dir: str
) -> str:
    """
    Exports negative keywords in Google Ads Editor upload format.
    Columns: Campaign, Ad Group, Keyword, Match Type, Status
    """
    rows = []
    for _, row in candidates.iterrows():
        search_term = row[COL_SEARCH_TERM].strip()
        campaign = row.get(COL_CAMPAIGN, "")
        variants = generate_match_type_variants(search_term, match_types)
        for v in variants:
            rows.append({
                "Campaign": campaign,
                "Ad Group": "",           # Campaign-level negatives (safer default)
                "Keyword": v["keyword"],
                "Match Type": v["match_type"],
                "Status": "Enabled",
            })

    output_df = pd.DataFrame(rows)
    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = os.path.join(output_dir, "negatives_upload.csv")
    output_df.to_csv(filepath, index=False)
    print(f"[saved] {filepath} ({len(output_df)} rows, ready for Google Ads Editor)")

    # Save monthly archive
    archive_path = os.path.join(
        output_dir, f"negatives_archive_{datetime.now().strftime('%Y-%m')}.csv"
    )
    output_df.to_csv(archive_path, index=False)
    print(f"[saved] Archive: {archive_path}")

    return filepath


# ---------------------------------------------------------------------------
# SUMMARY REPORT
# ---------------------------------------------------------------------------
def print_summary(df: pd.DataFrame, candidates: pd.DataFrame, existing_count: int):
    """Prints a formatted summary to the terminal."""
    high_waste = candidates[candidates[COL_IMPRESSIONS] >= DEFAULT_HIGH_IMPRESSION_THRESHOLD]
    high_waste_sorted = high_waste.sort_values(COL_IMPRESSIONS, ascending=False).head(5)

    print(f"\n=== Google Ads Negative Keyword Manager ===")
    print(f"Search Terms Analyzed:       {len(df):,}")
    print(f"Zero-conversion terms:       {len(df[df[COL_CONVERSIONS] == 0]):,}")
    print(f"High-impression wasted:      {len(high_waste):,}  (â¥{DEFAULT_HIGH_IMPRESSION_THRESHOLD} impressions, 0 conversions)")
    print(f"Already in negatives list:   {existing_count:,}  (skipped)")
    print(f"Net new suggestions:         {len(candidates):,}")

    if not high_waste_sorted.empty:
        print(f"\nTop High-Waste Terms:")
        for _, row in high_waste_sorted.iterrows():
            cost = row.get(COL_COST, 0)
            print(f"  \"{row[COL_SEARCH_TERM]}\"")
            print(f"    â {int(row[COL_IMPRESSIONS])} impressions | {int(row[COL_CONVERSIONS])} conversions | ${cost:.2f} cost")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Google Ads Negative Keyword Manager"
    )
    parser.add_argument("--report", required=True,
                        help="Path to Google Ads search term report CSV")
    parser.add_argument("--existing", default=None,
                        help="Path to existing negatives CSV (optional)")
    parser.add_argument("--min-impressions", type=int, default=DEFAULT_MIN_IMPRESSIONS,
                        help=f"Minimum impressions to consider (default: {DEFAULT_MIN_IMPRESSIONS})")
    parser.add_argument("--max-ctr", type=float, default=DEFAULT_MAX_CTR,
                        help=f"Max CTR threshold (default: {DEFAULT_MAX_CTR})")
    parser.add_argument("--match-types", default="exact,phrase",
                        help="Match types to generate: exact,phrase,broad (default: exact,phrase)")
    parser.add_argument("--output", default="./output/",
                        help="Output directory (default: ./output/)")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    match_types = [m.strip().lower() for m in args.match_types.split(",")]

    print(f"[start] Loading search term report: {args.report}")
    df = load_search_term_report(args.report)
    existing_negatives = load_existing_negatives(args.existing)

    candidates = identify_negative_candidates(
        df, args.min_impressions, args.max_ctr, existing_negatives
    )

    print_summary(df, candidates, len(df) - len(candidates))
    export_for_google_ads_editor(candidates, match_types, args.output)
    print(f"\n[done] Output saved to: {args.output}")


if __name__ == "__main__":
    main()
