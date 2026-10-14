import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from integration.mutations import MutationError, apply_mutation, validate_control_bindings


ROOT = Path(__file__).resolve().parents[2]
# reports/ is untracked, so a fresh clone (CI) has no temporary-directory parent yet.
(ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)
MATRIX_PATH = ROOT / "integration" / "mutation_matrix.json"


def setUpModule():
    (ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)


class IsolatedMutationPatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = json.loads(MATRIX_PATH.read_text())

    def candidate_with_anchor_files(self, parent: Path):
        candidate = parent / "candidate"
        sources = {}
        for mutation in self.matrix["mutations"]:
            for language, anchor in mutation["anchors"].items():
                sources.setdefault((language, anchor["path"]), []).append(anchor)
        for (language, relative_path), anchors in sources.items():
            path = candidate / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            keyword = "func" if language == "swift" else "fun"
            declarations = []
            for anchor in anchors:
                body = "\n".join("        " + line for line in anchor["before"].splitlines())
                declarations.append(
                    f"private {keyword} {anchor['function']}() {{\n{body}\n}}"
                )
            path.write_text("prefix\n" + "\n".join(declarations) + "\nsuffix\n")
        return candidate

    def test_each_mutation_writes_only_hash_bound_copied_sources(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            root = Path(temporary)
            candidate = self.candidate_with_anchor_files(root)
            original_files = {
                path.relative_to(candidate).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in candidate.rglob("*") if path.is_file()
            }

            for mutation in self.matrix["mutations"]:
                output = root / mutation["id"]
                result = apply_mutation(
                    candidate=candidate,
                    output=output,
                    mutation_id=mutation["id"],
                    matrix_path=MATRIX_PATH,
                )
                manifest = json.loads((output / "mutation.json").read_text())
                self.assertEqual(result, manifest)
                self.assertEqual(manifest["mutationId"], mutation["id"])
                self.assertEqual(set(manifest["files"]), set(mutation["anchors"]))
                for language, anchor in mutation["anchors"].items():
                    source = candidate / anchor["path"]
                    copied = output / language / anchor["path"]
                    self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), original_files[anchor["path"]])
                    for line in anchor["after"].splitlines():
                        self.assertIn(line, copied.read_text())
                    self.assertEqual(manifest["files"][language]["sourceSha256"], original_files[anchor["path"]])
                    self.assertEqual(
                        manifest["files"][language]["mutatedSha256"],
                        hashlib.sha256(copied.read_bytes()).hexdigest(),
                    )

    def test_n2_anchor_is_in_logout_caller_not_the_clear_helper(self):
        mutation = next(row for row in self.matrix["mutations"] if row["id"] == "N2-duplicate-deferred-clear")
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            for language, anchor in mutation["anchors"].items():
                source = candidate / anchor["path"]
                source.parent.mkdir(parents=True, exist_ok=True)
                keyword = "func" if language == "swift" else "fun"
                helper = f"private {keyword} clearThenPublishSignedOut() {{\n        {anchor['before']}\n}}"
                caller = f"private {keyword} handleLogout() {{\n        {anchor['before']}\n}}"
                source.write_text(helper + "\n" + caller + "\n")

            output = root / "n2-mutant"
            apply_mutation(candidate=candidate, output=output, mutation_id=mutation["id"], matrix_path=MATRIX_PATH)
            for language, anchor in mutation["anchors"].items():
                copied = (output / language / anchor["path"]).read_text()
                self.assertEqual(copied.count(anchor["before"]), 1)
                self.assertEqual(copied.count(anchor["after"]), 1)

    def test_patch_requires_exactly_one_anchor_match_before_writing(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            root = Path(temporary)
            candidate = self.candidate_with_anchor_files(root)
            mutation = self.matrix["mutations"][0]
            anchor = mutation["anchors"]["swift"]
            source = candidate / anchor["path"]
            source.write_text("no target here\n")

            with self.assertRaisesRegex(MutationError, "expected exactly one anchor"):
                apply_mutation(
                    candidate=candidate,
                    output=root / "missing-anchor",
                    mutation_id=mutation["id"],
                    matrix_path=MATRIX_PATH,
                )
            self.assertFalse((root / "missing-anchor").exists())

            source.write_text(anchor["before"] + "\n" + anchor["before"] + "\n")
            with self.assertRaisesRegex(MutationError, "expected exactly one anchor"):
                apply_mutation(
                    candidate=candidate,
                    output=root / "duplicate-anchor",
                    mutation_id=mutation["id"],
                    matrix_path=MATRIX_PATH,
                )
            self.assertFalse((root / "duplicate-anchor").exists())

    def test_anchor_must_be_inside_the_declared_function(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            root = Path(temporary)
            candidate = self.candidate_with_anchor_files(root)
            mutation = self.matrix["mutations"][0]
            swift = mutation["anchors"]["swift"]
            kotlin = mutation["anchors"]["kotlin"]
            (candidate / swift["path"]).write_text(
                f"func unrelated() {{\n{swift['before']}\n}}\n"
            )
            (candidate / kotlin["path"]).write_text(
                f"fun {kotlin['function']}() {{\n{kotlin['before']}\n}}\n"
            )

            with self.assertRaisesRegex(MutationError, "declared function"):
                apply_mutation(
                    candidate=candidate,
                    output=root / "wrong-function",
                    mutation_id=mutation["id"],
                    matrix_path=MATRIX_PATH,
                )
            self.assertFalse((root / "wrong-function").exists())

            (candidate / swift["path"]).write_text(
                f"func {swift['function']}() {{}}\n{swift['before']}\n"
            )
            with self.assertRaisesRegex(MutationError, "declared function"):
                apply_mutation(
                    candidate=candidate,
                    output=root / "outside-function",
                    mutation_id=mutation["id"],
                    matrix_path=MATRIX_PATH,
                )
            self.assertFalse((root / "outside-function").exists())

    def test_patch_refuses_existing_output_and_source_path_escape(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            root = Path(temporary)
            candidate = self.candidate_with_anchor_files(root)
            mutation = self.matrix["mutations"][0]
            output = root / "existing"
            output.mkdir()
            (output / "keep.txt").write_text("keep")
            with self.assertRaisesRegex(MutationError, "output already exists"):
                apply_mutation(
                    candidate=candidate,
                    output=output,
                    mutation_id=mutation["id"],
                    matrix_path=MATRIX_PATH,
                )
            self.assertEqual((output / "keep.txt").read_text(), "keep")

    def test_mutation_witnesses_match_the_frozen_control_inventory(self):
        controls_path = ROOT / "integration" / "control-scenarios.json"
        self.assertIsNone(validate_control_bindings(MATRIX_PATH, controls_path))

        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            changed_matrix = Path(temporary) / "mutation_matrix.json"
            changed = json.loads(MATRIX_PATH.read_text())
            changed["mutations"][0]["expectedControls"]["CTRL-N1-NEW-LOGIN"] = ["I4"]
            changed_matrix.write_text(json.dumps(changed))
            with self.assertRaisesRegex(MutationError, "witness set disagrees"):
                validate_control_bindings(changed_matrix, controls_path)

    def test_malformed_matrix_witness_values_are_rejected_as_protocol_data(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            malformed_matrix = Path(temporary) / "mutation_matrix.json"
            changed = json.loads(MATRIX_PATH.read_text())
            changed["mutations"][0]["expectedControls"]["CTRL-N1-NEW-LOGIN"] = [{}]
            malformed_matrix.write_text(json.dumps(changed))

            with self.assertRaisesRegex(MutationError, "invalid witness set"):
                validate_control_bindings(
                    malformed_matrix,
                    ROOT / "integration" / "control-scenarios.json",
                )


if __name__ == "__main__":
    unittest.main()
