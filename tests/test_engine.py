from pathlib import Path

import pytest

from negkw.engine import (
    SuggestRules,
    audit_suggestions,
    find_conflicts,
    negative_blocks_keyword,
    suggest_negatives,
)
from negkw.io import read_existing_negatives, read_keywords_csv, read_search_term_report
from negkw.models import Keyword, MatchType, NegativeKeyword, SearchTermRow, Severity

FIX = Path(__file__).parent / "fixtures"


def kw(text, mt, campaign="C1", ad_group="AG1"):
    return Keyword(text=text, match_type=mt, campaign=campaign, ad_group=ad_group)


def neg(text, mt, campaign="C1", ad_group="", shared=""):
    return NegativeKeyword(text=text, match_type=mt, campaign=campaign, ad_group=ad_group, shared_list=shared)


# ── matching semantics ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "keyword, negative, expected",
    [
        (kw("[running shoes]", MatchType.EXACT), neg("[running shoes]", MatchType.EXACT), True),
        (kw("[running shoes]", MatchType.EXACT), neg("[shoes]", MatchType.EXACT), False),
        (kw('"mens running shoes"', MatchType.PHRASE), neg('"running shoes"', MatchType.PHRASE), True),
        (kw('"shoes running"', MatchType.PHRASE), neg('"running shoes"', MatchType.PHRASE), False),
        (kw("+buy +sneakers +online", MatchType.BROAD), neg("sneakers buy", MatchType.BROAD), True),
        (kw("dress shoes", MatchType.BROAD), neg("running", MatchType.BROAD), False),
    ],
)
def test_negative_blocks_keyword(keyword, negative, expected):
    assert negative_blocks_keyword(keyword, negative) is expected


def test_phrase_negative_does_not_match_partial_word():
    # "run" must not block "running shoes" — word-boundary safe
    assert not negative_blocks_keyword(kw('"running shoes"', MatchType.PHRASE), neg('"run"', MatchType.PHRASE))


# ── conflicts ────────────────────────────────────────────────────────────────

def test_find_conflicts_scopes_by_campaign_and_ad_group():
    keywords = [kw("[nike shoes]", MatchType.EXACT, "Brand", "Core"), kw("[nike shoes]", MatchType.EXACT, "Generic", "Core")]
    negatives = [neg("[nike shoes]", MatchType.EXACT, "Brand", ad_group="Other")]
    assert find_conflicts(keywords, negatives) == []  # different ad group, no hit
    negatives = [neg("[nike shoes]", MatchType.EXACT, "Brand")]  # campaign-level
    hits = find_conflicts(keywords, negatives)
    assert len(hits) == 1 and hits[0].severity is Severity.HIGH and hits[0].keyword.campaign == "Brand"


def test_shared_list_is_high_severity_and_sorted_first():
    keywords = [kw('"cheap shoes"', MatchType.PHRASE, "C1", "AG1"), kw("boots", MatchType.BROAD, "C1", "AG1")]
    negatives = [neg("boots", MatchType.BROAD, "C1", ad_group="AG1"), neg('"cheap"', MatchType.PHRASE, "C1", shared="Global")]
    hits = find_conflicts(keywords, negatives)
    assert [h.severity for h in hits] == [Severity.HIGH, Severity.LOW]


# ── suggestions ──────────────────────────────────────────────────────────────

def rows():
    return [
        SearchTermRow("free seo tools", "C1", "AG1", impressions=312, clicks=4, conversions=0, cost=48.2),
        SearchTermRow("buy seo audit", "C1", "AG1", impressions=90, clicks=9, conversions=2, cost=30.0),
        SearchTermRow("seo jobs", "C1", "AG1", impressions=5, clicks=0, conversions=0, cost=0.0),
        SearchTermRow("seo tutorial", "C1", "AG1", impressions=60, clicks=0, conversions=0, cost=0.0),
    ]


def test_suggest_applies_rules_and_existing():
    s = suggest_negatives(rows(), SuggestRules(min_impressions=10, max_ctr=0.02, high_impression_threshold=50), existing={"seo tutorial"})
    terms = [x.term for x in s]
    assert terms == ["free seo tools"]  # converting + tiny-sample + already-negated all excluded
    assert any("impr" in r for r in s[0].reasons)


def test_suggest_protect_regex():
    s = suggest_negatives(rows(), SuggestRules(protect_regex=r"free"), existing=set())
    assert all("free" not in x.term for x in s)


# ── audit ────────────────────────────────────────────────────────────────────

def test_audit_quarantines_self_blocking_negative():
    suggestions = suggest_negatives(rows(), SuggestRules(min_impressions=10, high_impression_threshold=50))
    live = [kw('"free seo tools"', MatchType.PHRASE, "C1", "AG1")]
    outcome = audit_suggestions(suggestions, live, [MatchType.EXACT, MatchType.PHRASE])
    assert [s.term for s, _ in outcome.blocked] == ["free seo tools"]
    assert [s.term for s in outcome.safe] == ["seo tutorial"]  # no live keyword collides


# ── io ───────────────────────────────────────────────────────────────────────

def test_read_search_term_report_handles_preamble_and_totals():
    parsed = read_search_term_report(FIX / "search_terms.csv")
    assert [r.search_term for r in parsed] == ["free seo tools", "seo audit service", "seo tutorial"]
    assert parsed[0].cost == pytest.approx(48.20) and parsed[0].impressions == 1312


def test_read_existing_negatives_strips_notation():
    assert read_existing_negatives(FIX / "negatives.csv") == {"seo tutorial", "jobs"}


def test_read_keywords_skips_paused():
    kws = read_keywords_csv(FIX / "keywords.csv")
    assert [k.text for k in kws] == ['"seo audit service"', "[free seo tools]"]
