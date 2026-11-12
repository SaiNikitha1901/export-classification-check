# Evaluation 1: Corpus confirmation (Mini Project 07, Export Classification Check)

Prepared by Member 2 (Corpus, Retrieval & Evaluation). Date: 2026-11-12.
Items marked **[CONFIRM]** need faculty confirmation.

## 1. Documents in the corpus

Full details, URLs and sha256 values are in [`corpus/SOURCES.md`](../corpus/SOURCES.md). All are official, public and have a text layer (no OCR needed).

| doc_id | Document | Publisher | Version |
|---|---|---|---|
| `cbic-gri` | Customs Tariff Part I: General Rules for the Interpretation of Import Tariff (pages 30–31) | CBIC | Tariff as on 30.06.2025 |
| `cbic-sec-xv` | Section XV notes (opening pages of the Chapter 72 PDF) | CBIC | Tariff as on 30.06.2025 (file dated 30.06.2024) |
| `cbic-ch73` | Chapter 73: Articles of iron or steel | CBIC | Tariff as on 30.06.2025 (file dated 30.06.2024) |
| `cbic-sec-xx` | Section XX opening (Chapter 94 PDF): shows that Section XX has **no** section notes | CBIC | Tariff as on 30.06.2025 (file dated 30.06.2024) |
| `cbic-ch96` | Chapter 96: Miscellaneous manufactured articles | CBIC | Tariff as on 30.06.2025 (file dated 30.06.2024) |
| `dgft-sch2` | ITC (HS) Schedule 2: Chapter-wise Export Policy | DGFT | ITC (HS) 2018 consolidated file **[CONFIRM version]** |
| `dgft-sch2-gn` | General Notes to Export Policy | DGFT | ITC (HS) 2018 |
| `dgft-sch2-read` | How to read Schedule 2 (policy categories) | DGFT | ITC (HS) 2022 |

Corpus scope: GRI 1–6; Section XV notes; Chapter 73 notes, headings and tariff items; Chapter 96 notes, headings and tariff items; DGFT Schedule 2 rows for Chapters 73 and 96 plus the general notes that decide the default policy.

## 2. Passages the §4.1 case depends on

The case: *"Stainless steel vacuum flask with a moulded plastic outer body."*

Quotes come from the official PDFs' text layer, with only extraction artefacts normalised (split words rejoined, `�` restored to quotes). Page numbers are PDF pages.

### 2.1 GRI 1: classify by the terms of the headings and the notes (`GRI-1`)
Source: `cbic-gri`, page 30.
> "The titles of Sections, Chapters and sub-chapters are provided for ease of reference only; for legal purposes, classification shall be determined according to the terms of the headings and any relative Section or Chapter Notes and, provided such headings or Notes do not otherwise require, according to the following provisions:"

**Why it matters:** the rule makes the system look for a heading whose *terms* describe the article (heading 9617 names "vacuum flasks"). It also says Section and Chapter notes are binding. The chapter title "Articles of iron or steel" does not decide anything.

### 2.2 The heading that names the article (`HDG-9617`)
Source: `cbic-ch96`, page 7.
> "9617 VACUUM FLASKS AND OTHER VACUUM VESSELS, COMPLETE; PARTS THEREOF OTHER THAN GLASS INNERS"

The heading wording has no material limit, so it covers a flask whatever it is made of.

### 2.3 Tariff items under 9617 (`TL-961700xx`)
Source: `cbic-ch96`, page 7. Columns: tariff item, description, unit, standard rate.

| clause_id | Tariff item | Description (verbatim) | Unit |
|---|---|---|---|
| `TL-96170011` | 9617 00 11 | "---- Vacuum flasks having a capacity not exceeding 0.75 l" | kg. |
| `TL-96170012` | 9617 00 12 | "---- Vacuum flasks having a capacity exceeding 0.75 l" | kg. |
| `TL-96170013` | 9617 00 13 | "---- Casserol and other vacuum containers" | kg. |
| `TL-96170019` | 9617 00 19 | "---- Other" | kg. |
| `TL-96170090` | 9617 00 90 | "--- Parts (other than glass inners)" | kg. |

(The parent line: "9617 00 - Vacuum flasks and other vacuum vessels, complete; parts thereof other than glass inners:", then "--- Vacuum flasks and other vacuum vessels, complete:". The 9617 entries carry the marker "*w.e.f. 1.1.2022", the HS 2022 amendment.)

