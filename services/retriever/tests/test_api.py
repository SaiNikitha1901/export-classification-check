"""HTTP contract A.7 against the built index (tests listed in the Member 2 brief, B.3)."""


def test_clause_9617(client):
    r = client.get("/clause/HDG-9617", headers={"X-Correlation-ID": "test-cid"})
    assert r.status_code == 200
    assert r.headers["X-Correlation-ID"] == "test-cid"
    p = r.json()["passages"][0]
    assert "VACUUM FLASKS" in p["text"] and p["kind"] == "heading"
    assert set(p) == {"passage_id", "clause_id", "kind", "section", "chapter", "heading", "title", "text", "doc_id",
                      "doc_version", "page", "score"}


def test_clause_prefix_and_404(client):
    assert {p["clause_id"] for p in client.get("/clause/GRI-3").json()["passages"]} == {"GRI-3(a)", "GRI-3(b)",
                                                                                         "GRI-3(c)"}
    assert client.get("/clause/HDG-8471").status_code == 404


def test_keyword_search_vacuum_flask_top3(client):
    r = client.post("/search", json={"query": "vacuum flask", "mode": "keyword", "k": 3})
    assert r.status_code == 200
    ids = [p["clause_id"] for p in r.json()["passages"]]
    assert "HDG-9617" in ids, ids


def test_hybrid_search_demo_sentence_finds_9617(client):
    q = "Stainless steel vacuum flask with a moulded plastic outer body."
    ids = [p["clause_id"] for p in client.post("/search", json={"query": q, "k": 8}).json()["passages"]]
    assert any(i in ("HDG-9617", "TL-96170011", "TL-96170012") for i in ids), ids


def test_search_filters(client):
    r = client.post("/search", json={"query": "articles of iron or steel", "kinds": ["heading"], "chapters": ["96"]})
    assert all(p["kind"] == "heading" and p["chapter"] == "96" for p in r.json()["passages"])
    assert client.post("/search", json={"query": "x", "mode": "fuzzy"}).status_code == 422


def test_notes_applicable_7323_has_section_xv_note_1(client):
    body = client.get("/notes/applicable/HDG-7323").json()
    ids = [p["clause_id"] for p in body["passages"]]
    assert "SEC-XV-NOTE-1" in ids and "CH73-NOTE-1" in ids
    note1 = " ".join(p["text"] for p in body["passages"] if p["clause_id"] == "SEC-XV-NOTE-1")
    assert "other articles of Chapter 96" in note1


def test_notes_applicable_9617_has_chapter_96_notes_only(client):
    ids = [p["clause_id"] for p in client.get("/notes/applicable/TL-96170011").json()["passages"]]
    assert "CH96-NOTE-1" in ids and not any(i.startswith("SEC-XV") for i in ids)


def test_policy_default_free_for_9617(client):
    body = client.get("/policy/96170011").json()
    assert body["basis"] == "default" and body["policy"] == "Free" and body["tariff_item_exists"] is True
    assert body["passages"][0]["clause_id"] == "EXP-GN-1"


def test_policy_schedule_row_and_out_of_scope(client):
    body = client.get("/policy/96020030").json()
    assert body["basis"] == "schedule_row" and body["passages"][0]["clause_id"] == "EXP-96020030"
    assert client.get("/policy/84713010").status_code == 404


def test_index_info(client):
    info = client.get("/index/info").json()
    assert info["built_at"] and info["chunk_count"] > 400 and info["embed_model"]
    assert {s["doc_id"] for s in info["sources"]} >= {"cbic-gri", "cbic-ch96", "dgft-sch2"}
