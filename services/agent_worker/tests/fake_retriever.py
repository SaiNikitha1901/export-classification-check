"""Fake retriever that follows the A.7 HTTP contract exactly, so the agents can be built and tested
before Member 2's retriever is ready. It is a TEST DOUBLE, never deployed.

Passage text is hand-copied from the official Customs Tariff Act, 1975, First Schedule as published at
thc.nic.in ("Customs Tariff Act, 1975.pdf", schedule substituted by Act 25 of 2003, amended to 2020):
GRI (p.1), Section XV notes, Chapter 73, heading 7323, Chapter 96 notes, heading 9617.
The EXP-* export-policy rows are NOT from an official source I could reach: they are marked
UNCONFIRMED and must be replaced by Member 2's DGFT ITC(HS) Schedule 2 passages.

Search behaviour imitates the real failure the spec describes: "dense"/"hybrid" match surface words
(so the description hits steel headings in Chapter 73 first), "keyword" also matches word stems
(so "vacuum flask" finds heading 9617 "VACUUM FLASKS").
"""
from __future__ import annotations

import re

from fastapi import FastAPI, HTTPException, Request

DOC_TARIFF = "cta-1975-first-schedule"
DOC_TARIFF_V = "Act 25 of 2003 as amended to 2020 (thc.nic.in)"
DOC_POLICY = "dgft-itchs-2022-schedule2-UNCONFIRMED"

