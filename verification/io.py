import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_contract(spec_path=None, schema_path=None):
    spec_path = Path(spec_path) if spec_path else ROOT / "contract/specification.json"
    schema_path = Path(schema_path) if schema_path else ROOT / "contract/schema.json"
    spec = json.loads(spec_path.read_text(), object_pairs_hook=strict_object)
    schema = json.loads(schema_path.read_text(), object_pairs_hook=strict_object)
    from verification.contract import validate
    return spec, validate(spec, schema)


def read_document(path):
    return (json.loads(Path(path).read_text(), object_pairs_hook=strict_object)
            if path else json.load(__import__("sys").stdin, object_pairs_hook=strict_object))


def strict_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def write_document(value, path=None):
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    if path:
        Path(path).write_text(serialized)
    else:
        print(serialized, end="")
