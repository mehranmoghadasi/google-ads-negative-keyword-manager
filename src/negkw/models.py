"""Domain models shared by all negkw workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MatchType(str, Enum):
    EXACT = "exact"
    PHRASE = "phrase"
    BROAD = "broad"

    @classmethod
    def parse(cls, raw: str | None) -> MatchType:
        text = (raw or "").strip().lower()
        if "exact" in text:
            return cls.EXACT
        if "phrase" in text:
            return cls.PHRASE
        return cls.BROAD

    def format(self, term: str) -> str:
        """Render a keyword in Google Ads Editor notation."""
        t = term.strip()
        if self is MatchType.EXACT:
            return f"[{t}]"
        if self is MatchType.PHRASE:
            return f'"{t}"'
        return t


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        return {"high": 0, "medium": 1, "low": 2}[self.value]


def clean_keyword_text(text: str) -> str:
    """Strip match-type notation and modifiers, lower-case, collapse spaces."""
    t = text.strip().strip("[]\"").replace("+", " ")
    return " ".join(t.lower().split())


@dataclass(frozen=True)
class Keyword:
    text: str
    match_type: MatchType
    campaign: str
    ad_group: str = ""
    status: str = "enabled"

    @property
    def clean_text(self) -> str:
        return clean_keyword_text(self.text)

    @property
    def words(self) -> frozenset[str]:
        return frozenset(self.clean_text.split())


@dataclass(frozen=True)
class NegativeKeyword:
    text: str
    match_type: MatchType
    campaign: str
    ad_group: str = ""
    shared_list: str = ""

    @property
    def clean_text(self) -> str:
        return clean_keyword_text(self.text)

    @property
    def words(self) -> frozenset[str]:
        return frozenset(self.clean_text.split())

    @property
    def level(self) -> str:
        if self.shared_list:
            return f"shared list: {self.shared_list}"
        if self.ad_group:
            return "ad group level"
        return "campaign level"


@dataclass
class SearchTermRow:
    """One row of a Google Ads search-term report, normalised."""

    search_term: str
    campaign: str = ""
    ad_group: str = ""
    impressions: int = 0
    clicks: int = 0
    conversions: float = 0.0
    cost: float = 0.0

    @property
    def ctr(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0


@dataclass
class Suggestion:
    row: SearchTermRow
    reasons: list[str] = field(default_factory=list)

    @property
    def term(self) -> str:
        return self.row.search_term.strip()


@dataclass
class Conflict:
    keyword: Keyword
    negative: NegativeKeyword
    severity: Severity
    explanation: str
    fix: str