_GRI5 = "In addition to the foregoing provisions, the following rules shall apply in respect of the goods referred to therein: "
_P = [
    ("GRI-1", "gri", None, None, None, "General Rules for the Interpretation - Rule 1",
     "The titles of Sections, Chapters and Sub-Chapters are provided for ease of reference only; for legal purposes, "
     "classification shall be determined according to the terms of the headings and any relative Section or Chapter "
     "Notes and, provided such headings or Notes do not otherwise require, according to the following provisions."),
    ("GRI-2(a)", "gri", None, None, None, "General Rules for the Interpretation - Rule 2(a)",
     "Any reference in a heading to an article shall be taken to include a reference to that article incomplete or "
     "unfinished, provided that, as presented, the incomplete or unfinished article has the essential character of "
     "the complete or finished article. It shall also be taken to include a reference to that article complete or "
     "finished (or falling to be classified as complete or, finished by virtue of this rule), presented unassembled "
     "or disassembled."),
    ("GRI-2(b)", "gri", None, None, None, "General Rules for the Interpretation - Rule 2(b)",
     "Any reference in a heading to a material or substance shall be taken to include a reference to mixtures or "
     "combinations of that material or substance with other materials or substances. Any reference to goods of a "
     "given material or substance shall be taken to include a reference to goods consisting wholly or partly of "
     "such material or substance. The classification of goods consisting of more than one material or substance "
     "shall be according to the principles of rule 3."),
    ("GRI-3(a)", "gri", None, None, None, "General Rules for the Interpretation - Rule 3(a)",
     "When by application of rule 2(b) or for any other reason, goods are, prima facie, classifiable under two or "
     "more headings, classification shall be effected as follows: (a) the heading which provides the most specific "
     "description shall be preferred to headings providing a more general description. However, when two or more "
     "headings each refer to part only of the materials or substances contained in mixed or composite goods or to "
     "part only of the items in a set put up for retail sale, those headings are to be regarded as equally specific "
     "in relation to those goods, even if one of them gives a more complete or precise description of the goods."),
    ("GRI-3(b)", "gri", None, None, None, "General Rules for the Interpretation - Rule 3(b)",
     "(b) mixtures, composite goods consisting of different materials or made up of different components, and goods "
     "put up in sets for retail sale, which cannot be classified by reference to (a), shall be classified, as if they "
     "consisted of the material or component which gives them their essential character, insofar as this criterion "
     "is applicable."),
    ("GRI-3(c)", "gri", None, None, None, "General Rules for the Interpretation - Rule 3(c)",
     "(c) when goods cannot be classified by reference to (a) or (b), they shall be classified under the heading "
     "which occurs last in numerical order among those which equally merit consideration."),
    ("GRI-4", "gri", None, None, None, "General Rules for the Interpretation - Rule 4",
     "Goods which cannot be classified in accordance with the above rules shall be classified under the heading "
     "appropriate to the goods to which they are most akin."),
    ("GRI-5(a)", "gri", None, None, None, "General Rules for the Interpretation - Rule 5(a)",
     _GRI5 + "(a) camera cases, musical instrument cases, gun cases, drawing instrument cases, necklace cases and "
     "similar containers, specially shaped or fitted to contain a specific article or set of articles, suitable for "
     "long-term use and presented with the articles for which they are intended, shall be classified with such "
     "articles when of a kind normally sold therewith. This rule does not, however, apply to containers which give "
     "the whole its essential character;"),
    ("GRI-5(b)", "gri", None, None, None, "General Rules for the Interpretation - Rule 5(b)",
     _GRI5 + "(b) subject to the provisions of (a) above, packing materials and packing containers presented with the "
     "goods therein shall be classified with the goods if they are of a kind normally used for packing such goods. "
     "However, this provision does not apply when such packing materials or packing containers are clearly suitable "
     "for repetitive use."),
    ("GRI-6", "gri", None, None, None, "General Rules for the Interpretation - Rule 6",
     "For legal purposes, the classification of goods in the sub-headings of a heading shall be determined according "
     "to the terms of those sub-headings and any related subheading Notes and, mutatis mutandis, to the above rules, "
     "on the understanding that only sub-headings at the same level are comparable. For the purposes of this rule "
     "the relative Section and Chapter Notes also apply, unless the context otherwise requires."),
    ("SEC-XV-NOTE-1", "section_note", "XV", None, None, "Section XV (Base Metals and Articles of Base Metal) - Note 1",
     "This Section does not cover: (a) Prepared paints, inks or other products with a basis of metallic flakes or "
     "powder (headings 3207 to 3210, 3212, 3213 or 3215); (b) Ferro-cerium or other pyrophoric alloys (heading 3606); "
     "(c) Headgear or parts thereof of heading 6506 or 6507; (d) Umbrella frames or other articles of heading 6603; "
     "(e) Goods of Chapter 71 (for example, precious metal alloys, base metal clad with precious metal, imitation "
     "jewellery); (f) Articles of Section XVI (machinery, mechanical appliances and electrical goods); (g) Assembled "
     "railway or tramway track (heading 8608) or other articles of Section XVII (vehicles, ships and boats, aircraft); "
     "(h) Instruments or apparatus of Section XVIII, including clock or watch springs; (ij) Lead shot prepared for "
     "ammunition (heading 9306) or other articles of Section XIX (arms and ammunition); (k) Articles of Chapter 94 "
     "(for example, furniture, mattress supports, lamps and lighting fittings, illuminated signs, prefabricated "
     "buildings); (l) Articles of Chapter 95 (for example, toys, games, sports requisites); (m) Hand sieves, buttons, "
     "pens, pencil-holders, pen nibs or other articles of Chapter 96 (miscellaneous manufactured articles); or "
     "(n) Articles of Chapter 97 (for example, works of art)."),
    ("CH73-NOTE-1", "chapter_note", "XV", "73", None, "Chapter 73 (Articles of Iron or Steel) - Note 1",
     "In this Chapter the expression \"cast iron\" applies to products obtained by casting in which iron predominates "
     "by weight over each of the other elements and which do not comply with the chemical composition of steel as "
     "defined in Note 1 (d) to Chapter 72."),
    ("CH73-NOTE-2", "chapter_note", "XV", "73", None, "Chapter 73 (Articles of Iron or Steel) - Note 2",
     "In this Chapter the word \"wire\" means hot or cold-formed products of any cross-sectional shape, of which no "
     "cross-sectional dimension exceeds 16 mm."),
    ("CH96-NOTE-1", "chapter_note", "XX", "96", None, "Chapter 96 (Miscellaneous Manufactured Articles) - Note 1",
     "This Chapter does not cover: (a) Pencils for cosmetic or toilet uses (Chapter 33); (b) Articles of Chapter 66 "
     "(for example, parts of umbrellas or walking-sticks); (c) Imitation jewellery (heading 7117); (d) Parts of "
     "general use, as defined in Note 2 to Section XV, of base metal (Section XV), or similar goods of plastics "
     "(Chapter 39); (e) Cutlery or other articles of Chapter 82 with handles or other parts of carving or moulding "
     "materials; heading 9601 or 9602 applies, however, to separately presented handles or other parts of such "
     "articles; (f) Articles of Chapter 90 [for example, spectacle frames (heading 9003), mathematical drawing pens "
     "(heading 9017), brushes of a kind specialised for use in dentistry or for medical, surgical or veterinary "
     "purposes (heading 9018)]; (g) Articles of Chapter 91 (for example, clock or watch cases); (h) Musical "
     "instruments or parts or accessories thereof (Chapter 92); (ij) Articles of Chapter 93 (arms and parts "
     "thereof); (k) Articles of Chapter 94 (for example, furniture, lamps and lighting fittings); (l) Articles of "
     "Chapter 95 (toys, games, sports requisites); or (m) Works of art, collectors' pieces or antiques (Chapter 97)."),
    ("CH96-NOTE-4", "chapter_note", "XX", "96", None, "Chapter 96 (Miscellaneous Manufactured Articles) - Note 4",
     "Articles of this Chapter, other than those of headings 9601 to 9606 or 9615, remain classified in the Chapter "
     "whether or not composed wholly or partly of precious metal or metal clad with precious metal, of natural or "
     "cultured pearls, or precious or semi-precious stones (natural, synthetic or reconstructed)."),
    ("HDG-7323", "heading", "XV", "73", "7323", "Heading 7323",
     "7323 TABLE, KITCHEN OR OTHER HOUSEHOLD ARTICLES AND PARTS THEREOF, OF IRON OR STEEL; IRON OR STEEL WOOL; POT "
     "SCOURERS AND SCOURING OR POLISHING PADS, GLOVES AND THE LIKE, OF IRON OR STEEL"),
    ("TL-73239310", "tariff_line", "XV", "73", "7323", "Tariff item 7323 93 10",
     "7323 93 -- Of stainless steel: 7323 93 10 --- Pressure cookers"),
    ("TL-73239390", "tariff_line", "XV", "73", "7323", "Tariff item 7323 93 90",
     "7323 93 -- Of stainless steel: 7323 93 90 --- Other"),
    ("HDG-9617", "heading", "XX", "96", "9617", "Heading 9617",
     "9617 VACUUM FLASKS AND OTHER VACUUM VESSELS, COMPLETE WITH CASES; PARTS THEREOF OTHER THAN GLASS INNERS"),
    ("TL-96170011", "tariff_line", "XX", "96", "9617", "Tariff item 9617 00 11",
     "9617 00 - Vacuum flasks and other vacuum vessels, complete with cases; parts thereof other than glass inners: "
     "--- Vacuum flasks and other vacuum vessels, complete with case: 9617 00 11 ---- Vacuum flasks having a "
     "capacity not exceeding 0.75 l"),
    ("TL-96170012", "tariff_line", "XX", "96", "9617", "Tariff item 9617 00 12",
     "9617 00 - Vacuum flasks and other vacuum vessels, complete with cases; parts thereof other than glass inners: "
     "--- Vacuum flasks and other vacuum vessels, complete with case: 9617 00 12 ---- Vacuum flasks having a "
     "capacity exceeding 0.75 l"),
    ("TL-96170013", "tariff_line", "XX", "96", "9617", "Tariff item 9617 00 13",
     "9617 00 13 ---- Casserol and other vacuum containers"),
    ("TL-96170019", "tariff_line", "XX", "96", "9617", "Tariff item 9617 00 19", "9617 00 19 ---- Other"),
    ("TL-96170090", "tariff_line", "XX", "96", "9617", "Tariff item 9617 00 90",
     "9617 00 90 --- Parts (other than glass inners)"),
    ("EXP-96170011", "export_policy", "XX", "96", "9617", "Export policy 9617 00 11 (UNCONFIRMED)",
     "96170011 Vacuum flasks having a capacity not exceeding 0.75 l Export Policy: Free"),
    ("EXP-96170012", "export_policy", "XX", "96", "9617", "Export policy 9617 00 12 (UNCONFIRMED)",
     "96170012 Vacuum flasks having a capacity exceeding 0.75 l Export Policy: Free"),
    ("EXP-73239390", "export_policy", "XV", "73", "7323", "Export policy 7323 93 90 (UNCONFIRMED)",
     "73239390 Table, kitchen or other household articles of stainless steel: Other Export Policy: Free"),
]

