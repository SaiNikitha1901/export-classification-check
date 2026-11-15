"""Structure-aware parsing of the corpus into legal units (D2, L1).

One chunk per legal unit, each with its A.7 clause ID:
  GRI rules and sub-rules          GRI-1, GRI-2(a) … GRI-6
  Section notes                    SEC-XV-NOTE-1 …
  Chapter notes                    CH73-NOTE-1, CH96-NOTE-1 …
  4-digit headings (+ their lines) HDG-7323, HDG-9617
  8-digit tariff items             TL-96170011
  DGFT Schedule 2 rows             EXP-96020030
  DGFT General Notes               EXP-GN-1 … (contract change #13)

A heading chunk's text starts with the heading's own wording, so a search for the article's name
("vacuum flask") hits HDG-9617 directly instead of the material-based Chapter 73 headings.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from collections import Counter
from typing import Iterable, Iterator, Optional

from pypdf import PdfReader

from retriever.ingest.textnorm import basic_clean, build_vocab, normalise, one_line

CHAPTER_SECTION = {"72": "XV", "73": "XV", "94": "XX", "96": "XX"}
IN_SCOPE_CHAPTERS = ("73", "96")
MAX_NOTE_CHARS = 1500


@dataclass
class Chunk:
    clause_id: str
    kind: str                       # gri|section_note|chapter_note|heading|tariff_line|export_policy
    text: str
    doc_id: str
    doc_version: str
    page: Optional[int]
    section: Optional[str] = None
    chapter: Optional[str] = None
    heading: Optional[str] = None
    title: Optional[str] = None
    meta: dict = field(default_factory=dict)
    passage_id: str = ""

    def finalise(self) -> "Chunk":
        key = "|".join([self.doc_id, self.doc_version, self.clause_id, self.text])
        self.passage_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        return self

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SourceDoc:
    doc_id: str
    file: str
    parser: str
    version: str
    publisher: str
    title: str
    chapter: Optional[str] = None
    section: Optional[str] = None
    pages: Optional[list[int]] = None   # 1-based pages to read; None = all


def load_sources(corpus_dir: Path) -> list[SourceDoc]:
    data = json.loads((corpus_dir / "sources.json").read_text(encoding="utf-8"))
    return [SourceDoc(**d) for d in data["documents"]]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def read_pages(path: Path, pages: Optional[list[int]] = None) -> list[tuple[int, str]]:
    reader = PdfReader(str(path))
    wanted = pages or list(range(1, len(reader.pages) + 1))
    return [(p, basic_clean(reader.pages[p - 1].extract_text() or "")) for p in wanted]


# --------------------------------------------------------------------------- GRI

_GRI_START = re.compile(r"GENERAL RULES FOR THE INTERPRETATION", re.I)
_GRI_END = re.compile(r"GENERAL EXPLANATORY NOTES", re.I)


def parse_gri(doc: SourceDoc, pages: list[tuple[int, str]], vocab: Counter[str]) -> list[Chunk]:
    lines: list[tuple[int, str]] = []
    on = False
    for pno, text in pages:
        for line in normalise(text, vocab).split("\n"):
            if _GRI_START.search(line):
                on = True
                continue
            if on and _GRI_END.search(line):
                on = False
                break
            if on and line and not re.match(r"^(IMPORT TARIFF|THE)$", line):
                lines.append((pno, line))
    body = "\n".join(l for _, l in lines)
    page_of = {}
    for pno, l in lines:
        page_of.setdefault(l[:40], pno)

    def page_for(snippet: str) -> Optional[int]:
        for pno, l in lines:
            if snippet[:30] and snippet[:30] in l:
                return pno
        return lines[0][0] if lines else None

    preamble, _, rest = body.partition("\n1.")
    rules = re.split(r"\n(?=[2-6]\.\s)", "1." + rest)
    chunks: list[Chunk] = []
    for rule in rules:
        m = re.match(r"([1-6])\.\s*(.*)", rule, re.S)
        if not m:
            continue
        num, txt = m.group(1), m.group(2)
        # Sub-rules start a line ("(b) Any reference…"), or open the rule ("2. (a) …"). A "(b)" in the middle
        # of a line is a cross-reference ("rule 2(b)") and must not split.
        parts = re.split(r"(?:^|\n)(?=\((?:a|b|c)\)\s)", txt)
        lead = one_line(parts[0])
        subs = [p for p in parts[1:] if p.strip()]
        if not subs:
            text = one_line(f"{num}. {txt}")
            if num == "1" and preamble.strip():
                text = one_line(preamble) + " " + text
            chunks.append(Chunk(f"GRI-{num}", "gri", text, doc.doc_id, doc.version, page_for(txt.strip()),
                                title=f"General Rule for Interpretation {num}"))
            continue
        for sub in subs:
            letter = sub.strip()[1]
            head = f"{num}. {lead} " if lead else f"{num}. "
            text = one_line(head + sub)
            chunks.append(Chunk(f"GRI-{num}({letter})", "gri", text, doc.doc_id, doc.version,
                                page_for(sub.strip()[4:]), title=f"General Rule for Interpretation {num}({letter})"))
    return chunks


# --------------------------------------------------------------------------- notes

_NOTE_NUM = re.compile(r"^\*?(\d{1,2})\.\s*(.*)$")
_ITEM = re.compile(r"^\*?\((?:[a-z]|ij)\)\s")


def _split_long_note(lead: str, items: list[str]) -> list[str]:
    """Split a long note at its lettered items, repeating the lead-in so each part stands alone."""
    parts, cur = [], []
    for it in items:
        if cur and len(lead) + sum(len(c) for c in cur) + len(it) > MAX_NOTE_CHARS:
            parts.append(cur)
            cur = []
        cur.append(it)
    if cur:
        parts.append(cur)
    return [one_line(lead + " " + " ".join(p)) for p in parts]


def notes_to_chunks(note_lines: list[tuple[int, str]], clause_prefix: str, kind: str, doc: SourceDoc,
                    section: Optional[str], chapter: Optional[str], scope_title: str) -> list[Chunk]:
    notes: list[tuple[str, int, list[str]]] = []
    for pno, line in note_lines:
        m = _NOTE_NUM.match(line)
        if m and (not notes or int(m.group(1)) == int(notes[-1][0]) + 1):
            notes.append((m.group(1), pno, [line]))
        elif notes:
            notes[-1][2].append(line)
    chunks = []
    for num, pno, lines in notes:
        text = one_line(" ".join(lines))
        title = f"{scope_title}, Note {num}"
        if len(text) <= MAX_NOTE_CHARS:
            pieces = [text]
        else:
            # Re-split on lettered items; the lead-in is everything before item (a).
            item_starts = [i for i, l in enumerate(lines) if _ITEM.match(l)]
            if not item_starts:
                pieces = [text]
            else:
                lead = one_line(" ".join(lines[: item_starts[0]]))
                items = [one_line(" ".join(lines[a:b])) for a, b in
                         zip(item_starts, item_starts[1:] + [len(lines)])]
                pieces = _split_long_note(lead, items)
        for i, piece in enumerate(pieces):
            meta = {"part": i + 1, "parts": len(pieces)} if len(pieces) > 1 else {}
            chunks.append(Chunk(f"{clause_prefix}-NOTE-{num}", kind, piece, doc.doc_id, doc.version, pno,
                                section=section, chapter=chapter, title=title, meta=meta))
    return chunks


def parse_section_notes(doc: SourceDoc, pages: list[tuple[int, str]], vocab: Counter[str]) -> list[Chunk]:
    """Section notes printed before the first chapter of the section (Section XV notes in the Ch 72 PDF)."""
    sec = doc.section
    lines: list[tuple[int, str]] = []
    on = False
    for pno, text in pages:
        for line in normalise(text, vocab).split("\n"):
            if re.match(r"^NOTES\s*:?$", line, re.I) and not on:
                on = True
                continue
            if on and re.match(r"^CHAPTER\s+\d+", line):
                return notes_to_chunks(lines, f"SEC-{sec}", "section_note", doc, sec, None, f"Section {sec}")
            if on and line and not _is_noise(line):
                lines.append((pno, line))
    return notes_to_chunks(lines, f"SEC-{sec}", "section_note", doc, sec, None, f"Section {sec}")


# --------------------------------------------------------------------------- tariff chapters

_NOISE = [
    re.compile(r"^--- page"), re.compile(r"^SECTION-[IVXL]+ \d+ CHAPTER-\d+$"), re.compile(r"^_{5,}$"),
    re.compile(r"^\(1\) \(2\)"), re.compile(r"^Tariff Item\b"), re.compile(r"^(Standard|Prefer-|ential|Areas)"),
    re.compile(r"^\*?(w\.e\.f\.|Amended by|Inserted by|Substituted by)", re.I), re.compile(r"^Rate of duty", re.I),
]
_STOP = re.compile(r"^(ADDITIONAL DUTY|ANTI.?DUMPING|SAFEGUARD DUTY|COUNTERVAILING|EXPORT DUTY)", re.I)
_CODE = re.compile(r"^\*?(\d{4})(?:\s(\d{2}))?(?:\s(\d{2}))?\s+(.*)$")
_DASHES = re.compile(r"^\*?(-{1,4})\s*(.+)$")
_UNIT_RATE = re.compile(
    r"(?:\s+|(?<=[,;:]))(kg\.?|u|l|m|m2|m3|pa|tu|2u|g|kl|ct|No\.?|1000\s?u|1000\s?kg|1000\s?kWh)\s+"
    r"(\*?\d+(?:\.\d+)?%|\*?Free|\*?Nil)(?:\s+(?:-|\*?\d+(?:\.\d+)?%?|Free))?\s*$", re.I)


def _is_noise(line: str) -> bool:
    return any(p.search(line) for p in _NOISE)


def _uppercase_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    return sum(c.isupper() for c in letters) / len(letters) if letters else 0.0


@dataclass
class _Line:
    code: str                 # "9617", "961700", "96170011" or "" for a dash group
    level: int                # number of dashes (0 for headings)
    text: str
    page: int
    unit: Optional[str] = None


def _tariff_lines(pages: list[tuple[int, str]], vocab: Counter[str]) -> tuple[list[tuple[int, str]], list[_Line]]:
    """Split a chapter into (note lines, table lines). Table lines get codes, levels and units."""
    notes: list[tuple[int, str]] = []
    table: list[_Line] = []
    phase = "pre"
    for pno, text in pages:
        for raw in normalise(text, vocab).split("\n"):
            line = raw.strip()
            if not line or _is_noise(line):
                continue
            if phase in ("pre", "notes") and re.match(r"^NOTES?\s*:?$", line, re.I):
                phase = "notes"
                continue
            m = _CODE.match(line)
            if phase != "table" and m and (m.group(2) or _uppercase_ratio(m.group(4)) > 0.8):
                phase = "table"
            if phase == "notes":
                notes.append((pno, line))
                continue
            if phase != "table":
                continue
            if _STOP.match(line):
                return notes, table
            unit = None
            um = _UNIT_RATE.search(line)
            if um:
                unit = um.group(1)
                line = line[: um.start()].rstrip()
            m = _CODE.match(line)
            if m:
                code = m.group(1) + (m.group(2) or "") + (m.group(3) or "")
                rest = m.group(4).strip()
                dm = _DASHES.match(rest)
                if len(code) == 4 or (not dm and _uppercase_ratio(rest) > 0.8):
                    table.append(_Line(code, 0, rest, pno, unit))
                elif dm:
                    table.append(_Line(code, len(dm.group(1)), rest, pno, unit))
                else:
                    table.append(_Line(code, 1, rest, pno, unit))
                continue
            dm = _DASHES.match(line)
            if dm and not line.startswith("--- page"):
                table.append(_Line("", len(dm.group(1)), line, pno, unit))
                continue
            if table:                                    # continuation of the previous line
                prev = table[-1]
                prev.text = f"{prev.text} {line}"
                prev.unit = prev.unit or unit
    return notes, table


def _fmt_code(code: str) -> str:
    return " ".join([code[:4], code[4:6], code[6:8]]).strip()


def parse_chapter(doc: SourceDoc, pages: list[tuple[int, str]], vocab: Counter[str]) -> list[Chunk]:
    ch, sec = doc.chapter, doc.section
    note_lines, table = _tariff_lines(pages, vocab)
    chunks = notes_to_chunks(note_lines, f"CH{ch}", "chapter_note", doc, sec, ch, f"Chapter {ch}")

    headings: dict[str, dict] = {}
    order: list[str] = []
    stack: list[tuple[int, str]] = []    # (level, label) of the open sub-headings / dash groups
    current: Optional[str] = None
    for ln in table:
        if ln.level == 0 and ln.code:
            hd = ln.code[:4]
            current = hd
            stack = []
            if hd not in headings:
                headings[hd] = {"title": one_line(ln.text).lstrip("*"), "page": ln.page, "lines": []}
                order.append(hd)
            if len(ln.code) == 8:     # heading that is itself a single tariff item, e.g. "9604 00 00 HAND SIEVES…"
                headings[hd]["lines"].append({"code": ln.code, "label": ln.text, "path": [], "unit": ln.unit,
                                              "page": ln.page})
            continue
        if current is None:
            continue
        label = one_line(ln.text)
        while stack and stack[-1][0] >= ln.level:
            stack.pop()
        if len(ln.code) == 8:
            headings[current]["lines"].append({"code": ln.code, "label": label, "path": [s for _, s in stack],
                                               "unit": ln.unit, "page": ln.page})
        else:
            shown = f"{_fmt_code(ln.code)} {label}" if ln.code else label
            stack.append((ln.level, shown))
            headings[current].setdefault("subheadings", []).append(shown)

    for hd in order:
        h = headings[hd]
        title = h["title"]
        lines_txt = [f"{_fmt_code(l['code'])} {l['label']}" for l in h["lines"]]
        text = f"{hd} {title}\n" + "\n".join(lines_txt)
        chunks.append(Chunk(f"HDG-{hd}", "heading", text.strip(), doc.doc_id, doc.version, h["page"],
                            section=sec, chapter=ch, heading=hd, title=f"Heading {hd}: {title}",
                            meta={"tariff_items": [l["code"] for l in h["lines"]]}))
        for l in h["lines"]:
            parts = [f"Tariff item {_fmt_code(l['code'])}: {l['label']}"]
            if l["path"]:
                parts.append("Under: " + " > ".join(l["path"]))
            parts.append(f"Heading {hd}: {title}")
            if l["unit"]:
                parts.append(f"Unit: {l['unit']}")
            chunks.append(Chunk(f"TL-{l['code']}", "tariff_line", "\n".join(parts), doc.doc_id, doc.version,
                                l["page"], section=sec, chapter=ch, heading=hd,
                                title=f"Tariff item {_fmt_code(l['code'])}", meta={"unit": l["unit"]}))
    return chunks


# --------------------------------------------------------------------------- DGFT export policy

_POLICY = re.compile(r"\b(Free|Restricted|Prohibited|STE)\b")


def parse_dgft_schedule2(doc: SourceDoc, pages: list[tuple[int, str]], vocab: Counter[str]) -> list[Chunk]:
    """Rows of Schedule 2 for the in-scope chapters only. Row text is kept verbatim (whitespace-collapsed)."""
    chunks: list[Chunk] = []
    chapter: Optional[str] = None
    row: Optional[dict] = None

    def flush():
        nonlocal row
        if row:
            text = one_line(" ".join(row["lines"]))
            pm = _POLICY.search(text[len(row["code_txt"]):])
            policy = pm.group(1) if pm else "unknown"
            code = row["code"]
            chunks.append(Chunk(f"EXP-{code}", "export_policy", text, doc.doc_id, doc.version, row["page"],
                                section=CHAPTER_SECTION.get(code[:2]), chapter=code[:2], heading=code[:4],
                                title=f"DGFT Schedule 2 export policy for {_fmt_code(code)}: {policy}",
                                meta={"policy": policy, "basis": "schedule_row"}))
        row = None

    for pno, text in pages:
        for line in normalise(text, vocab).split("\n"):
            cm = re.match(r"^CHAPTER\s+(\d{1,2})\b", line)
            if cm:
                flush()
                chapter = cm.group(1).zfill(2)
                continue
            if chapter not in IN_SCOPE_CHAPTERS:
                continue
            if re.match(r"^(ITC \(HS\)|SCHEDULE 2|S\.No\.|HS Code|Tariff Item)", line):
                continue
            # A serial-number cell ("207", "AA") or an "Ex 293499" code ends the current row. Rows inserted
            # later for other chapters (e.g. 207AA Remdesivir) are printed after Chapter 96 and must not leak.
            if re.match(r"^(\d{1,3}[A-Z]{0,2}|[A-Z]{1,2}|Ex\s+\d{4,8})$", line):
                flush()
                continue
            rm = re.match(r"^(\d{4})\s?(\d{2})\s?(\d{2})\b", line)
            if rm:
                flush()
                code = "".join(rm.groups())
                if code[:2] == chapter:
                    row = {"code": code, "code_txt": rm.group(0), "page": pno, "lines": [line]}
            elif row and line:
                row["lines"].append(line)
    flush()
    return chunks


def parse_dgft_general_notes(doc: SourceDoc, pages: list[tuple[int, str]], vocab: Counter[str]) -> list[Chunk]:
    lines: list[tuple[int, str]] = []
    for pno, text in pages:
        for line in basic_clean(text).split("\n"):
            if line and not re.match(r"^(ITC \(HS\)|SCHEDULE 2)", line):
                lines.append((pno, line))
    # Start at the first numbered note ("1. Free Exportability").
    start = next((i for i, (_, l) in enumerate(lines) if re.match(r"^1\.\s+\S", l)), None)
    if start is None:
        return []
    notes: list[tuple[str, int, list[str]]] = []
    for pno, line in lines[start:]:
        m = re.match(r"^(\d{1,2})\.\s+(.*)$", line)
        if m and (not notes or int(m.group(1)) == int(notes[-1][0]) + 1):
            notes.append((m.group(1), pno, [line]))
        elif notes:
            notes[-1][2].append(line)
    chunks = []
    for num, pno, nl in notes:
        text = one_line(" ".join(nl))
        title = one_line(nl[0])
        chunks.append(Chunk(f"EXP-GN-{num}", "export_policy", text, doc.doc_id, doc.version, pno,
                            title=f"DGFT General Notes to Export Policy, {title}",
                            meta={"basis": "general_note"}))
    return chunks


PARSERS = {
    "gri": parse_gri,
    "section_notes": parse_section_notes,
    "chapter": parse_chapter,
    "dgft_schedule2": parse_dgft_schedule2,
    "dgft_general_notes": parse_dgft_general_notes,
}


def parse_corpus(corpus_dir: Path) -> tuple[list[Chunk], list[dict]]:
    """Parse every document in corpus/sources.json. Returns (chunks, source records for the manifest)."""
    docs = [d for d in load_sources(corpus_dir) if d.parser in PARSERS]
    raw = {d.doc_id: read_pages(corpus_dir / "raw" / d.file, d.pages) for d in docs}
    vocab = build_vocab(t for pages in raw.values() for _, t in pages)
    chunks: list[Chunk] = []
    sources = []
    for d in docs:
        got = PARSERS[d.parser](d, raw[d.doc_id], vocab)
        chunks.extend(c.finalise() for c in got)
        sources.append({"doc_id": d.doc_id, "version": d.version, "file": d.file,
                        "sha256": sha256_file(corpus_dir / "raw" / d.file), "chunks": len(got)})
    return chunks, sources


def iter_kinds(chunks: Iterable[Chunk], kind: str) -> Iterator[Chunk]:
    return (c for c in chunks if c.kind == kind)
