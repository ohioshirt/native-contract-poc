"""Apply exact, evaluator-owned native mutation anchors in isolated source copies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile


class MutationError(ValueError):
    """The frozen mutation request or its source anchor is invalid."""


LANGUAGES = {"swift", "kotlin"}
MUTATION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_MODIFIERS = r"(?:(?:private|internal|public|fileprivate|open|final|override|suspend|inline|operator|tailrec|external|expect|actual)\s+)*"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_matrix(path: Path) -> tuple[dict, bytes]:
    try:
        raw = Path(path).read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise MutationError(f"mutation matrix is unavailable or invalid: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"version", "mutations"}:
        raise MutationError("mutation matrix must contain only version and mutations")
    if type(document["version"]) is not int or document["version"] != 1:
        raise MutationError("unsupported mutation matrix version")
    rows = document["mutations"]
    if not isinstance(rows, list) or not rows:
        raise MutationError("mutation matrix must contain a non-empty mutations array")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise MutationError("each mutation must have a string id")
        mutation_id = row["id"]
        if MUTATION_ID.fullmatch(mutation_id) is None or mutation_id in seen:
            raise MutationError("mutation IDs must be unique frozen ASCII labels")
        seen.add(mutation_id)
        anchors = row.get("anchors")
        if not isinstance(anchors, dict) or set(anchors) != LANGUAGES:
            raise MutationError(f"{mutation_id} must define exactly Swift and Kotlin anchors")
        for language, anchor in anchors.items():
            if not isinstance(anchor, dict) or set(anchor) != {"path", "function", "before", "after"}:
                raise MutationError(f"{mutation_id}/{language} anchor fields are invalid")
            source_path = anchor["path"]
            if (
                not isinstance(source_path, str)
                or not source_path
                or Path(source_path).is_absolute()
                or ".." in Path(source_path).parts
                or "\\" in source_path
            ):
                raise MutationError(f"{mutation_id}/{language} source path must be candidate-relative")
            if not isinstance(anchor["function"], str) or not anchor["function"]:
                raise MutationError(f"{mutation_id}/{language} function anchor is required")
            if not isinstance(anchor["before"], str) or not anchor["before"]:
                raise MutationError(f"{mutation_id}/{language} exact source anchor is required")
            if not isinstance(anchor["after"], str) or not anchor["after"] or anchor["before"] == anchor["after"]:
                raise MutationError(f"{mutation_id}/{language} replacement must differ from its anchor")
    return document, raw


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _function_source(source: str, language: str, function: str) -> str:
    keyword = "func" if language == "swift" else "fun"
    signature = re.compile(rf"(?m)^[ \t]*{_MODIFIERS}{keyword}\s+{re.escape(function)}\s*\(")
    declarations = list(re.finditer(rf"(?m)^[ \t]*{_MODIFIERS}(?:func|fun)\s+[A-Za-z_][A-Za-z0-9_]*\s*\(", source))
    matches = [match for match in declarations if signature.match(source, match.start())]
    if len(matches) != 1:
        raise MutationError(
            f"expected exactly one anchor in declared function {function}; "
            f"found {len(matches)} matching function declarations"
        )
    selected = matches[0]
    following = next((match for match in declarations if match.start() > selected.start()), None)
    opening = source.find("{", selected.end())
    if opening < 0 or (following is not None and opening >= following.start()):
        raise MutationError(f"declared function {function} has no braced body")
    end = _matching_brace_end(source, opening)
    if end is None:
        raise MutationError(f"declared function {function} has an unterminated body")
    return source[selected.start():end]


def _matching_brace_end(source: str, opening: int) -> int | None:
    depth = 0
    index = opening
    quote = None
    quote_hashes = 0
    escaped = False
    line_comment = False
    block_depth = 0
    while index < len(source):
        if line_comment:
            if source[index] == "\n":
                line_comment = False
            index += 1
            continue
        if block_depth:
            if source.startswith("/*", index):
                block_depth += 1
                index += 2
            elif source.startswith("*/", index):
                block_depth -= 1
                index += 2
            else:
                index += 1
            continue
        if quote is not None:
            closing = quote + ("#" * quote_hashes)
            if escaped:
                escaped = False
                index += 1
            elif quote_hashes == 0 and source[index] == "\\":
                escaped = True
                index += 1
            elif source.startswith(closing, index):
                index += len(closing)
                quote = None
                quote_hashes = 0
            else:
                index += 1
            continue
        if source.startswith("//", index):
            line_comment = True
            index += 2
        elif source.startswith("/*", index):
            block_depth = 1
            index += 2
        elif source.startswith('"""', index):
            quote = '"""'
            index += 3
        elif source[index] in {'"', "'"}:
            quote = source[index]
            cursor = index - 1
            while cursor >= 0 and source[cursor] == "#":
                quote_hashes += 1
                cursor -= 1
            index += 1
        elif source[index] == "{":
            depth += 1
            index += 1
        elif source[index] == "}":
            depth -= 1
            index += 1
            if depth == 0:
                return index
        else:
            index += 1
    return None


