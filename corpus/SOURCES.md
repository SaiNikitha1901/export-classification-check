# Corpus sources

All files in `corpus/raw/` are unmodified public documents downloaded from the official CBIC and DGFT websites on **2026-11-12**.
Every file has a text layer, so **no OCR was needed** (checked with `pypdf`: every page returns extractable text).

The project corpus is limited to the GRI, Customs Tariff Chapters 73 and 96 with their Section and Chapter notes, and the DGFT export policy for those chapters (spec §3).

| # | File (`corpus/raw/`) | Title | Publisher | Version / date | Pages | Used for | sha256 |
|---|---|---|---|---|---|---|---|
| 1 | `cbic_tariff_part1_general_notes_gri.pdf` | Customs Tariff, Part I: Customs Tariff Act 1975 + **General Rules for the Interpretation of Import Tariff** + General Explanatory Notes | CBIC | Tariff (as on 30.06.2025) | 41 | GRI 1–6 (pages 30–31) | `0821f495f9a8687dbd4a18eb3e0d9ae89566752b4c4942599abce529bf244353` |
| 2 | `cbic_tariff_ch72_with_section_xv_notes.pdf` | Customs Tariff, Section XV (Base metals) notes + Chapter 72 | CBIC | Tariff (as on 30.06.2025) edition; file carried over from 30.06.2024 | 31 | **Section XV Notes 1–8 only** (pages 1–2). Chapter 72 itself is out of scope and is not indexed | `5a2b0f3f17a229f2f3c03c7b145715da84dd9ab5a897e5a2060379b760a35112` |
| 3 | `cbic_tariff_ch73.pdf` | Customs Tariff, Chapter 73: Articles of iron or steel | CBIC | Tariff (as on 30.06.2025) edition; file carried over from 30.06.2024 | 18 | Chapter 73 notes, headings 7301–7326, tariff items | `f21a14313285a8657585b9085d332c21c42f2dccfac48078be47b56e60ebb793` |
| 4 | `cbic_tariff_ch94_section_xx_opening.pdf` | Customs Tariff, Section XX opening + Chapter 94 | CBIC | Tariff (as on 30.06.2025) edition; file carried over from 30.06.2024 | 6 | Evidence that **Section XX has no Section notes** (the section title is followed directly by Chapter 94). Chapter 94 is not indexed | `86b032c15f24c4384e6eaba627f16d9cb767904d75782422554c65e023500e26` |
| 5 | `cbic_tariff_ch96.pdf` | Customs Tariff, Chapter 96: Miscellaneous manufactured articles | CBIC | Tariff (as on 30.06.2025) edition; file carried over from 30.06.2024 | 9 | Chapter 96 notes, headings 9601–9620, tariff items | `7cb3a01215743d9208e7c92090992576aa332a6fd21202f40021a579fee543ac` |
| 6 | `dgft_itchs_schedule2_export_policy.pdf` | ITC (HS) Schedule 2: Chapter-wise Export Policy | DGFT | ITC (HS) 2018 Schedule 2, consolidated "New" file (pages headed "ITC (HS), 2018") | 126 | Export policy rows. Chapter 73 has **no** rows. Chapter 96 has **one** row (9602 00 30) | `4860966d9269061764306d92284d3b8386d4df05e27c6f524f520ec4cb575142` |
| 7 | `dgft_schedule2_general_notes.pdf` | General Notes to Export Policy | DGFT | ITC (HS) 2018 Schedule 2 | 6 | General Note 1 "Free Exportability": goods not listed are freely exportable | `df483994cf8638044f7598a31a3c7d7d198c57b9f845bdadb9bc187267c8e846` |
| 8 | `dgft_schedule2_how_to_read.pdf` | Explanatory Note for Row and Column Description of Schedule 2 | DGFT | ITC (HS) 2022 | 2 | Meaning of Free / Restricted / Prohibited / STE | `b04e40a2a84f5a1db1662dfbac5dcbfa0cc71ef80275fe2a2f18439dee3c0081` |

## Download URLs

CBIC's new site (`www.cbic.gov.in`) is a JavaScript app. The old `old.cbic.gov.in` host no longer resolves. The tariff tree comes from the site's own API, and each PDF is served as base64 inside a JSON body (`{"data": "<base64>"}`) at `https://www.cbic.gov.in/content/pdf/<CONTENTREPO path>`.

- Tariff index (API): `https://www.cbic.gov.in/api/cbic-content-msts/MTcyNDYy` (the "Tariff (as on 30.06.2025)" node; id 172462, base64-encoded)
- 1: `https://www.cbic.gov.in/content/pdf/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2025)/CUSTOMS_TARIFF_VOL-I/General-Notes.pdf`
- 2: `https://www.cbic.gov.in/content/pdf/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-72.pdf`
- 3: `https://www.cbic.gov.in/content/pdf/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-73.pdf`
- 4: `https://www.cbic.gov.in/content/pdf/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-94.pdf`
- 5: `https://www.cbic.gov.in/content/pdf/CONTENTREPO/Customs/Tariff/Tariff(ason30.06.2024)/CUSTOMS_TARIFF_VOL-I/chap-96.pdf`
- 6: `https://content.dgft.gov.in/Website/dgftprod/64c14faa-53ac-4387-bcf3-d355fee40bc8/Schedule%202%20-%20Export%20Policy%20New.pdf`
- 7: `https://content.dgft.gov.in/Website/gennote_0.pdf`
- 8: `https://content.dgft.gov.in/Website/how%20to%20read%20export%20policy.pdf`

Note on files 2–5: the 30.06.2025 tariff edition links to chapter PDFs stored in the `Tariff(ason30.06.2024)` folder. In other words, CBIC did not reissue these chapters in 2025. We record the edition as "as on 30.06.2025" and the file folder as 30.06.2024.

## Known limitations

- **DGFT Schedule 2 version.** The only consolidated, chapter-wise Schedule 2 PDF on the DGFT site has pages headed "ITC (HS), 2018". DGFT issued a *draft* harmonised Schedule 2 for ITC (HS) 2022 (Trade Notice 22/2024-25, 14.11.2024), and it amends Schedule 2 by notification from time to time. **We have not yet checked every later notification** for a new Chapter 73 or Chapter 96 row; that check is still open. **Faculty to confirm** that this file is an acceptable version.
- **Text-extraction artefacts.** In CBIC PDFs, `pypdf` sometimes splits words (`classific ation`, `V ACUUM`) and turns typographic quotes into `�`. The ingestion step normalises these. Quotes in our docs use the normalised text.

## Project spec documents (not part of the corpus)

| File (`docs/spec/`) | Source | sha256 |
|---|---|---|
| `MiniProject_07_Export_Classification_Check.pdf` | Course Google Drive folder | `cdefdf635781c10f2952afbd1ba8fd11ce1c71c4885ac0534b3732614f662f34` |
| `00_GLOSSARY.pdf` | Course Google Drive folder | `5b18ad51d081771d7e082938b900b6a690f237556ff527bb36d5abe7981367a6` |

The course Drive folder holds only the 15 project specs, `00_INDEX.pdf` and `00_GLOSSARY.pdf`. It contains **no corpus PDFs**.
