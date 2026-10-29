"""Numeric grounding verifier.

`verify(text)` returns one violation for every number in `text` that is not a fact reference
(`{{F<id>}}`). It is deliberately strict: any character Unicode classifies as numeric counts
(ASCII, Arabic-Indic, fullwidth, superscripts, vulgar fractions, Roman numeral and CJK numeral
characters), as do English number words.

Allowed, and nothing else:
- fact references `{{F<id>}}` (ASCII digits only);
- entity references `{{E:store}}`, `{{E:product:<uuid>}}`, `{{E:campaign:<uuid>}}` (lower-case
  canonical UUIDs only);
- valid ISO 8601 dates and date-times (`2026-10-27`, `2026-10-27T14:05:00Z`);
- years 1900-2099 written as four ASCII digits after a year-context word ("in 2026",
  "since 2025", "Q3 2026", "between 2025 and 2026"), never next to a currency, unit or percent;
- tokens the caller passes in `allowed` (matched whole, case-sensitive);
- ordered-list markers at the start of a line ("1. ", "2) "), only while they count 1, 2, 3...
  in order: "30. days of cover" on its own is still flagged.

Multiplicative claims are numbers too: "doubled", "tripled", "halved", "twice", "threefold",
"3x", "3 times", "three times".

Known strictness: "Q3"-style labels and "half" are flagged; pass labels through `allowed`.
Not detected: ordinals ("first"), "single", and number words in languages other than English.
LLM output is meant to be structured (see ADR 0002), so the verifier mostly sees short prose.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.verifier.render import ENTITY_REFERENCE, REFERENCE


class ViolationKind(StrEnum):
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    NUMBER = "number"
    SPELLED_NUMBER = "spelled_number"
    MULTIPLIER = "multiplier"


@dataclass(frozen=True)
class Violation:
    kind: ViolationKind
    text: str
    start: int
    end: int

    @property
    def message(self) -> str:
        return f"literal {self.kind.value} {self.text!r} at {self.start}: reference a fact instead"


CURRENCY_SYMBOLS = "$€£¥₹¢₩₽₺₴₦₱฿₫"
CURRENCY_WORDS = frozenset(
    {
        "usd",
        "eur",
        "gbp",
        "jpy",
        "cad",
        "aud",
        "chf",
        "dollar",
        "dollars",
        "euro",
        "euros",
        "pound",
        "pounds",
        "cent",
        "cents",
        "bucks",
        "yen",
    }
)
PERCENT_WORDS = frozenset({"percent", "pct", "pp", "bps", "basis", "percentage", "points"})
UNIT_WORDS = CURRENCY_WORDS | PERCENT_WORDS | frozenset({"k", "m", "bn", "x"})

NUMBER_WORDS = frozenset(
    {
        "zero",
        "two",
        "three",
        "four",
        "five",
        "six",
        "seven",
        "eight",
        "nine",
        "ten",
        "eleven",
        "twelve",
        "thirteen",
        "fourteen",
        "fifteen",
        "sixteen",
        "seventeen",
        "eighteen",
        "nineteen",
        "twenty",
        "thirty",
        "forty",
        "fourty",
        "fifty",
        "sixty",
        "seventy",
        "eighty",
        "ninety",
        "hundred",
        "hundreds",
        "thousand",
        "thousands",
        "million",
        "millions",
        "billion",
        "billions",
        "trillion",
        "trillions",
        "dozen",
        "dozens",
        "tens",
        "half",
        "percent",
    }
)
# Multiplicative claims. Whole words only: "double-check" is one word and is not flagged.
MULTIPLIER_WORDS = frozenset(
    {
        "double",
        "doubled",
        "doubles",
        "doubling",
        "triple",
        "tripled",
        "triples",
        "tripling",
        "quadruple",
        "quadrupled",
        "quadruples",
        "quadrupling",
        "halve",
        "halved",
        "halves",
        "halving",
        "twice",
        "thrice",
    }
)
# Words that turn a preceding number into a multiplier ("3 times", "three-fold").
MULTIPLIER_SUFFIXES = frozenset({"times", "fold"})
# "double down" is an idiom, not a claim.
MULTIPLIER_IDIOM_NEXT = frozenset({"down"})
# "one" is only a number next to another number word or a unit ("one hundred", "one percent").
WEAK_NUMBER_WORDS = frozenset({"one", "a"})
CONNECTORS = frozenset({"and", "point", "a"})

YEAR_CONTEXT = frozenset(
    {
        "in",
        "since",
        "during",
        "from",
        "until",
        "till",
        "through",
        "by",
        "of",
        "for",
        "year",
        "fy",
        "before",
        "after",
        "between",
        "early",
        "late",
        "mid",
        "q1",
        "q2",
        "q3",
        "q4",
        "h1",
        "h2",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "jan",
        "feb",
        "mar",
        "apr",
        "jun",
        "jul",
        "aug",
        "sep",
        "sept",
        "oct",
        "nov",
        "dec",
    }
)
YEAR_RANGE_JOINERS = frozenset({"and", "or", "to", "-", "–", "—", "/"})

ISO_DATETIME = re.compile(
    r"(?<![\w.,$€£¥])"
    r"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"
    r"(?P<time>T[0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?"
    r"(?![\w])"
)
YEAR = re.compile(
    r"(?<![\w.,:/$€£¥₹+\-−])(?P<year>(?:19|20)[0-9]{2})(?![\w%‰])(?![.,][0-9])"
    r"(?!\s*(?:%|‰|[$€£¥₹×]|(?:percent|pct|usd|eur|gbp|dollars?|euros?|pounds?|k|m|bn|x)\b))",
    re.IGNORECASE,
)
LIST_MARKER = re.compile(r"^[ 	]{0,3}(?P<n>[0-9]{1,9})[.)](?=[ 	])", re.MULTILINE)
FOLD_WORD = re.compile(r"^(?P<prefix>[a-z]+)-?fold$")
PRECEDING_WORD = re.compile(r"([\w\-–—/]+)\W*$")
TOKEN = re.compile(r"\S+")
WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
STRIP = "()[]{}<>\"'*_`~.,;:!?"


def _is_numeric_char(ch: str) -> bool:
    return ch.isnumeric() or ch.isdigit()


class _Masked:
    """The text with allowed spans blanked out, keeping offsets stable."""

    def __init__(self, text: str) -> None:
        self.chars = list(text)

    def blank(self, start: int, end: int) -> None:
        for i in range(start, end):
            if not self.chars[i].isspace():
                self.chars[i] = " "

    def __str__(self) -> str:
        return "".join(self.chars)


def _mask_references(text: str, masked: _Masked) -> None:
    for pattern in (REFERENCE, ENTITY_REFERENCE):
        for match in pattern.finditer(text):
            masked.blank(match.start(), match.end())


def _mask_allowed(text: str, masked: _Masked, allowed: Iterable[str]) -> None:
    for token in {t for t in allowed if t}:
        pattern = re.compile(r"(?<![\w])" + re.escape(token) + r"(?![\w])")
        for match in pattern.finditer(text):
            masked.blank(match.start(), match.end())


def _mask_list_markers(text: str, masked: _Masked) -> None:
    """Blank ordered-list markers that count 1, 2, 3... A marker of 1 starts a new list."""
    expected = 1
    for match in LIST_MARKER.finditer(text):
        n = int(match.group("n"))
        if n == 1 or n == expected:
            masked.blank(match.start("n"), match.end())
            expected = n + 1


def _valid_iso(match: re.Match[str]) -> bool:
    try:
        date.fromisoformat(match.group("date"))
        if match.group("time"):
            datetime.fromisoformat(match.group(0).replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _mask_dates(text: str, masked: _Masked) -> None:
    for match in ISO_DATETIME.finditer(text):
        if _valid_iso(match):
            masked.blank(match.start(), match.end())


def _mask_years(text: str, masked: _Masked) -> None:
    previous_year_end = -1
    for match in YEAR.finditer(str(masked)):
        before = text[max(0, match.start() - 64) : match.start()]
        word_match = PRECEDING_WORD.search(before)
        word = word_match.group(1).lower() if word_match else ""
        gap = text[previous_year_end : match.start()].strip() if previous_year_end >= 0 else None
        if re.search(r"(?:usd|eur|gbp|[$€£¥₹])\s*$", before, re.IGNORECASE):
            continue
        joined_range = gap is not None and gap.lower() in YEAR_RANGE_JOINERS
        if word in YEAR_CONTEXT or joined_range:
            masked.blank(match.start(), match.end())
            previous_year_end = match.end()


def _classify(text: str, start: int, end: int) -> tuple[ViolationKind, int]:
    """Kind of a numeric token, and the end of the violation span (it may absorb a unit word)."""
    token = text[start:end]
    after = re.match(r"\s*([^\W\d_]+|%|‰|×)", text[end:])
    next_word = after.group(1).lower() if after else ""
    before = re.search(r"([^\W\d_]+)\s*$", text[:start])
    prev_word = before.group(1).lower() if before else ""
    absorbed = UNIT_WORDS | MULTIPLIER_SUFFIXES | {"%", "‰", "×"}
    span_end = end + after.end() if after and next_word in absorbed else end
    if any(ch in CURRENCY_SYMBOLS for ch in token) or {next_word, prev_word} & CURRENCY_WORDS:
        return ViolationKind.CURRENCY, span_end
    if "%" in token or "‰" in token or next_word in PERCENT_WORDS | {"%", "‰"}:
        return ViolationKind.PERCENTAGE, span_end
    if (
        re.search(r"[0-9.]\s*[x×]$", token, re.IGNORECASE)
        or re.search(r"[0-9]-?fold$", token, re.IGNORECASE)
        or next_word in MULTIPLIER_SUFFIXES | {"x", "×"}
    ):
        return ViolationKind.MULTIPLIER, span_end
    if re.search(r"[0-9][:/][0-9]", token):
        return ViolationKind.RATIO, span_end
    return ViolationKind.NUMBER, span_end


def _numeric_violations(text: str, masked: str) -> list[Violation]:
    out: list[Violation] = []
    for match in TOKEN.finditer(masked):
        if not any(_is_numeric_char(ch) for ch in match.group(0)):
            continue
        start, end = match.start(), match.end()
        while start < end and masked[start] in STRIP:
            start += 1
        while end > start and masked[end - 1] in STRIP:
            end -= 1
        kind, span_end = _classify(text, start, end)
        out.append(Violation(kind, text[start:span_end], start, span_end))
    return out


def _spelled_violations(text: str, masked: str, taken: list[Violation]) -> list[Violation]:
    """Number words, grouped into phrases. Words already inside a numeric violation (the unit in
    "12 percent") are not reported twice."""
    covered = {i for v in taken for i in range(v.start, v.end)}
    words = [
        (m.group(0).lower(), m.start(), m.end())
        for m in WORD.finditer(masked)
        if m.start() not in covered
    ]

    def is_number(i: int) -> bool:
        word = words[i][0]
        parts = word.split("-")
        return word in NUMBER_WORDS or any(p in NUMBER_WORDS for p in parts)

    def is_multiplier(i: int) -> bool:
        word = words[i][0]
        if word in MULTIPLIER_WORDS:
            following = words[i + 1][0] if i + 1 < len(words) else ""
            return following not in MULTIPLIER_IDIOM_NEXT
        # "twofold", "ten-fold", "hundredfold"; not "manifold".
        fold = FOLD_WORD.match(word)
        return fold is not None and fold.group("prefix") in NUMBER_WORDS

    def is_weak_number(i: int) -> bool:
        if words[i][0] not in WEAK_NUMBER_WORDS:
            return False
        if words[i][0] == "a":
            return i + 1 < len(words) and is_number(i + 1) and not is_multiplier(i + 1)
        neighbours = [words[j][0] for j in (i - 1, i + 1) if 0 <= j < len(words)]
        return any(w in NUMBER_WORDS or w in UNIT_WORDS for w in neighbours)

    out: list[Violation] = []
    i = 0
    while i < len(words):
        if is_multiplier(i):
            _, start, end = words[i]
            out.append(Violation(ViolationKind.MULTIPLIER, text[start:end], start, end))
            i += 1
            continue
        if not (is_number(i) or is_weak_number(i)):
            i += 1
            continue
        first = last = i
        j = i + 1
        while j < len(words):
            grouped = UNIT_WORDS | MULTIPLIER_SUFFIXES
            if is_number(j) or is_weak_number(j) or words[j][0] in grouped:
                last = j
                j += 1
            elif words[j][0] in CONNECTORS and j + 1 < len(words) and is_number(j + 1):
                j += 1
            else:
                break
        group = [words[k][0] for k in range(first, last + 1)]
        if any(is_number(k) or words[k][0] == "one" for k in range(first, last + 1)):
            start, end = words[first][1], words[last][2]
            multiplies = any(w in MULTIPLIER_SUFFIXES or w.endswith("-fold") for w in group)
            kind = ViolationKind.MULTIPLIER if multiplies else ViolationKind.SPELLED_NUMBER
            out.append(Violation(kind, text[start:end], start, end))
        i = last + 1
    return out


def verify(text: str, allowed: Iterable[str] = ()) -> list[Violation]:
    """Every numeric literal outside a fact reference, in order of appearance."""
    masked = _Masked(text)
    _mask_references(text, masked)
    _mask_allowed(text, masked, allowed)
    _mask_dates(text, masked)
    _mask_list_markers(text, masked)
    _mask_years(text, masked)
    flat = str(masked)
    numeric = _numeric_violations(text, flat)
    violations = numeric + _spelled_violations(text, flat, numeric)
    return sorted(violations, key=lambda v: (v.start, v.end))
