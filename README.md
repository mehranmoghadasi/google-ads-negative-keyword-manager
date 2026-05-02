# Google Ads Negative Keyword Manager

> Stop wasting ad spend on irrelevant searches. Automate your negative keyword workflow.

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://python.org)

## The Problem

Negative keyword management is one of the highest-ROI tasks in PPC — and one of the most tedious. Most PPC managers spend hours each week manually reviewing search term reports, cross-checking existing negatives, and uploading keyword lists. Mistakes are common: duplicate negatives, missing match types, negatives that block converting terms.

## The Solution

`google-ads-negative-keyword-manager` ingests your Google Ads search term report CSV (exported directly from the Google Ads UI), applies configurable filters, and produces a clean, deduplicated negative keyword list ready to upload — with exact match, phrase match, and broad match variants generated automatically.

## Features

- Parses Google Ads search term report CSV (standard export format)
- Filters by minimum impressions, zero conversions, and below-threshold CTR
- Deduplicates against your existing negative keyword list
- Generates Exact, Phrase, and Broad match variants
- Groups suggestions by campaign and ad group
- Flags high-impression wasted spend (configurable threshold)
- Exports upload-ready CSV in Google Ads Editor format
- Saves monthly archive of applied negatives to prevent re-adding

## Tech Stack

- Python 3.8+
- `pandas` — CSV parsing and filtering
- `click` — CLI interface
- `rich` — terminal output formatting
- `openpyxl` — Excel export support

## Installation

```bash
git clone https://github.com/mehranmoghadasi/google-ads-negative-keyword-manager.git
cd google-ads-negative-keyword-manager
pip install -r requirements.txt
```

## Usage

```bash
# Basic analysis
python negative_manager.py --report search_terms.csv

# With existing negatives list and custom thresholds
python negative_manager.py \
  --report search_terms.csv \
  --existing negatives_current.csv \
  --min-impressions 10 \
  --max-ctr 0.02 \
  --output ./output/

# Generate broad match variants only
python negative_manager.py --report search_terms.csv --match-types broad,phrase
```

## Sample Output

```
=== Google Ads Negative Keyword Manager ===
Search Terms Analyzed:       1,847
Zero-conversion terms:         423
High-impression wasted:         38  (≥50 impressions, 0 conversions)
Already in negatives list:      91  (skipped)
Net new suggestions:           332

Top Wasted Spend Terms:
  "free seo tools"           — 312 impressions | $0 conversions | $48.20 cost
  "digital marketing salary" — 198 impressions | $0 conversions | $31.40 cost
  "google ads tutorial"      — 156 impressions | $0 conversions | $27.10 cost

Output files:
  negatives_upload.csv       ← Google Ads Editor format, ready to upload
  negatives_archive_2026-04.csv
  summary_report.csv
```

## MIT License

Copyright (c) 2026 Mehran Moghadasi

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software.