PASSAGES = [
    {"passage_id": f"{DOC_POLICY if kind == 'export_policy' else DOC_TARIFF}#{cid}", "clause_id": cid, "kind": kind,
     "section": sec, "chapter": ch, "heading": hdg, "title": title, "text": text,
     "doc_id": DOC_POLICY if kind == "export_policy" else DOC_TARIFF,
     "doc_version": "UNCONFIRMED" if kind == "export_policy" else DOC_TARIFF_V, "page": None, "score": None}
    for cid, kind, sec, ch, hdg, title, text in _P
]
BY_CLAUSE = {p["clause_id"]: p for p in PASSAGES}
NOTES_FOR_CHAPTER = {"73": ["SEC-XV-NOTE-1", "CH73-NOTE-1", "CH73-NOTE-2"], "96": ["CH96-NOTE-1", "CH96-NOTE-4"]}

app = FastAPI(title="fake retriever (tests only)")
calls: list[dict] = []   # tests inspect what the agents asked for


_STOP = {"with", "and", "the", "other", "for", "thereof", "than", "not", "item", "tariff", "heading", "into"}


def _words(s: str, stem: bool) -> set[str]:
    ws = {w.lower() for w in re.findall(r"[A-Za-z]+", s) if len(w) > 2} - _STOP
    return {w[:-1] if stem and w.endswith("s") and len(w) > 4 else w for w in ws}


