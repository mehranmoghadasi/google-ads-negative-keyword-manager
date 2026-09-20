"""Command-line interface for negkw."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from . import __version__
from .engine import SuggestRules, audit_suggestions, find_conflicts, suggest_negatives
from .io import (
    read_existing_negatives,
    read_keywords_csv,
    read_negatives_csv,
    read_search_term_report,
    write_editor_negatives,
)
from .models import Conflict, MatchType, Severity, Suggestion

RED, YEL, CYN, GRN, DIM, RST, BOLD = "\033[91m", "\033[93m", "\033[96m", "\033[92m", "\033[2m", "\033[0m", "\033[1m"


def _parse_match_types(raw: str) -> list[MatchType]:
    return [MatchType(m.strip().lower()) for m in raw.split(",") if m.strip()]


# ─── Reporting ───────────────────────────────────────────────────────────────


def _print_suggestions(rows_total: int, suggestions: list[Suggestion], skipped_existing: int, out: Path) -> None:
    print(f"\n{BOLD}negkw suggest{RST}")
    print("━" * 56)
    print(f"Search terms analysed:      {rows_total:>7,}")
    print(f"Already negated (skipped):  {skipped_existing:>7,}")
    print(f"Net new suggestions:        {len(suggestions):>7,}")
    if suggestions:
        print(f"\n{BOLD}Top wasted spend{RST}")
        for s in suggestions[:8]:
            r = s.row
            print(f"  {DIM}${r.cost:>7.2f}{RST}  {r.impressions:>5} impr  {r.clicks:>4} clk   \"{s.term}\"")
            print(f"           {DIM}{'; '.join(s.reasons)}{RST}")
    print(f"\n{GRN}✔{RST} Editor-ready list: {out}")


def _print_conflicts(conflicts: list[Conflict], n_kw: int, n_neg: int) -> None:
    print(f"\n{BOLD}negkw conflicts{RST}")
    print("━" * 56)
    groups = [
        (Severity.HIGH, RED, "HIGH — likely blocking significant traffic"),
        (Severity.MEDIUM, YEL, "MEDIUM — may limit reach"),
        (Severity.LOW, CYN, "LOW — minor impact"),
    ]
    for sev, color, label in groups:
        items = [c for c in conflicts if c.severity is sev]
        if not items:
            continue
        print(f"\n{color}{label} ({len(items)}){RST}")
        for c in items:
            print(f"  {c.keyword.campaign} › {c.keyword.ad_group or '(campaign)'}")
            print(f"    {c.explanation}")
            print(f"    {DIM}fix: {c.fix}{RST}")
    print("\n" + "━" * 56)
    print(f"Keywords: {n_kw:,}   Negatives: {n_neg:,}   Conflicts: {len(conflicts)}")
    if not conflicts:
        print(f"{GRN}✔ No self-blocking negatives found.{RST}")


def _write_conflicts_csv(conflicts: list[Conflict], path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["severity", "campaign", "ad_group", "keyword", "keyword_match", "negative", "negative_match", "negative_level", "fix"])
        for c in conflicts:
            w.writerow([c.severity.value, c.keyword.campaign, c.keyword.ad_group, c.keyword.text, c.keyword.match_type.value,
                        c.negative.text, c.negative.match_type.value, c.negative.level, c.fix])


# ─── Sub-commands ────────────────────────────────────────────────────────────


def cmd_suggest(a: argparse.Namespace) -> int:
    rows = read_search_term_report(a.report)
    existing = read_existing_negatives(a.existing)
    rules = SuggestRules(
        min_impressions=a.min_impressions,
        min_spend=a.min_spend,
        max_ctr=a.max_ctr,
        high_impression_threshold=a.high_impressions,
        protect_regex=a.protect,
    )
    suggestions = suggest_negatives(rows, rules, existing)
    skipped = sum(1 for r in rows if " ".join(r.search_term.lower().split()) in existing)
    out = write_editor_negatives(suggestions, _parse_match_types(a.match_types), a.output, campaign_level=not a.ad_group_level)
    _print_suggestions(len(rows), suggestions, skipped, out)
    return 0


def cmd_conflicts(a: argparse.Namespace) -> int:
    keywords = read_keywords_csv(a.keywords)
    negatives = read_negatives_csv(a.negatives)
    conflicts = find_conflicts(keywords, negatives)
    allowed = {"high": {Severity.HIGH}, "medium": {Severity.HIGH, Severity.MEDIUM}, "low": set(Severity)}[a.min_severity]
    conflicts = [c for c in conflicts if c.severity in allowed]
    _print_conflicts(conflicts, len(keywords), len(negatives))
    if a.output:
        _write_conflicts_csv(conflicts, Path(a.output))
        print(f"CSV saved: {a.output}")
    return 1 if conflicts and a.fail_on_conflict else 0


def cmd_audit(a: argparse.Namespace) -> int:
    """suggest → screen against live keywords → export only the safe ones."""
    rows = read_search_term_report(a.report)
    existing = read_existing_negatives(a.existing)
    keywords = read_keywords_csv(a.keywords)
    match_types = _parse_match_types(a.match_types)
    rules = SuggestRules(min_impressions=a.min_impressions, min_spend=a.min_spend, max_ctr=a.max_ctr,
                         high_impression_threshold=a.high_impressions, protect_regex=a.protect)
    suggestions = suggest_negatives(rows, rules, existing)
    outcome = audit_suggestions(suggestions, keywords, match_types)

    out_dir = Path(a.output)
    upload = write_editor_negatives(outcome.safe, match_types, out_dir, campaign_level=not a.ad_group_level)
    quarantine = out_dir / "negatives_quarantined.csv"
    with open(quarantine, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["search_term", "campaign", "cost", "impressions", "would_block_keyword", "keyword_match", "severity"])
        for s, hits in outcome.blocked:
            seen: set[str] = set()
            for c in hits:
                if c.keyword.text in seen:
                    continue
                seen.add(c.keyword.text)
                w.writerow([s.term, s.row.campaign, f"{s.row.cost:.2f}", s.row.impressions, c.keyword.text, c.keyword.match_type.value, c.severity.value])

    print(f"\n{BOLD}negkw audit{RST}")
    print("━" * 56)
    print(f"Search terms analysed:        {len(rows):>7,}")
    print(f"Candidate negatives:          {len(suggestions):>7,}")
    print(f"{GRN}Safe to upload:               {len(outcome.safe):>7,}{RST}")
    print(f"{RED}Quarantined (would self-block): {len(outcome.blocked):>5,}{RST}")
    for s, hits in outcome.blocked[:6]:
        print(f"  ✖ \"{s.term}\" → blocks {hits[0].keyword.text} ({hits[0].keyword.match_type.value})")
    print(f"\n{GRN}✔{RST} Upload:      {upload}")
    print(f"{YEL}!{RST} Quarantine:  {quarantine}")
    return 0


# ─── Parser ──────────────────────────────────────────────────────────────────


def _add_suggest_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--report", required=True, help="Google Ads search-term report CSV")
    p.add_argument("--existing", help="Existing negatives CSV to de-duplicate against")
    p.add_argument("--min-impressions", type=int, default=10)
    p.add_argument("--min-spend", type=float, default=0.0, help="Flag zero-conv terms with spend ≥ this")
    p.add_argument("--max-ctr", type=float, default=0.02, help="Flag terms with CTR below this (0.02 = 2%%)")
    p.add_argument("--high-impressions", type=int, default=50, help="Flag zero-conv terms with impressions ≥ this")
    p.add_argument("--protect", help="Regex; matching terms are never suggested (e.g. your brand)")
    p.add_argument("--match-types", default="exact,phrase", help="exact,phrase,broad")
    p.add_argument("--ad-group-level", action="store_true", help="Emit ad-group-level instead of campaign-level negatives")
    p.add_argument("--output", default="./output", help="Output directory")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="negkw", description="Google Ads negative keyword manager")
    p.add_argument("--version", action="version", version=f"negkw {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("suggest", help="Mine a search-term report for negatives")
    _add_suggest_args(s)
    s.set_defaults(fn=cmd_suggest)

    c = sub.add_parser("conflicts", help="Find negatives that block your own keywords")
    c.add_argument("--keywords", required=True, help="Google Ads Editor keyword export CSV")
    c.add_argument("--negatives", required=True, help="Google Ads Editor negative export CSV")
    c.add_argument("--min-severity", choices=["high", "medium", "low"], default="low")
    c.add_argument("--output", help="Save conflict report CSV here")
    c.add_argument("--fail-on-conflict", action="store_true", help="Exit 1 if conflicts found (CI-friendly)")
    c.set_defaults(fn=cmd_conflicts)

    au = sub.add_parser("audit", help="suggest + screen against live keywords before export")
    _add_suggest_args(au)
    au.add_argument("--keywords", required=True, help="Google Ads Editor keyword export CSV")
    au.set_defaults(fn=cmd_audit)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        print(f"{RED}error:{RST} {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