def _anchor_matches(source: str, anchor: str) -> list[re.Match[str]]:
    """Match frozen source lines while ignoring only their block indentation."""
    lines = anchor.splitlines()
    if not lines or any(not line.strip() for line in lines):
        return []
    normalized = [line.lstrip(" \t") for line in lines]
    pattern = r"(?m)^[ \t]*" + re.escape(normalized[0])
    for line in normalized[1:]:
        pattern += r"\r?\n[ \t]*" + re.escape(line)
    return list(re.finditer(pattern, source))


def _indented_replacement(anchor_match: re.Match[str], replacement: str) -> str:
    source_lines = anchor_match.group(0).splitlines()
    indents = [line[:len(line) - len(line.lstrip(" \t"))] for line in source_lines]
    replacement_lines = [line.lstrip(" \t") for line in replacement.splitlines()]
    if len(replacement_lines) != len(indents):
        indents = [indents[0]] * len(replacement_lines)
    return "\n".join(indent + line for indent, line in zip(indents, replacement_lines))


def validate_control_bindings(matrix_path: Path, controls_path: Path) -> None:
    """Require every frozen control to have the mutation's exact witness set."""
    matrix, _ = _load_matrix(Path(matrix_path))
    try:
        controls_document = json.loads(Path(controls_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise MutationError(f"control inventory is unavailable or invalid: {exc}") from exc
    if (
        not isinstance(controls_document, dict)
        or controls_document.get("version") != 1
        or not isinstance(controls_document.get("controls"), list)
    ):
        raise MutationError("control inventory has an invalid top-level shape")
    controls = {}
    for row in controls_document["controls"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise MutationError("control inventory contains an invalid row")
        control_id = row["id"]
        witnesses = row.get("witnessInvariants")
        if (
            control_id in controls
            or not isinstance(witnesses, list)
            or not witnesses
            or any(not isinstance(value, str) or not re.fullmatch(r"I[1-9][0-9]*", value) for value in witnesses)
            or len(witnesses) != len(set(witnesses))
        ):
            raise MutationError("control inventory contains duplicate IDs or invalid witness sets")
        controls[control_id] = witnesses

    matrix_controls = {}
    for mutation in matrix["mutations"]:
        expected = mutation.get("expectedControls")
        if not isinstance(expected, dict) or not expected:
            raise MutationError(f"{mutation['id']} has no expected control witnesses")
        for control_id, witnesses in expected.items():
            if not isinstance(control_id, str) or not control_id:
                raise MutationError(f"{mutation['id']} has an invalid control ID")
            if control_id in matrix_controls:
                raise MutationError(f"control {control_id} is bound by more than one mutation")
            if (
                not isinstance(witnesses, list)
                or not witnesses
                or any(not isinstance(value, str) or not re.fullmatch(r"I[1-9][0-9]*", value) for value in witnesses)
                or len(witnesses) != len(set(witnesses))
            ):
                raise MutationError(f"{mutation['id']} has an invalid witness set for {control_id}")
            matrix_controls[control_id] = witnesses

    if set(matrix_controls) != set(controls):
        raise MutationError("mutation matrix control inventory is incomplete or has unknown controls")
    for control_id, expected in controls.items():
        if matrix_controls[control_id] != expected:
            raise MutationError(f"{control_id} mutation witness set disagrees with frozen control inventory")


def apply_mutation(*, candidate: Path, output: Path, mutation_id: str, matrix_path: Path) -> dict:
    """Apply one mutation only after both language anchors validate exactly once.

    The candidate is read-only. The new tree is staged beside the destination and
    atomically renamed into place only after every replacement and digest succeeds.
    """
    if not isinstance(mutation_id, str) or MUTATION_ID.fullmatch(mutation_id) is None:
        raise MutationError("mutationId must be a frozen ASCII label")
    candidate = Path(candidate).resolve(strict=True)
    output = Path(output).absolute()
    output_parent = output.parent.resolve(strict=True)
    output = output_parent / output.name
    if output.exists():
        raise MutationError("output already exists")
    if _inside(output, candidate) or _inside(candidate, output):
        raise MutationError("mutation output and candidate must be disjoint trees")

    matrix, matrix_bytes = _load_matrix(Path(matrix_path))
    row = next((item for item in matrix["mutations"] if item["id"] == mutation_id), None)
    if row is None:
        raise MutationError(f"unknown mutationId: {mutation_id}")

    selected = {}
    for language in sorted(LANGUAGES):
        anchor = row["anchors"][language]
        requested = candidate / anchor["path"]
        try:
            source = requested.resolve(strict=True)
            source.relative_to(candidate)
        except (OSError, ValueError) as exc:
            raise MutationError(f"{mutation_id}/{language} anchor source escapes or is missing") from exc
        if not source.is_file():
            raise MutationError(f"{mutation_id}/{language} anchor source is not a regular file")
        before_bytes = source.read_bytes()
        try:
            before_text = before_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MutationError(f"{mutation_id}/{language} anchor source is not UTF-8") from exc
        function_text = _function_source(before_text, language, anchor["function"])
        matches = _anchor_matches(function_text, anchor["before"])
        count = len(matches)
        if count != 1:
            raise MutationError(
                f"{mutation_id}/{language} expected exactly one anchor match in declared function "
                f"{anchor['function']}, found {count}"
            )
        match = matches[0]
        replacement = _indented_replacement(match, anchor["after"])
        changed_function = function_text[:match.start()] + replacement + function_text[match.end():]
        after_text = before_text.replace(function_text, changed_function, 1)
        selected[language] = {
            "anchor": anchor,
            "source": source,
            "beforeBytes": before_bytes,
            "afterBytes": after_text.encode("utf-8"),
        }

    output_parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.mutation-", dir=output_parent))
    try:
        files = {}
        for language, item in selected.items():
            anchor = item["anchor"]
            destination = stage / language / anchor["path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(item["afterBytes"])
            files[language] = {
                "path": anchor["path"],
                "function": anchor["function"],
                "sourceSha256": _sha256(item["beforeBytes"]),
                "mutatedSha256": _sha256(item["afterBytes"]),
                "anchorSha256": _sha256(anchor["before"].encode("utf-8")),
                "replacementSha256": _sha256(anchor["after"].encode("utf-8")),
            }
        manifest = {
            "version": 1,
            "mutationId": mutation_id,
            "description": row["description"],
            "expectedControls": row["expectedControls"],
            "isolatedHelperRequired": row.get("isolatedHelperRequired", False),
            "matrixSha256": _sha256(matrix_bytes),
            "files": files,
        }
        (stage / "mutation.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.rename(stage, output)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply", help="apply one exact mutation into a fresh copied-source output")
    apply_parser.add_argument("--candidate", type=Path, required=True)
    apply_parser.add_argument("--output", type=Path, required=True)
    apply_parser.add_argument("--mutation", required=True)
    apply_parser.add_argument("--matrix", type=Path, default=Path(__file__).with_name("mutation_matrix.json"))
    args = parser.parse_args(argv)
    try:
        result = apply_mutation(
            candidate=args.candidate,
            output=args.output,
            mutation_id=args.mutation,
            matrix_path=args.matrix,
        )
    except MutationError as exc:
        parser.exit(2, f"mutation rejected: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
