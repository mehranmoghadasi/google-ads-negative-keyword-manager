"""CSV readers/writers tolerant of the quirks of Google Ads exports.

Google Ads search-term reports carry 1–3 preamble lines, localised column
headers ("Impr." vs "Impressions"), thousands separators, currency symbols,
percent signs, and "Total: …" summary rows. Everything here normalises that.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from .models import Keyword, MatchType, NegativeKeyword, SearchTermRow, Suggestion

# Column aliases → canonical name (all compared lower-cased, punctuation stripped)
_ALIASES = {
    "search term": "search_term",
    "search_term": "search_term",
    "query": "search_term",
    "campaign": "campaign",
    "ad group": "ad_group",
    "ad_group": "ad_group",
    "impr": "impressions",
    "impressions": "impressions",
    "clicks": "clicks",
    "conversions": "conversions",
    "conv": "conversions",
    "cost": "cost",
    "spend": "cost",
}

_NUM_RE = re.compile(r"[^0-9.\-]")


def _canon(header: str) -> str:
    key = re.sub(r"[.\s]+", " ", header.strip().lower()).strip()
    return _ALIASES.get(key, key.replace(" ", "_"))


def _num(value: str | None) -> float:
    if value is None:
        return 0.0
    cleaned = _NUM_RE.sub("", str(value).replace(",", ""))
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _find_header_line(lines: list[str]) -> int:
    """Locate the real header row: the first line whose *cells* include a
    search-term column. Title/date preamble lines ("Search terms report") are
    single-cell and therefore skipped."""
    for i, line in enumerate(lines[:10]):
        cells = [_canon(c) for c in next(csv.reader([line]), [])]
        if len(cells) >= 2 and "search_term" in cells:
            return i
    return 0


def read_search_term_report(path: str | Path) -> list[SearchTermRow]:
    """Parse a Google Ads search-term report CSV into normalised rows."""
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    start = _find_header_line(lines)
    reader = csv.DictReader(io.StringIO("\n".join(lines[start:])))
    if not reader.fieldnames:
        return []
    mapping = {h: _canon(h) for h in reader.fieldnames}
    rows: list[SearchTermRow] = []
    for raw in reader:
        rec = {mapping[k]: v for k, v in raw.items() if k in mapping}
        term = (rec.get("search_term") or "").strip()
        if not term or term.lower().startswith("total"):
            continue
        rows.append(
            SearchTermRow(
                search_term=term,
                campaign=(rec.get("campaign") or "").strip(),
                ad_group=(rec.get("ad_group") or "").strip(),
                impressions=int(_num(rec.get("impressions"))),
                clicks=int(_num(rec.get("clicks"))),
                conversions=_num(rec.get("conversions")),
                cost=_num(rec.get("cost")),
            )
        )
    return rows


def read_existing_negatives(path: str | Path | None) -> set[str]:
    """Return lower-cased, notation-stripped negative terms from any CSV.

    Accepts Google Ads Editor exports (``Keyword`` / ``Negative keyword``
    column) or a bare one-column list.
    """
    if not path or not Path(path).exists():
        return set()
    negatives: set[str] = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return negatives
        cols = {c.lower(): c for c in reader.fieldnames}
        col = cols.get("negative keyword") or cols.get("keyword") or cols.get("negative_keyword") or reader.fieldnames[0]
        for row in reader:
            kw = (row.get(col) or "").strip().strip("[]\"").lower()
            if kw:
                negatives.add(" ".join(kw.split()))
    return negatives


def read_keywords_csv(path: str | Path) -> list[Keyword]:
    """Parse a Google Ads Editor keyword export (Campaign, Ad group, Keyword, Match type, Status)."""
    out: list[Keyword] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            text = r.get("keyword", "")
            status = r.get("status", "enabled").lower()
            if not text or status in {"removed", "paused"}:
                continue
            out.append(
                Keyword(
                    text=text,
                    match_type=MatchType.parse(r.get("match type") or r.get("match_type")),
                    campaign=r.get("campaign", ""),
                    ad_group=r.get("ad group") or r.get("ad_group", ""),
                    status=status,
                )
            )
    return out


def read_negatives_csv(path: str | Path) -> list[NegativeKeyword]:
    """Parse a Google Ads Editor negative-keyword export."""
    out: list[NegativeKeyword] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            r = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            text = r.get("negative keyword") or r.get("negative_keyword") or r.get("keyword", "")
            if not text:
                continue
            out.append(
                NegativeKeyword(
                    text=text,
                    match_type=MatchType.parse(r.get("match type") or r.get("match_type")),
                    campaign=r.get("campaign", ""),
                    ad_group=r.get("ad group") or r.get("ad_group", ""),
                    shared_list=r.get("list name") or r.get("shared_list", ""),
                )
            )
    return out


def write_editor_negatives(
    suggestions: Iterable[Suggestion],
    match_types: Iterable[MatchType],
    out_dir: str | Path,
    *,
    campaign_level: bool = True,
    archive: bool = True,
) -> Path:
    """Write a Google Ads Editor–importable negative list (+ optional monthly archive)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    match_types = list(match_types)
    rows: list[dict[str, str]] = []
    for s in suggestions:
        for mt in match_types:
            rows.append(
                {
                    "Campaign": s.row.campaign or "All Campaigns",
                    "Ad Group": "" if campaign_level else s.row.ad_group,
                    "Keyword": mt.format(s.term),
                    "Match Type": mt.value.capitalize(),
                    "Status": "Enabled",
                    "Reason": "; ".join(s.reasons),
                }
            )
    upload = out_dir / "negatives_upload.csv"
    _write_rows(upload, rows)
    if archive:
        _write_rows(out_dir / f"negatives_archive_{datetime.now(timezone.utc):%Y-%m}.csv", rows)
    return upload


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    fields = ["Campaign", "Ad Group", "Keyword", "Match Type", "Status", "Reason"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
