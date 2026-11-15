"""Prompts are versioned files: prompts/<name>/<version>.yaml (L2).

PROMPT_VERSION picks versions, e.g. "classifier@v2" or "classifier@v2,verifier@v1".
Prompts not named use v1. Templates use $var (string.Template) so JSON braces need no escaping.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from string import Template

import yaml

PROMPTS_DIR = Path(os.environ.get("PROMPTS_DIR", "/srv/prompts"))
NAMES = ("extractor", "classifier", "verifier")


@lru_cache(maxsize=32)
def load(name: str, version: str) -> dict:
    data = yaml.safe_load((PROMPTS_DIR / name / f"{version}.yaml").read_text())
    data["id"] = f"{name}@{version}"
    return data


def resolve(prompt_version: str) -> dict[str, dict]:
    """Map each prompt name to its loaded prompt for this run."""
    chosen = {n: "v1" for n in NAMES}
    for part in filter(None, (p.strip() for p in prompt_version.split(","))):
        name, _, version = part.partition("@")
        if name not in chosen or not version:
            raise ValueError(f"bad PROMPT_VERSION entry: {part!r}")
        chosen[name] = version
    return {n: load(n, v) for n, v in chosen.items()}


def render(template: str, **values) -> str:
    return Template(template).substitute(**values)
