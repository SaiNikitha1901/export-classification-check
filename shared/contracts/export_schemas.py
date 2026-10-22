"""Write the published JSON schemas next to the models: python -m contracts.export_schemas"""
import json
from pathlib import Path

from contracts import Passage, ProductRequest, Result

SCHEMAS = {"request": ProductRequest, "result": Result, "passage": Passage}


def render(model) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    here = Path(__file__).parent
    for name, model in SCHEMAS.items():
        (here / f"{name}.schema.json").write_text(render(model))
        print(f"wrote {name}.schema.json")


if __name__ == "__main__":
    main()
