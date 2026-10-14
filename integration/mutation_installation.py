"""Create isolated, hash-bound native source trees for frozen negative controls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from integration.mutations import _load_matrix, apply_mutation


class MutationInstallationError(ValueError):
    """A copied mutant source tree could not be materialized exactly."""


HELPERS = {
    "N2-duplicate-deferred-clear": {
        "swift": "apps/ios-demo/MutationFixtures/N2DuplicateClear.swift",
        "kotlin": "apps/android-demo/MutationFixtures/N2DuplicateClear.kt",
        "swiftConformance": "N2DuplicateClearMutationHost",
        "kotlinConformance": "N2DuplicateClearMutationHost",
        "swiftCall": "debugClearThenScheduleDuplicate",
        "kotlinCall": "debugClearThenScheduleDuplicate",
    },
    "N4-false-logout-ack": {
        "swift": "apps/ios-demo/MutationFixtures/N4FalseLogout.swift",
        "kotlin": "apps/android-demo/MutationFixtures/N4FalseLogout.kt",
        "swiftConformance": "N4FalseLogoutMutationHost",
        "kotlinConformance": "N4FalseLogoutMutationHost<CommandReceipt>",
        "swiftCall": "debugFalseLogoutReceipt",
        "kotlinCall": "debugFalseLogoutReceipt",
    },
}

_IGNORED_COPY_NAMES = {
    ".git", ".gradle", ".build", ".swift-cache", "build", "__pycache__",
    "xcuserdata", "DerivedData", "reports", ".kotlin",
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _require_helper_host_methods(source: str, language: str, mutation_id: str) -> None:
    if language == "swift":
        names = {
            "N2-duplicate-deferred-clear": (
                "n2PerformNormalVerifiedLogout",
                "n2PauseBeforeDeferredControlClear",
                "n2PerformDuplicateClearAndRecord",
            ),
            "N4-false-logout-ack": (
                "n4PublishSignedOutWithoutStoreClear",
                "n4MakeCompletedLogoutReceipt",
            ),
        }[mutation_id]
        keyword = "func"
    else:
        names = {
            "N2-duplicate-deferred-clear": (
                "n2PerformNormalVerifiedLogout",
                "n2ScheduleDetachedEffect",
                "n2PauseBeforeDeferredControlClear",
                "n2PerformDuplicateClearAndRecord",
            ),
            "N4-false-logout-ack": (
                "n4PublishSignedOutWithoutStoreClear",
                "n4MakeCompletedLogoutReceipt",
            ),
        }[mutation_id]
        keyword = "fun"
    modifier = r"(?:override\s+)?" if language == "kotlin" else ""
    missing = [
        name for name in names
        if len(re.findall(rf"(?m)^\s*{modifier}{keyword}\s+{re.escape(name)}\s*\(", source)) != 1
    ]
    if missing:
        raise MutationInstallationError(
            "copied candidate must implement each frozen isolated helper adapter exactly once: "
            + ", ".join(missing)
        )


def mutation_for_control(*, control_id: str, matrix_path: Path) -> str:
    matrix, _ = _load_matrix(Path(matrix_path))
    matches = [row["id"] for row in matrix["mutations"] if control_id in row.get("expectedControls", {})]
    if len(matches) != 1:
        raise MutationInstallationError(f"{control_id} does not resolve to exactly one frozen mutation")
    return matches[0]


def _copytree(source: Path, destination: Path) -> None:
    def ignore(directory, names):
        return {name for name in names if name in _IGNORED_COPY_NAMES or name.endswith(".xcuserstate")}

    if destination.exists():
        raise MutationInstallationError("mutation workspace must be fresh")
    shutil.copytree(source, destination, ignore=ignore, symlinks=False)


def _copy_platform_candidate(candidate: Path, workspace: Path, platform: str) -> None:
    _copytree(candidate / "apps" / f"{platform}-demo", workspace / "apps" / f"{platform}-demo")
    if platform == "ios":
        _copytree(candidate / "ios", workspace / "ios")
    else:
        _copytree(candidate / "android" / "async-library", workspace / "android" / "async-library")
    _copytree(candidate / "integration", workspace / "integration")
    _copytree(candidate / "contract", workspace / "contract")


def _swift_helper_install(workspace: Path, mutation_id: str, helper_path: str, helper_bytes: bytes) -> dict:
    source_path = workspace / "apps/ios-demo/NativeContractDemo/Coordinator/SessionCoordinator.swift"
    source = source_path.read_text(encoding="utf-8")
    _require_helper_host_methods(source, "swift", mutation_id)
    helper = helper_bytes.decode("utf-8")
    protocol_name = HELPERS[mutation_id]["swiftConformance"]
    if re.search(rf"(?m)^extension\s+SessionCoordinator\s*:\s*{re.escape(protocol_name)}\b", source):
        raise MutationInstallationError("mutant helper conformance is already present")
    suffix = f"\n\n// Isolated evaluator helper: {mutation_id}\n{helper.rstrip()}\n\nextension SessionCoordinator: {protocol_name} {{}}\n"
    patched = source + suffix
    source_path.write_text(patched, encoding="utf-8")
    return {
        "helperPath": helper_path,
        "helperSha256": _sha(helper_bytes),
        "materializedPath": source_path.relative_to(workspace).as_posix(),
        "materializedSha256": _sha(patched.encode("utf-8")),
        "conformance": f"extension SessionCoordinator: {protocol_name} {{}}",
    }


def _kotlin_class_header_end(source: str, class_name: str) -> tuple[int, int]:
    matches = list(re.finditer(rf"(?m)^([ \t]*class\s+{re.escape(class_name)}\b)", source))
    if len(matches) != 1:
        raise MutationInstallationError(f"expected one Kotlin class declaration for {class_name}; found {len(matches)}")
    start = matches[0].start(1)
    cursor = matches[0].end(1)
    parens = 0
    angles = 0
    while cursor < len(source):
        char = source[cursor]
        if char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
        elif char == "<":
            angles += 1
        elif char == ">" and angles:
            angles -= 1
        elif char == "{" and parens == 0 and angles == 0:
            return start, cursor
        cursor += 1
    raise MutationInstallationError(f"Kotlin class {class_name} has no body")


def _kotlin_helper_install(workspace: Path, mutation_id: str, helper_path: str, helper_bytes: bytes) -> dict:
    root = workspace / "apps/android-demo/app/src/debug/java/nativecontract/demo/mutation"
    root.mkdir(parents=True, exist_ok=True)
    helper_output = root / Path(helper_path).name
    if helper_output.exists():
        raise MutationInstallationError("mutant helper destination already exists")
    helper_output.write_bytes(helper_bytes)

    source_path = workspace / "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/SessionCoordinator.kt"
    source = source_path.read_text(encoding="utf-8")
    _require_helper_host_methods(source, "kotlin", mutation_id)
    helper_config = HELPERS[mutation_id]
    protocol_name = helper_config["kotlinConformance"]
    short_protocol = protocol_name.split("<", 1)[0]
    package_match = re.search(r"(?m)^package\s+([A-Za-z0-9_.]+)\s*$", source)
    if package_match is None or len(re.findall(r"(?m)^package\s+", source)) != 1:
        raise MutationInstallationError("Kotlin coordinator must declare exactly one package")
    package_prefix = "nativecontract.demo.mutation"
    imports = [
        f"import {package_prefix}.{short_protocol}",
        f"import {package_prefix}.{helper_config['kotlinCall']}",
    ]
    for import_line in imports:
        if re.search(rf"(?m)^{re.escape(import_line)}\s*$", source):
            raise MutationInstallationError("mutant helper import is already present")
    adapter_names = {
        "N2-duplicate-deferred-clear": (
            "n2PerformNormalVerifiedLogout",
            "n2ScheduleDetachedEffect",
            "n2PauseBeforeDeferredControlClear",
            "n2PerformDuplicateClearAndRecord",
        ),
        "N4-false-logout-ack": (
            "n4PublishSignedOutWithoutStoreClear",
            "n4MakeCompletedLogoutReceipt",
        ),
    }[mutation_id]
    overridden = []
    for name in adapter_names:
        pattern = re.compile(rf"(?m)^([ \t]*)(override[ \t]+)?fun\s+{re.escape(name)}\s*\(")
        matches = list(pattern.finditer(source))
        if len(matches) != 1:
            raise MutationInstallationError(f"Kotlin helper adapter {name} is absent or duplicated")
        match = matches[0]
        if match.group(2) is None:
            insertion_point = match.start() + len(match.group(1))
            source = source[:insertion_point] + "override " + source[insertion_point:]
        overridden.append(name)
    insertion = package_match.end()
    source = source[:insertion] + "\n\n" + "\n".join(imports) + source[insertion:]
    class_start, body_open = _kotlin_class_header_end(source, "SessionCoordinator")
    header_text = source[class_start:body_open]
    if re.search(rf"\b{re.escape(short_protocol)}\b", header_text):
        raise MutationInstallationError("mutant coordinator interface is already installed")
    separator = ", " if re.search(r"\)\s*:", header_text) else " : "
    source = source[:body_open] + f"{separator}{protocol_name} " + source[body_open:]
    source_path.write_text(source, encoding="utf-8")
    return {
        "helperPath": helper_path,
        "helperSha256": _sha(helper_bytes),
        "materializedPath": helper_output.relative_to(workspace).as_posix(),
        "materializedSha256": _sha(helper_bytes),
        "coordinatorPath": source_path.relative_to(workspace).as_posix(),
        "coordinatorSha256": _sha(source.encode("utf-8")),
        "imports": imports,
        "overriddenAdapters": overridden,
        "conformance": protocol_name,
    }


def prepare_mutation_workspace(
    *, candidate: Path, workspace: Path, mutation_id: str, platform: str,
    matrix_path: Path | None = None,
) -> dict:
    """Patch one language in a fresh platform copy and materialize only its helper.

    The original candidate is read-only. The build workspace is an isolated copy;
    the opposite-language patched source and matrix manifest remain in provenance.
    """
    if platform not in {"ios", "android"}:
        raise MutationInstallationError("platform must be ios or android")
    candidate = Path(candidate).resolve(strict=True)
    workspace = Path(workspace).absolute()
    workspace_parent = workspace.parent.resolve(strict=True)
    workspace = workspace_parent / workspace.name
    if workspace.exists() or workspace.is_symlink():
        raise MutationInstallationError("mutation build workspace already exists")
    matrix_path = Path(matrix_path or candidate / "integration/mutation_matrix.json").resolve(strict=True)
    matrix, matrix_bytes = _load_matrix(matrix_path)
    mutation = next((row for row in matrix["mutations"] if row["id"] == mutation_id), None)
    if mutation is None:
        raise MutationInstallationError(f"unknown frozen mutation: {mutation_id}")

    with tempfile.TemporaryDirectory(prefix="native-contract-patches-") as temporary:
        patch_output = Path(temporary) / "patched-sources"
        patch_manifest = apply_mutation(
            candidate=candidate,
            output=patch_output,
            mutation_id=mutation_id,
            matrix_path=matrix_path,
        )
        _copy_platform_candidate(candidate, workspace, platform)
        language = "swift" if platform == "ios" else "kotlin"
        patch_row = patch_manifest["files"][language]
        relative_source = patch_row["path"]
        mutated_source = patch_output / language / relative_source
        source_target = workspace / relative_source
        if not source_target.is_file():
            raise MutationInstallationError(f"patched platform source is absent from copied workspace: {relative_source}")
        source_target.write_bytes(mutated_source.read_bytes())

        helper_provenance = None
        helper_config = HELPERS.get(mutation_id)
        if mutation.get("isolatedHelperRequired", False):
            if helper_config is None:
                raise MutationInstallationError("mutation requires an undeclared isolated helper")
            helper_path = helper_config[language]
            helper_bytes = (candidate / helper_path).read_bytes()
            if platform == "ios":
                helper_provenance = _swift_helper_install(workspace, mutation_id, helper_path, helper_bytes)
            else:
                helper_provenance = _kotlin_helper_install(workspace, mutation_id, helper_path, helper_bytes)

        final_source_bytes = source_target.read_bytes()
        return {
            "version": 1,
            "mutationId": mutation_id,
            "platform": platform,
            "matrixSha256": _sha(matrix_bytes),
            "patchManifest": patch_manifest,
            "patchedPlatformSource": {
                "path": relative_source,
                "originalSha256": patch_row["sourceSha256"],
                "anchorPatchedSha256": patch_row["mutatedSha256"],
                "materializedSha256": _sha(final_source_bytes),
            },
            "workspaceSourceSha256": _source_tree_sha256(workspace),
            "helper": helper_provenance,
            "candidateUnitTestPolicy": {
                "workspaceSourceTests": "included",
                "execution": "skipped-for-mutant-witness-build",
            },
            "workspaceRelativePath": workspace.relative_to(candidate).as_posix()
            if workspace.is_relative_to(candidate) else None,
            "workspacePath": str(workspace),
        }


__all__ = [
    "HELPERS",
    "MutationInstallationError",
    "mutation_for_control",
    "prepare_mutation_workspace",
]
