import os
from pathlib import Path

import pytest

from retriever import config


@pytest.fixture(scope="session")
def settings():
    return config.load()


@pytest.fixture(scope="session")
def chunks(settings):
    from retriever.ingest.parsers import parse_corpus

    parsed, _ = parse_corpus(settings.corpus_dir)
    return parsed


@pytest.fixture(scope="session")
def client(settings):
    if not settings.manifest_path.exists():
        pytest.skip("index not built; run `python -m retriever.ingest build` first")
    from fastapi.testclient import TestClient

    from retriever.app import app

    with TestClient(app) as c:
        yield c
