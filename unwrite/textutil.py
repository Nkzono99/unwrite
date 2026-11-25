"""Text utilities: LaTeX-light plain text, tokenization, n-grams, atom extraction."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

BRK = "\x00"  # sentinel that breaks n-gram runs (masked atoms, math, citations)

_CJK = "\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff々〆ヶ"
_TOKEN_RE = re.compile(
    rf"(?P<cjk>[{_CJK}])|(?P<word>[A-Za-z][A-Za-z0-9'\-]*)|(?P<num>\d+(?:\.\d+)?)|(?P<brk>{BRK})"
)

_CITE_RE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")
_PANDOC_CITE_RE = re.compile(r"(?<![\w.])@([A-Za-z0-9_][\w:.\-]*\w)")
_LABELREF_RE = re.compile(r"\\(?:[a-zA-Z]*ref|label)\*?\{([^}]*)\}")
_CMD_ARG_DROP_RE = re.compile(
    r"\\(?:[a-zA-Z]*cite[a-zA-Z]*|[a-zA-Z]*ref|label|url|href|begin|end|includegraphics"
    r"|bibliography[a-zA-Z]*)\*?(?:\[[^\]]*\])*\{[^}]*\}"
)
_INLINE_MATH_RE = re.compile(r"\$[^$]*\$|\\\(.*?\\\)")
_CMD_RE = re.compile(r"\\[a-zA-Z]+\*?")
_NUM_STRICT_RE = re.compile(r"(?<![A-Za-z_\d.])\d+(?:\.\d+)?")
_NUM_LOOSE_RE = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Token:
    text: str
    kind: str  # cjk | word | num | brk
    line: int = 0


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def strip_tex_comments(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*", "", ln) for ln in text.split("\n"))


def plain(text: str) -> str:
    """Remove LaTeX markup; citations, refs and inline math become BRK."""
    t = _CMD_ARG_DROP_RE.sub(f" {BRK} ", text)
    t = _INLINE_MATH_RE.sub(f" {BRK} ", t)
    t = _PANDOC_CITE_RE.sub(f" {BRK} ", t)
    t = _CMD_RE.sub(f" {BRK} ", t)  # any remaining command (number macros, formatting) breaks runs
    t = t.replace("~", " ")
    t = re.sub(r"[{}]", " ", t)
    return nfkc(t)


def _phrase_pattern(phrase: str) -> str:
    pat = re.escape(phrase)
    if re.match(r"[A-Za-z0-9]", phrase):
        pat = r"(?<![A-Za-z0-9])" + pat
    if re.search(r"[A-Za-z0-9]$", phrase):
        pat = pat + r"(?![A-Za-z0-9])"
    return pat


@lru_cache(maxsize=64)
def _mask_regexes(phrases: frozenset) -> tuple:
    """Two combined patterns (raw form, plain form), alternatives longest first."""
    raw = sorted({nfkc(p).strip() for p in phrases if p and p.strip()}, key=len, reverse=True)
    plains = sorted({plain(p).replace(BRK, " ").strip() for p in raw} - {""}, key=len, reverse=True)
    def build(items):
        return re.compile("|".join(_phrase_pattern(p) for p in items), re.IGNORECASE) if items else None
    return build(raw), build(plains)


def mask(text: str, phrases: Iterable[str]) -> str:
    """Replace each phrase (atoms, terms) with BRK, longest first, in raw and plain form."""
    key = phrases if isinstance(phrases, frozenset) else frozenset(phrases)
    raw_re, plain_re = _mask_regexes(key)
    t = nfkc(text)
    if raw_re is not None:
        t = raw_re.sub(f" {BRK} ", t)
    t = plain(t)
    if plain_re is not None:
        t = plain_re.sub(f" {BRK} ", t)
    return t


def tokenize(text: str, line: int = 0) -> list[Token]:
    out = []
    for m in _TOKEN_RE.finditer(text):
        kind = m.lastgroup
        tok = m.group(0)
        if kind == "word":
            tok = tok.lower()
        out.append(Token(tok, kind, line))
    return out


def _strip_keyed(text: str) -> str:
    return _CMD_ARG_DROP_RE.sub(" ", text)


def numbers_strict(text: str) -> set[str]:
    """Numbers a reader would see in the source (citation keys and labels excluded)."""
    t = nfkc(_strip_keyed(text))
    t = _PANDOC_CITE_RE.sub(" ", t)
    return set(_NUM_STRICT_RE.findall(t))


def numbers_loose(text: str) -> set[str]:
    return set(_NUM_LOOSE_RE.findall(nfkc(text)))


def cite_keys(text: str) -> set[str]:
    keys = set()
    for m in _CITE_RE.finditer(text):
        keys.update(k.strip() for k in m.group(1).split(",") if k.strip())
    keys.update(_PANDOC_CITE_RE.findall(text))
    return keys


def label_keys(text: str) -> set[str]:
    return {k.strip() for m in _LABELREF_RE.finditer(text) for k in m.group(1).split(",") if k.strip()}


_MACRO_USE_RE = re.compile(r"\\([a-zA-Z]+)")


def macros_used(text: str, macros: dict) -> set[str]:
    """Names of known (number) macros used in text, e.g. {'floorPot'}."""
    return {m for m in _MACRO_USE_RE.findall(text) if m in macros}


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", "", nfkc(text))
