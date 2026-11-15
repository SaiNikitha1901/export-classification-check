"""Repair PDF text-extraction artefacts without inventing text.

CBIC PDFs come out of pypdf with split words ("classific ation", "V ACUUM", "W O RK ED") and broken
quote glyphs. We rejoin a run of tokens only when (a) the joined word occurs elsewhere in the corpus as a
whole word (at least twice) and (b) at least one piece is rarer in the corpus than the joined word.
So "in to" stays two words ("in" and "to" are far more common than "into"), while "comple te" becomes
"complete" and "V ACUUM" becomes "VACUUM". Nothing is added that is not already in the documents.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

_WORD = re.compile(r"[A-Za-z]+")
_TOKEN = re.compile(r"\S+")
_MAX_SPAN = 8
_MIN_JOINED = 2


_ITEM_MARKER = re.compile(r"\((?:[a-z]{1,2}|[ivx]{1,5})\)")


def build_vocab(texts: Iterable[str]) -> Counter[str]:
    """Lower-cased word frequencies over the whole corpus. Item markers like "(h)" are not words."""
    counts: Counter[str] = Counter()
    for t in texts:
        counts.update(w.lower() for w in _WORD.findall(_ITEM_MARKER.sub(" ", t)))
    return counts


def _piece_count(piece: str, vocab: Counter[str], caps_line: bool) -> int:
    # In an all-caps heading a lone capital is the PDF's drop-cap artefact ("V ACUUM", "H AND").
    if caps_line and len(piece) == 1 and piece.isupper():
        return 0
    return vocab.get(piece.lower(), 0)


def basic_clean(text: str) -> str:
    """Glyph and spacing fixes that need no vocabulary."""
    text = text.replace("�", '"').replace("“", '"').replace("”", '"')
    text = text.replace("‘", "'").replace("’", "'").replace("", "-").replace(" ", " ")
    text = re.sub(r"(\w) -(\w)", r"\1-\2", text)          # "sub -headings" -> "sub-headings"
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.split("\n"))


def _alpha(tok: str) -> str:
    return tok if tok.isalpha() else ""


def rejoin_split_words(line: str, vocab: Counter[str]) -> str:
    toks = _TOKEN.findall(line)
    letters = [c for c in line if c.isalpha()]
    caps_line = len(letters) >= 6 and sum(c.isupper() for c in letters) / len(letters) > 0.8
    out: list[str] = []
    i = 0
    while i < len(toks):
        best_j = None
        # Only purely alphabetic pieces are candidates; punctuation may end the last piece ("ation,").
        for j in range(min(len(toks), i + _MAX_SPAN), i + 1, -1):
            span = toks[i:j]
            head, last = span[:-1], span[-1]
            m = re.match(r"^([A-Za-z]+)([^A-Za-z]*)$", last)
            if not m or not all(_alpha(t) for t in head):
                continue
            pieces = head + [m.group(1)]
            joined = vocab.get("".join(pieces).lower(), 0)
            if joined >= _MIN_JOINED and any(_piece_count(p, vocab, caps_line) < joined for p in pieces):
                best_j = j
                break
        if best_j is None and (caps_line and i + 1 < len(toks) and len(toks[i]) == 1 and toks[i].isupper()
                               and toks[i] not in "AI" and re.match(r"^[A-Z]{2,}", toks[i + 1])):
            # Fallback for the drop-cap artefact in all-caps headings when the whole word is too rare for the
            # vocabulary test: "S HEET" -> "SHEET". "A" and "I" are real words ("OF A CAPACITY" stays).
            out.append(toks[i] + toks[i + 1])
            i += 2
        elif best_j is None:
            out.append(toks[i])
            i += 1
        else:
            out.append("".join(toks[i:best_j]))
            i = best_j
    return " ".join(out)


def normalise(text: str, vocab: Counter[str]) -> str:
    text = basic_clean(text)
    return "\n".join(rejoin_split_words(line, vocab) for line in text.split("\n"))


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