### 2.4 The note that removes it from Chapter 73 (`SEC-XV-NOTE-1`, item (m))
Source: `cbic-sec-xv`, page 1. Chapter 73 is in Section XV.
> "1. This Section does not cover : … (m) hand sieves, buttons, pens, pencil-holders, pen nibs, monopods, bipods, tripods and similar articles or other articles of Chapter 96 (miscellaneous manufactured articles); or"

**Why it matters:** a vacuum flask is an article of Chapter 96 (heading 9617). So Section XV, and with it heading 7323, does not cover it, even though the flask is mostly stainless steel. This note is the "provision the request never mentions" (spec §5).

### 2.5 The material-first trap (`HDG-7323`, `TL-73239390`)
Source: `cbic-ch73`, page 12.
> "7323 TABLE, KITCHEN OR OTHER HOUSEHOLD ARTICLES AND PARTS THEREOF, OF IRON OR STEEL; IRON OR STEEL WOOL; POT SCOURERS AND SCOURING OR POLISHING PADS, GLOVES AND THE LIKE, OF IRON OR STEEL"
> "7323 93 -- Of stainless steel :" … "7323 93 90 --- Other"

A material-first search lands here (7323 93 90). That answer is **wrong** because of 2.4.

### 2.6 Chapter 73 and Chapter 96 notes checked
- Chapter 73 Notes 1–2 (`CH73-NOTE-1`, `CH73-NOTE-2`) only define "cast iron" and "wire". They neither include nor exclude vacuum flasks.
- Chapter 96 Note 1 (`CH96-NOTE-1`) lists what Chapter 96 does **not** cover, items (a)–(m). Vacuum flasks are not among them, so nothing pushes 9617 back out. Note 1(d) excludes "parts of general use, as defined in Note 2 of Section XV, of base metal", which does not apply to a complete flask.
- Chapter 96 Notes 2–4 concern headings 9602, 9603 and precious-metal content. They are not relevant.
- **Section XX has no section notes.** In the Chapter 94 PDF, page 1, the title "SECTION XX MISCELLANEOUS MANUFACTURED ARTICLES" is followed directly by "CHAPTER 94".

### 2.7 GRI 6: choosing the tariff item inside 9617 (`GRI-6`)
Source: `cbic-gri`, page 31.
> "For legal purposes, the classification of goods in the sub-headings of a heading shall be determined according to the terms of those sub-headings and any related sub-headings Notes and, mutatis mutandis, to the above rules, on the understanding that only sub-headings at the same level are comparable."

Inside 9617, the only feature that separates 9617 00 11 from 9617 00 12 is **capacity (0.75 l)**. Material does not matter at this level.

### 2.8 GRI 3: why it is not needed here (`GRI-3(a)`, `GRI-3(b)`)
Source: `cbic-gri`, page 30. GRI 3 applies only when goods are "prima facie, classifiable under two or more headings". After Section XV Note 1(m), 7323 is no longer a candidate, so only 9617 remains and **GRI 3 is not reached**. (The steel inner and plastic body might tempt someone into a GRI 3(b) "essential character" argument. That argument is not needed, because GRI 1 decides the case.)

### 2.9 Export policy (`EXP-GN-1`, proposed ID; see §5)
DGFT Schedule 2, Chapter 96 (`dgft-sch2`, page 117) has exactly **one** row: 9602 00 30 (empty gelatin capsules). **No row covers 9617**, and Chapter 73 has no rows at all. So the general rule applies.

Source: `dgft-sch2-gn`, page 3, General Note 1 "Free Exportability":
> "All goods other than the entries in the export licensing schedule along with its appendices are freely exportable. The free exportability is, however, subject to any other law for the time being in force. Goods not listed in the Schedule are deemed to be freely exportable without conditions under the Foreign Trade (Development and Regulations) Act, 1992 …"

Meaning of "Free" (`dgft-sch2-read`, page 2): "Export is permitted without a license from DGFT."

## 3. Classification path (reference reasoning)