@app.middleware("http")
async def _log(request: Request, call_next):
    calls.append({"method": request.method, "path": request.url.path,
                  "correlation_id": request.headers.get("X-Correlation-ID")})
    resp = await call_next(request)
    if request.headers.get("X-Correlation-ID"):
        resp.headers["X-Correlation-ID"] = request.headers["X-Correlation-ID"]
    return resp


@app.get("/health")
def health():
    return {"status": "ok", "fake": True}


@app.post("/search")
def search(body: dict):
    mode = body.get("mode") or "hybrid"
    stem = mode == "keyword"
    q = _words(body.get("query") or "", stem)
    out = []
    for p in PASSAGES:
        if body.get("kinds") and p["kind"] not in body["kinds"]:
            continue
        if body.get("chapters") and p["chapter"] not in body["chapters"]:
            continue
        score = len(q & _words(p["title"] + " " + p["text"], stem))
        if score:
            out.append({**p, "score": float(score)})
    out.sort(key=lambda p: (-p["score"], p["clause_id"]))
    return {"query": body.get("query"), "mode": mode, "passages": out[: int(body.get("k") or 8)], "cache_hit": False}


@app.get("/clause/{clause_id}")
def clause(clause_id: str):
    if clause_id not in BY_CLAUSE:
        raise HTTPException(404, f"{clause_id} not found")
    return {"clause_id": clause_id, "passages": [BY_CLAUSE[clause_id]]}


@app.get("/notes/applicable/{clause_id}")
def notes(clause_id: str):
    p = BY_CLAUSE.get(clause_id)
    if p is None or not p["chapter"]:
        raise HTTPException(404, f"{clause_id} not found")
    return {"clause_id": clause_id, "passages": [BY_CLAUSE[c] for c in NOTES_FOR_CHAPTER[p["chapter"]]]}


@app.get("/policy/{hs_code}")
def policy(hs_code: str):
    rows = [p for p in PASSAGES if p["kind"] == "export_policy" and p["clause_id"] == f"EXP-{hs_code}"]
    rows = rows or [p for p in PASSAGES if p["kind"] == "export_policy" and p["heading"] == hs_code[:4]]
    return {"hs_code": hs_code, "passages": rows}


@app.get("/index/info")
def index_info():
    return {"built_at": "2026-11-12T00:00:00Z", "sources": [{"doc_id": DOC_TARIFF, "version": DOC_TARIFF_V,
                                                             "sha256": None}], "chunk_count": len(PASSAGES),
            "embed_model": None}
