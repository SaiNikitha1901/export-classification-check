"""CLI: docker compose run --rm retriever python -m retriever.ingest build|status|reembed|chunks

  build [--if-missing]    parse + embed; idempotent (a second run embeds nothing)
  status                  manifest, active collection, collection sizes
  reembed --model NAME    new collection for NAME from stored chunks, then atomic switch
  chunks [--clause ID]    print parsed chunks (debugging / Evaluation 1 evidence)
"""
from __future__ import annotations

import argparse
import json
import sys

from ecs_common import setup_logging

from retriever import config
from retriever.ingest import pipeline


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m retriever.ingest")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--if-missing", action="store_true", help="do nothing if an index already exists")
    sub.add_parser("status")
    r = sub.add_parser("reembed")
    r.add_argument("--model", required=True)
    c = sub.add_parser("chunks")
    c.add_argument("--clause", help="only this clause_id (prefix match)")
    args = p.parse_args(argv)

    settings = config.load()
    setup_logging(settings.service_name + "-ingest", settings.log_level)
    if args.cmd == "build":
        out = pipeline.build(settings, if_missing=args.if_missing)
    elif args.cmd == "status":
        out = pipeline.status(settings)
    elif args.cmd == "reembed":
        out = pipeline.reembed(settings, args.model)
    else:
        rows = pipeline.read_chunks(settings.chunks_path)
        for row in rows:
            if not args.clause or row["clause_id"].startswith(args.clause):
                print(json.dumps(row, ensure_ascii=False))
        return 0
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