1. **Article:** vacuum flask. **Materials:** stainless steel (inner and outer vessel), moulded plastic (outer body).
2. **GRI 1:** read the terms of the headings and the notes. Heading 9617 names "vacuum flasks". Heading 7323 (household articles *of iron or steel*) is a candidate only because of the material.
3. **Section XV Note 1(m):** Section XV does not cover "other articles of Chapter 96", so 7323 is excluded.
4. **Chapter 96 Note 1:** does not exclude vacuum flasks, so 9617 stands. GRI 3 is not reached.
5. **GRI 6:** choose the tariff item by capacity: ≤ 0.75 l gives 9617 00 11, > 0.75 l gives 9617 00 12.
6. **Export policy:** 9617 is not listed in Schedule 2, so General Note 1 makes it **Free**.

## 4. Test values and reference answers

The §4.1 sentence **does not state a capacity**, and the 8-digit item depends on it. So we propose two test requests. **[CONFIRM which one is the demonstration reference.]** Our recommendation is **4.1-B as the main demo case**, with 4.1-A shown as the escalate-instead-of-guess behaviour.

Contract fields follow A.4. Material shares are our own test values, not corpus facts.

### 4.1-A: the exact sentence (no capacity)
```json
{
  "client_ref": "EVAL1-4.1-A",
  "product_description": "Stainless steel vacuum flask with a moulded plastic outer body.",
  "materials": [ { "name": "stainless steel", "share_pct": 70 }, { "name": "plastic", "share_pct": 30 } ],
  "destination_country": "AE",
  "quantity": 100,
  "unit": "PCS"
}
```
Reference answer:
- `route`: **seek-product-clarification**. The heading is certain, but the tariff item needs the capacity.
- `heading`: **9617**. `proposed_hs_code`: `null` (candidates 96170011 / 96170012).
- `gri_applied`: `["GRI-1", "GRI-6"]`
- citations: `GRI-1`, `HDG-9617`, `SEC-XV-NOTE-1` (item m), `TL-96170011`, `TL-96170012`
- `export_policy`: **Free** (`EXP-GN-1`). This holds for both candidate items.
- Must **not** be 7323 93 90.

### 4.1-B: the same sentence with capacity (recommended demo reference)
```json
{
  "client_ref": "EVAL1-4.1-B",
  "product_description": "Stainless steel vacuum flask with a moulded plastic outer body. Capacity 500 ml.",
  "materials": [ { "name": "stainless steel", "share_pct": 70 }, { "name": "plastic", "share_pct": 30 } ],
  "intended_use": "Household drinks flask for retail sale",
  "destination_country": "AE",
  "quantity": 100,
  "unit": "PCS"
}
```
Reference answer:
- `route`: **clear-for-filing** (only if verification passes, per the A.5 invariant)
- `heading`: **9617**. `proposed_hs_code`: **96170011**
- `gri_applied`: `["GRI-1", "GRI-6"]`
- citations: `GRI-1`, `HDG-9617`, `SEC-XV-NOTE-1` (item m), `GRI-6`, `TL-96170011`
- `export_policy`: `{ "policy": "Free", "conditions": "Not listed in Schedule 2; freely exportable under General Note 1", "clause_id": "EXP-GN-1" }`

If the faculty prefers the bare sentence to produce `clear-for-filing`, the only defensible way is to assume a capacity, and we would rather not. **[CONFIRM]**

Member 3 reached the same conclusion independently from the agent side (contract change #12). Their variant uses "Capacity 1 litre.", which gives `clear-for-filing` with **96170012** (> 0.75 l). The evaluation set (`eval/scenarios.jsonl`) contains all three: S01 (no capacity → seek clarification), S02 (500 ml → 96170011) and S03 (1 litre → 96170012).

## 5. Open points for faculty confirmation

1. **DGFT Schedule 2 version.** The only consolidated chapter-wise file is headed ITC (HS) 2018. Is it acceptable, or should we use another file? (A 2024 harmonised draft exists. We have not yet checked every later amendment notification for Chapters 73 and 96.)
2. **Reference answer for §4.1:** 4.1-A (seek clarification on capacity) or 4.1-B (500 ml, so 96170011, clear-for-filing)?
3. **Clause ID for the default export policy.** The shared contract only defines `EXP-<8 digits>` for Schedule 2 rows. 9617 has no row, so its policy comes from General Note 1. We propose the ID `EXP-GN-1`, logged as change #13 in `docs/contract_changes.md` for the team to agree.
4. **Section XV notes source.** They are printed at the start of the Chapter 72 PDF. We index only those notes, not Chapter 72.
