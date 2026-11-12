"""Structure-aware parsing: every legal unit the 4.1 case needs exists, with the right text and IDs."""
from collections import Counter


def by_id(chunks, cid):
    return [c for c in chunks if c.clause_id == cid]


def test_clause_ids_unique_except_split_notes(chunks):
    dup = {k: v for k, v in Counter(c.clause_id for c in chunks).items() if v > 1}
    for cid in dup:
        assert all(c.meta.get("parts") for c in by_id(chunks, cid)), cid


def test_all_gri_rules_present(chunks):
    want = {"GRI-1", "GRI-2(a)", "GRI-2(b)", "GRI-3(a)", "GRI-3(b)", "GRI-3(c)", "GRI-4", "GRI-5(a)", "GRI-5(b)",
            "GRI-6"}
    assert want == {c.clause_id for c in chunks if c.kind == "gri"}
    assert "terms of the headings and any relative Section or Chapter Notes" in by_id(chunks, "GRI-1")[0].text


def test_heading_9617_names_vacuum_flasks(chunks):
    [h] = by_id(chunks, "HDG-9617")
    assert h.text.startswith("9617 VACUUM FLASKS AND OTHER VACUUM VESSELS")
    assert h.chapter == "96" and h.section == "XX"
    assert "96170011" in h.meta["tariff_items"]


def test_tariff_item_96170011(chunks):
    [t] = by_id(chunks, "TL-96170011")
    assert "Vacuum flasks having a capacity not exceeding 0.75 l" in t.text
    assert "%" not in t.text                      # duty rates are stripped (spec §13: no duty calculation)


def test_section_xv_note_1_excludes_chapter_96(chunks):
    text = " ".join(c.text for c in by_id(chunks, "SEC-XV-NOTE-1"))
    assert "This Section does not cover" in text
    assert "other articles of Chapter 96" in text


def test_material_trap_heading_7323_exists(chunks):
    [h] = by_id(chunks, "HDG-7323")
    assert "HOUSEHOLD ARTICLES" in h.text and "73239390" in h.meta["tariff_items"]


def test_export_policy_rows(chunks):
    [gn] = by_id(chunks, "EXP-GN-1")
    assert "Goods not listed in the Schedule are deemed to be freely exportable" in gn.text
    rows = [c for c in chunks if c.kind == "export_policy" and c.clause_id[4:].isdigit()]
    assert [r.clause_id for r in rows] == ["EXP-96020030"]       # the only Schedule 2 row in Ch 73/96
    assert "Remdesivir" not in rows[0].text                        # later-inserted rows must not leak in


def test_chunk_ids_are_deterministic(settings, chunks):
    from retriever.ingest.parsers import parse_corpus

    again, _ = parse_corpus(settings.corpus_dir)
    assert [c.passage_id for c in again] == [c.passage_id for c in chunks]
