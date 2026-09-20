"""Core logic: suggestion rules, conflict detection, and the safety audit."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    Conflict,
    Keyword,
    MatchType,
    NegativeKeyword,
    SearchTermRow,
    Severity,
    Suggestion,
)

# ─── Suggestion rules ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SuggestRules:
    """Thresholds that decide whether a search term becomes a negative."""

    min_impressions: int = 10
    min_spend: float = 0.0
    max_ctr: float = 0.02
    high_impression_threshold: int = 50
    protect_regex: str | None = None  # terms matching this are never suggested


def suggest_negatives(
    rows: list[SearchTermRow],
    rules: SuggestRules,
    existing: set[str] | None = None,
) -> list[Suggestion]:
    """Return zero-conversion search terms that meet the waste thresholds.

    A term is suggested when it has zero conversions AND at least
    ``min_impressions`` AND (spend ≥ ``min_spend`` OR CTR < ``max_ctr`` OR
    impressions ≥ ``high_impression_threshold``). Each reason is recorded so
    the exported list explains itself to whoever reviews it.
    """
    import re

    existing = existing or set()
    protect = re.compile(rules.protect_regex, re.IGNORECASE) if rules.protect_regex else None
    out: list[Suggestion] = []
    seen: set[str] = set()

    for r in rows:
        term = " ".join(r.search_term.lower().split())
        if term in seen or term in existing:
            continue
        if r.conversions > 0 or r.impressions < rules.min_impressions:
            continue
        if protect and protect.search(term):
            continue

        reasons: list[str] = []
        if rules.min_spend > 0 and r.cost >= rules.min_spend:
            reasons.append(f"0 conv, ${r.cost:.2f} spend ≥ ${rules.min_spend:.2f}")
        if r.ctr < rules.max_ctr:
            reasons.append(f"CTR {r.ctr:.2%} < {rules.max_ctr:.2%}")
        if r.impressions >= rules.high_impression_threshold:
            reasons.append(f"{r.impressions} impr, 0 conv")
        if not reasons:
            continue

        seen.add(term)
        out.append(Suggestion(row=r, reasons=reasons))

    out.sort(key=lambda s: (s.row.cost, s.row.impressions), reverse=True)
    return out


# ─── Conflict detection ──────────────────────────────────────────────────────


def negative_blocks_keyword(kw: Keyword, neg: NegativeKeyword) -> bool:
    """Google Ads matching semantics for negatives.

    * EXACT negative blocks only an identical query.
    * PHRASE negative blocks when its words appear in order.
    * BROAD negative blocks when all its words appear in any order.
    """
    if neg.match_type is MatchType.EXACT:
        return kw.clean_text == neg.clean_text
    if neg.match_type is MatchType.PHRASE:
        return f" {neg.clean_text} " in f" {kw.clean_text} "
    return neg.words.issubset(kw.words)


def assess_severity(kw: Keyword, neg: NegativeKeyword) -> Severity:
    if neg.shared_list or not neg.ad_group:
        return Severity.HIGH
    if neg.match_type is MatchType.EXACT and kw.match_type is MatchType.EXACT:
        return Severity.HIGH
    if neg.match_type is MatchType.PHRASE:
        return Severity.MEDIUM
    return Severity.LOW


def build_fix(neg: NegativeKeyword) -> str:
    if neg.shared_list:
        return f"Review shared list '{neg.shared_list}' — '{neg.clean_text}' is too broad for this campaign"
    if not neg.ad_group:
        return f"Remove '{neg.clean_text}' from campaign-level negatives or move the keyword to another campaign"
    return f"Tighten '{neg.clean_text}' to a narrower match type or scope it away from this ad group"


def find_conflicts(keywords: list[Keyword], negatives: list[NegativeKeyword]) -> list[Conflict]:
    """Cross-reference every keyword against negatives in the same campaign."""
    by_campaign: dict[str, list[NegativeKeyword]] = {}
    for n in negatives:
        by_campaign.setdefault(n.campaign, []).append(n)

    conflicts: list[Conflict] = []
    for kw in keywords:
        for neg in by_campaign.get(kw.campaign, []):
            if neg.ad_group and neg.ad_group != kw.ad_group:
                continue
            if negative_blocks_keyword(kw, neg):
                conflicts.append(
                    Conflict(
                        keyword=kw,
                        negative=neg,
                        severity=assess_severity(kw, neg),
                        explanation=(
                            f"'{kw.text}' ({kw.match_type.value}) blocked by "
                            f"'{neg.text}' ({neg.match_type.value}, {neg.level})"
                        ),
                        fix=build_fix(neg),
                    )
                )
    conflicts.sort(key=lambda c: c.severity.rank)
    return conflicts


# ─── Safety audit ────────────────────────────────────────────────────────────


@dataclass
class AuditOutcome:
    safe: list[Suggestion]
    blocked: list[tuple[Suggestion, list[Conflict]]]


def audit_suggestions(
    suggestions: list[Suggestion],
    keywords: list[Keyword],
    match_types: list[MatchType],
) -> AuditOutcome:
    """Screen proposed negatives against the live keyword set.

    For every suggestion and every match type you intend to upload, build the
    would-be negative and run it through the conflict engine. Anything that
    would block an active keyword is quarantined instead of exported — this is
    the failure mode all three predecessor tools left to the human.
    """
    safe: list[Suggestion] = []
    blocked: list[tuple[Suggestion, list[Conflict]]] = []
    for s in suggestions:
        hits: list[Conflict] = []
        for mt in match_types:
            neg = NegativeKeyword(
                text=mt.format(s.term),
                match_type=mt,
                campaign=s.row.campaign or "",
            )
            scope = [k for k in keywords if not s.row.campaign or k.campaign == s.row.campaign]
            hits.extend(find_conflicts(scope, [neg]))
        if hits:
            blocked.append((s, hits))
        else:
            safe.append(s)
    return AuditOutcome(safe=safe, blocked=blocked)
