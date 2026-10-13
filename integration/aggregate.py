"""Portable, source-bound aggregation for split-platform native CI ledgers."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import tempfile

from integration import protocol_config, reproduce
from integration.check import check_control_trace, check_trace
from verification import change_protocol as protocol


IOS_STAGES = ["integration-red", "candidate-ios", "integration-controls", "legacy-full"]
ANDROID_STAGES = ["candidate-android", "integration-controls"]
CONTROL_STAGE = "integration-controls"


class AggregateError(ValueError):
    """Raised when a platform ledger cannot be bound to this candidate/run."""


def _json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregateError(f"required JSON artifact is unavailable: {path}") from exc
    return value


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_digest(manifest, candidate):
    """Recompute source integrity; allowed candidate-path edits remain explicit."""
    return protocol.check_sources(manifest, Path(candidate).resolve())


def _substitute_argv(stage, candidate, output):
    return [
        value.replace("{candidate}", str(candidate)).replace("{output}", str(output))
        for value in stage["argv"]
    ]


def _portable_attempt(root, candidate, manifest, manifest_digest, stage_id, suite_row, candidate_digest):
    """Recheck one attempt after artifact download without trusting producer paths."""
    stage = manifest["stages"].get(stage_id)
    if not isinstance(stage, dict):
        raise AggregateError(f"attempt names an undeclared stage: {stage_id}")
    attempt_id = "auto-" + stage_id
    output = Path(root) / attempt_id
    result_path = output / "result.json"
    result = _json(result_path)
    required = {
        "manifestDigest", "candidateDigest", "stageId", "attemptId", "outputDirectory",
        "argv", "cwd", "verdictProtocol", "metadata", "startedUtc", "startedNs",
        "exitCode", "timedOut", "artifacts", "evidence", "classification", "endedUtc",
        "durationSeconds",
    }
    if not isinstance(result, dict) or not required <= set(result) or set(result) - (required | {"detail"}):
        raise AggregateError(f"stage result has an invalid field set: {stage_id}")
    producer_root = result.get("cwd")
    producer_output = result.get("outputDirectory")
    if (
        not isinstance(producer_root, str) or not Path(producer_root).is_absolute()
        or not isinstance(producer_output, str) or not Path(producer_output).is_absolute()
        or Path(producer_output) != Path(producer_root) / manifest["outputRoot"] / attempt_id
    ):
        raise AggregateError(f"stage result output binding is inconsistent: {stage_id}")
    if (
        result.get("manifestDigest") != manifest_digest
        or result.get("candidateDigest") != candidate_digest
        or result.get("stageId") != stage_id
        or result.get("attemptId") != attempt_id
        or result.get("verdictProtocol") != stage["verdictProtocol"]
        or result.get("argv") != _substitute_argv(stage, producer_root, producer_output)
        or type(result.get("startedNs")) is not int or result["startedNs"] <= 0
        or type(result.get("exitCode")) is not int
        or type(result.get("timedOut")) is not bool
        or isinstance(result.get("durationSeconds"), bool)
        or not isinstance(result.get("durationSeconds"), (int, float))
        or not math.isfinite(result["durationSeconds"]) or result["durationSeconds"] < 0
    ):
        raise AggregateError(f"stage result does not match the frozen run: {stage_id}")
    if result.get("metadata") != manifest["metadata"]:
        raise AggregateError(f"stage metadata differs from the frozen run: {stage_id}")
    actual_evidence = protocol.captured_evidence(output, result["argv"], producer_root)
    if actual_evidence != result.get("evidence"):
        raise AggregateError(f"stage command/log evidence changed after execution: {stage_id}")
    actual_artifacts = protocol.read_artifacts(output, stage, result["startedNs"], verify_mtime=False)
    if actual_artifacts != result.get("artifacts"):
        raise AggregateError(f"stage artifacts changed after execution: {stage_id}")
    actual_classification = protocol.classify(stage, result["exitCode"], result["timedOut"], output)
    if actual_classification != result.get("classification"):
        raise AggregateError(f"stage verdict differs from its frozen artifacts: {stage_id}")
    if (
        suite_row.get("stageId") != stage_id
        or suite_row.get("attemptId") != attempt_id
        or suite_row.get("classification") != actual_classification
        or suite_row.get("manifestDigest") != manifest_digest
        or suite_row.get("candidateDigest") != candidate_digest
        or suite_row.get("outputDirectory") != result["outputDirectory"]
        or suite_row.get("argv") != result["argv"]
        or suite_row.get("cwd") != result["cwd"]
        or suite_row.get("verdictProtocol") != result["verdictProtocol"]
        or suite_row.get("bindingClassification") != "PASS"
        or suite_row.get("bindingResult", {}).get("bindingClassification") != "PASS"
        or suite_row.get("bindingResult", {}).get("manifestDigest") != manifest_digest
        or suite_row.get("bindingResult", {}).get("candidateDigest") != candidate_digest
    ):
        raise AggregateError(f"suite ledger does not bind checked attempt: {stage_id}")
    return result, output, stage


def _case_key(row):
    return (row.get("scenarioId"), row.get("variantId"))


def _read_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        values = [json.loads(line) for line in lines if line]
    except (OSError, json.JSONDecodeError) as exc:
        raise AggregateError(f"native trace artifact is unavailable or malformed: {path}") from exc
    if len(values) != len(lines) or not values:
        raise AggregateError(f"native trace artifact is empty or malformed: {path}")
    return values


def _index_case_rows(rows, *, label):
    if not isinstance(rows, list):
        raise AggregateError(f"{label} case inventory is malformed")
    result = {}
    for row in rows:
        key = _case_key(row) if isinstance(row, dict) else None
        if (
            key is None or not isinstance(key[0], str)
            or key in result
        ):
            raise AggregateError(f"{label} has a malformed or duplicate case identity")
        result[key] = row
    return result


def _verify_screenshot_manifest(platform_root):
    screenshot_manifest = _json(Path(platform_root) / "screenshots" / "manifest.json")
    screenshots = screenshot_manifest.get("screenshots")
    if not isinstance(screenshots, list):
        raise AggregateError("screenshot manifest is malformed")
    seen_screenshots = set()
    for row in screenshots:
        if (
            not isinstance(row, dict) or set(row) != {"path", "sha256"}
            or not isinstance(row["path"], str) or not isinstance(row["sha256"], str)
            or len(row["sha256"]) != 64 or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
            or row["path"] in seen_screenshots
        ):
            raise AggregateError("screenshot manifest row is malformed or duplicated")
        seen_screenshots.add(row["path"])
        screenshot = protocol.contained(Path(platform_root), row["path"])
        if not screenshot.is_file() or _sha256(screenshot) != row["sha256"]:
            raise AggregateError(f"screenshot evidence hash mismatch: {row['path']}")
    return screenshots


def _recheck_platform_histories(platform_root, platform, stage, candidate):
    """Replay every completed native history against the protected inventory."""
    scenario_rows = json.loads((candidate / "integration" / "scenarios.json").read_text())["scenarios"]
    control_rows = json.loads((candidate / "integration" / "control-scenarios.json").read_text())["controls"]
    controls_stage = "expectedControlWitnesses" in stage
    inventory = control_rows if controls_stage else scenario_rows
    inventory_by_id = {row["id"]: row for row in inventory}
    mutation_builds = {}
    control_mutation_ids = {}
    if controls_stage:
        from integration.mutation_installation import mutation_for_control, prepare_mutation_workspace
        matrix_path = candidate / "integration" / "mutation_matrix.json"
        for row in control_rows:
            control_mutation_ids[row["id"]] = mutation_for_control(control_id=row["id"], matrix_path=matrix_path)
        platform_report = _json(Path(platform_root) / "platform-report.json")
        for row in platform_report.get("mutationBuilds", []):
            mutation_id = row.get("mutationId") if isinstance(row, dict) else None
            if not isinstance(mutation_id, str) or mutation_id in mutation_builds:
                raise AggregateError("mutation build provenance has a duplicate or malformed ID")
            mutation_builds[mutation_id] = row
        expected_mutations = set(control_mutation_ids.values())
        if set(mutation_builds) != expected_mutations:
            raise AggregateError("mutation build provenance differs from the frozen control set")
        for mutation_id, build in mutation_builds.items():
            if (
                build.get("classification") != "BUILD_READY"
                or build.get("platform") != platform
                or not isinstance(build.get("workspaceSourceSha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", build["workspaceSourceSha256"])
                or not isinstance(build.get("buildHash"), str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", build["buildHash"])
            ):
                raise AggregateError(f"mutation build provenance is incomplete: {mutation_id}")
            with tempfile.TemporaryDirectory(prefix="native-aggregate-mutation-recheck-") as temporary:
                expected_provenance = prepare_mutation_workspace(
                    candidate=candidate,
                    workspace=Path(temporary) / "workspace",
                    mutation_id=mutation_id,
                    platform=platform,
                    matrix_path=matrix_path,
                )
            for field in (
                "matrixSha256", "patchManifest", "patchedPlatformSource", "helper",
                "workspaceSourceSha256", "candidateUnitTestPolicy",
            ):
                if build.get(field) != expected_provenance.get(field):
                    raise AggregateError(f"copied mutation {field} differs for {mutation_id}")
            build_commands = build.get("buildCommands")
            if not isinstance(build_commands, dict) or "unit-tests" in build_commands:
                raise AggregateError(f"mutant candidate unit tests were not excluded from build execution: {mutation_id}")
    contract = _json(candidate / "integration" / "contract.json")

    scenario_document = _json(Path(platform_root) / "scenario-results.json")
    if scenario_document.get("platform") != platform:
        raise AggregateError("scenario result artifact names another platform")
    cases = _index_case_rows(scenario_document.get("cases"), label="scenario-results")
    trace_rows = _read_jsonl(Path(platform_root) / "native-trace.jsonl")
    traces = _index_case_rows(trace_rows, label="native-trace")
    server_document = _json(Path(platform_root) / "server-events.json")
    ui_document = _json(Path(platform_root) / "ui-observations.json")
    servers = _index_case_rows(server_document.get("cases"), label="server-events")
    ui_rows = _index_case_rows(ui_document.get("cases"), label="ui-observations")
    if set(traces) != set(cases) or set(servers) != set(cases) or set(ui_rows) != set(cases):
        raise AggregateError("native trace, server, UI and scenario case membership differs")
    expected_keys = set()
    for row in inventory:
        variants = row.get("variants") or [None]
        expected_keys.update((row["id"], item.get("id") if item else None) for item in variants)
    if set(cases) != expected_keys:
        raise AggregateError("native case membership differs from the frozen inventory")

    platform_report = _json(Path(platform_root) / "platform-report.json")
    build_hash = platform_report.get("buildHash")
    if not controls_stage and (not isinstance(build_hash, str) or len(build_hash) != 64):
        raise AggregateError("platform build hash is missing or malformed")
    checked = []
    for key in sorted(expected_keys, key=lambda item: (item[0], item[1] or "")):
        case = cases[key]
        trace_row = traces[key]
        server_row = servers[key]
        ui_case = ui_rows[key]
        trace = trace_row.get("trace")
        expected_build_hash = (
            platform_report.get("scenarioBuildHashes", {}).get(key[0])
            if controls_stage else "sha256:" + build_hash
        )
        if (
            not isinstance(trace, dict)
            or trace.get("scenarioId") != key[0]
            or trace.get("variantId") != key[1]
            or trace.get("platform") != platform
            or not isinstance(expected_build_hash, str)
            or trace.get("buildHash") != expected_build_hash
            or server_row.get("runId") != trace.get("runId")
            or not isinstance(server_row.get("events"), list)
            or not isinstance(ui_case.get("observations"), list)
        ):
            raise AggregateError("native case artifact identity or build binding is inconsistent")
        inventory_row = inventory_by_id[key[0]]
        if controls_stage:
            expected_mutation_id = control_mutation_ids[key[0]]
            build_record = mutation_builds[expected_mutation_id]
            if (
                case.get("mutationId") != expected_mutation_id
                or case.get("buildHash") != expected_build_hash
                or case.get("workspaceSourceSha256") != build_record.get("workspaceSourceSha256")
                or build_record.get("buildHash") != expected_build_hash
                or key[0] not in build_record.get("controlIds", [])
            ):
                raise AggregateError(f"control trace is not bound to its actual {expected_mutation_id} build")
        checked_report = (
            check_control_trace(contract, inventory_row, trace, server_row["events"], ui_case["observations"])
            if controls_stage else check_trace(contract, inventory_row, trace, server_row["events"], ui_case["observations"])
        )
        if (
            case.get("classification") != checked_report["classification"]
            or case.get("violations") != checked_report["violations"]
            or case.get("missingObservations") != checked_report["missingObservations"]
        ):
            raise AggregateError(f"native checker result cannot be replayed for {key[0]}:{key[1]}")
        checked.append({
            "scenarioId": key[0],
            "variantId": key[1],
            "classification": checked_report["classification"],
            "violations": checked_report["violations"],
            "missingObservations": checked_report["missingObservations"],
        })

    _verify_screenshot_manifest(platform_root)
    return checked


def _suite_ledger(root, candidate, manifest, manifest_digest, expected_platform, expected_stages, candidate_digest):
    root = Path(root)
    suite = _json(root / "suite-report.json")
    if (
        not isinstance(suite, dict)
        or set(suite) != {"version", "classification", "manifest", "manifestDigest", "selectedStages", "stageResults"}
        or type(suite.get("version")) is not int or suite["version"] != 1
        or suite.get("manifestDigest") != manifest_digest
        or suite.get("selectedStages") != expected_stages
        or not isinstance(suite.get("stageResults"), list)
        or [row.get("stageId") for row in suite["stageResults"] if isinstance(row, dict)] != expected_stages
    ):
        raise AggregateError(f"{expected_platform} suite report is incomplete or bound to another run")
    for row in suite["stageResults"]:
        skipped = row.get("skippedAfter") if isinstance(row, dict) else None
        if skipped is not None:
            after = skipped.get("stageId") if isinstance(skipped, dict) else None
            cause = skipped.get("classification") if isinstance(skipped, dict) else None
            raise AggregateError(
                f"{expected_platform} stage {row['stageId']} was not run: skipped after {after} {cause}"
            )
    _verify_ledger_root(root, suite, manifest_digest, candidate_digest, expected_stages, expected_platform)

    checked = {}
    results = []
    durations = []
    for stage_id, suite_row in zip(expected_stages, suite["stageResults"], strict=True):
        result, output, stage = _portable_attempt(
            root, candidate, manifest, manifest_digest, stage_id, suite_row, candidate_digest
        )
        checked[stage_id] = (result, output, stage)
        durations.append(result["durationSeconds"])
        results.append({
            "stageId": stage_id,
            "classification": result["classification"],
            "bindingClassification": "PASS",
            "attemptId": result["attemptId"],
            "durationSeconds": result["durationSeconds"],
        })
    recalculated = reproduce.aggregate_suite_results(copy.deepcopy(suite["stageResults"]), expected_stages)
    if suite.get("classification") != recalculated["classification"]:
        raise AggregateError(f"{expected_platform} suite summary verdict does not match its checked stages")
    return checked, results, durations


def _verify_ledger_root(root, suite, manifest_digest, candidate_digest, expected_stages, expected_platform):
    root = Path(root)
    expected_attempts = {"auto-" + stage_id for stage_id in expected_stages}
    allowed_root = {
        "suite-report.json", "ledger-owner.json", ".manifest-digest", ".budget.lock",
        "owned-device", "runtime-gate", "ios-runner-logs", "android-runner-logs",
    } | expected_attempts
    entries = {path.name for path in root.iterdir()}
    if entries - allowed_root or not expected_attempts <= entries:
        raise AggregateError(f"{expected_platform} ledger has an unexpected or missing attempt/output member")
    owner = _json(root / "ledger-owner.json")
    if (
        not isinstance(owner, dict)
        or set(owner) != {"version", "manifestDigest", "manifestOwnerSha256", "selectedStages", "attemptIds", "candidateDigests"}
        or type(owner.get("version")) is not int or owner["version"] != 1
        or owner.get("manifestDigest") != manifest_digest
        or owner.get("manifestOwnerSha256") != _sha256_text(manifest_digest + "\n")
        or owner.get("selectedStages") != expected_stages
        or owner.get("attemptIds") != ["auto-" + stage_id for stage_id in expected_stages]
        or owner.get("candidateDigests") != [candidate_digest]
    ):
        raise AggregateError(f"{expected_platform} visible ledger owner does not bind this manifest/source")
    hidden_owner = root / ".manifest-digest"
    if hidden_owner.exists() and (
        hidden_owner.is_symlink() or not hidden_owner.is_file() or hidden_owner.read_text().strip() != manifest_digest
    ):
        raise AggregateError(f"{expected_platform} hidden ledger owner differs from the frozen manifest")
    budget_lock = root / ".budget.lock"
    if budget_lock.exists() and (budget_lock.is_symlink() or not budget_lock.is_file()):
        raise AggregateError(f"{expected_platform} budget lock artifact is malformed")
    return owner


def _stage_report(attempt_root, stage):
    if stage["verdictProtocol"] != "integration-comparator":
        return None
    return protocol.integration_report(Path(attempt_root) / stage["requiredArtifacts"][0]["path"], stage)


def _platform_row(report, platform):
    matches = [row for row in report.get("platformResults", []) if row.get("platform") == platform]
    return matches[0] if len(matches) == 1 else None


def validate_partial_control_report(report, stage, platform):
    """Require one fully detected selected platform and one explicitly unrun peer."""
    selected = _platform_row(report, platform)
    other_platform = "android" if platform == "ios" else "ios"
    other = _platform_row(report, other_platform)
    expected_ids = list(stage["requiredScenarioIds"])
    if report.get("classification") != "NOT_RUN" or not isinstance(selected, dict) or not isinstance(other, dict):
        raise AggregateError("control input must remain an explicitly partial NOT_RUN report")
    if selected["classification"] != "PASS" or selected["completedScenarioIds"] != expected_ids or selected["missingScenarioIds"]:
        raise AggregateError(f"selected {platform} control platform is not a complete PASS")
    if selected.get("validationScope") != "ci":
        raise AggregateError(f"selected {platform} control platform is outside the CI acceptance scope")
    if not selected["deviceHash"] or selected["buildHash"] is not None:
        raise AggregateError(f"selected {platform} control result has invalid aggregate build identity")
    if (
        other["classification"] != "NOT_RUN"
        or other["completedScenarioIds"]
        or other["missingScenarioIds"] != expected_ids
        or other["deviceHash"] is not None
        or other["buildHash"] is not None
            or other.get("validationScope") != "not-run"
    ):
        raise AggregateError("unselected control platform is not explicitly NOT_RUN")
    control_ids = set(expected_ids)
    control_results = [row for row in report.get("controlResults", []) if row["platform"] == platform]
    if (
        len(control_results) != len(control_ids)
        or {row["controlId"] for row in control_results} != control_ids
        or any(row["classification"] != "DETECTED" for row in control_results)
    ):
        raise AggregateError(f"selected {platform} ledger lacks every named control witness")
    expected_bindings = {
        (row["platform"], row["scenarioId"], row["variantId"])
        for row in stage["expectedTraceBindings"] if row["platform"] == platform
    }
    actual_bindings = {
        (row["platform"], row["scenarioId"], row["variantId"])
        for row in report.get("traceBindings", [])
    }
    if actual_bindings != expected_bindings:
        raise AggregateError(f"selected {platform} control trace binding inventory differs")
    scenario_builds = selected.get("scenarioBuildHashes")
    if (
        not isinstance(scenario_builds, dict)
        or set(scenario_builds) != control_ids
        or any(not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value) for value in scenario_builds.values())
    ):
        raise AggregateError(f"selected {platform} controls lack per-control build hashes")
    return selected


def _verify_native_stage(attempt_root, stage, platform, *, candidate, partial_controls=False):
    attempt_root = Path(attempt_root)
    stage_name = stage["requiredArtifacts"][0]["path"].split("/", 1)[0]
    stage_output = attempt_root / stage_name
    report = _stage_report(attempt_root, stage)
    if report is None:
        raise AggregateError("native stage report is unavailable")
    selected = _platform_row(report, platform)
    if not isinstance(selected, dict):
        raise AggregateError(f"native stage omits its selected {platform} platform row")
    expected_ids = list(stage["requiredScenarioIds"])
    if partial_controls:
        selected = validate_partial_control_report(report, stage, platform)
    elif report["classification"] != "PASS":
        raise AggregateError(f"candidate {platform} stage report is not a full PASS")
    elif (
        selected["classification"] != "PASS"
        or selected.get("validationScope") != "ci"
        or selected["completedScenarioIds"] != expected_ids
        or selected["missingScenarioIds"]
        or not selected["deviceHash"] or not selected["buildHash"]
    ):
        raise AggregateError(f"selected {platform} native stage is not a complete PASS")

    platform_root = stage_output / platform
    device_document = _json(platform_root / "device.json")
    raw_device_hash = device_document.get("deviceHash")
    if selected["deviceHash"] != ("sha256:" + raw_device_hash if isinstance(raw_device_hash, str) else None):
        raise AggregateError(f"{platform} device hash differs between stage and platform artifact")
    build_document = _json(platform_root / "build.json")
    if partial_controls:
        if (
            build_document.get("buildHash") is not None
            or build_document.get("scenarioBuildHashes") != selected["scenarioBuildHashes"]
        ):
            raise AggregateError(f"{platform} per-control build hashes differ between report and platform artifact")
    else:
        raw_build_hash = build_document.get("buildHash")
        if selected["buildHash"] != ("sha256:" + raw_build_hash if isinstance(raw_build_hash, str) else None):
            raise AggregateError(f"{platform} build hash differs between stage and platform artifact")
    checked = _recheck_platform_histories(platform_root, platform, stage, Path(candidate))
    if any(row["classification"] != ("SEMANTIC_FAIL" if partial_controls else "PASS") for row in checked):
        raise AggregateError(f"{platform} native history does not satisfy its frozen classification")
    return report, selected, checked


def aggregate_ledgers(*, candidate, manifest_path, manifest_digest, ios_ledger, android_ledger, output=None):
    """Recheck both platform ledgers and derive the complete five-stage verdict."""
    candidate = Path(candidate).resolve()
    manifest = protocol.read_manifest(manifest_path, manifest_digest)
    candidate_digest = _source_digest(manifest, candidate)
    if manifest["baselineCommit"] != manifest["provenance"].get("baselineCommit"):
        raise AggregateError("manifest baseline provenance is inconsistent")
    ios_checked, ios_results, ios_durations = _suite_ledger(
        ios_ledger, candidate, manifest, manifest_digest, "ios", IOS_STAGES, candidate_digest
    )
    android_checked, android_results, android_durations = _suite_ledger(
        android_ledger, candidate, manifest, manifest_digest, "android", ANDROID_STAGES, candidate_digest
    )
    all_records = ios_results + android_results
    if len(all_records) > manifest["maxAttempts"] or sum(ios_durations + android_durations) > manifest["maxTotalSeconds"]:
        raise AggregateError("cross-platform attempt or elapsed-time budget is exhausted")
    per_stage_limit = manifest["provenance"].get("maxAttemptsPerStage")
    if type(per_stage_limit) is not int or per_stage_limit != 2:
        raise AggregateError("frozen per-stage attempt limit is invalid")
    counts_by_stage = {}
    for row in all_records:
        counts_by_stage[row["stageId"]] = counts_by_stage.get(row["stageId"], 0) + 1
    if any(count > per_stage_limit for count in counts_by_stage.values()):
        raise AggregateError("cross-platform per-stage attempt limit is exhausted")

    ios_red = ios_checked["integration-red"][0]
    ios_candidate = ios_checked["candidate-ios"][0]
    ios_controls = ios_checked[CONTROL_STAGE][0]
    ios_legacy = ios_checked["legacy-full"][0]
    android_candidate = android_checked["candidate-android"][0]
    android_controls = android_checked[CONTROL_STAGE][0]

    if ios_candidate["classification"] == "PASS":
        _verify_native_stage(ios_checked["candidate-ios"][1], manifest["stages"]["candidate-ios"], "ios", candidate=candidate)
    if android_candidate["classification"] == "PASS":
        _verify_native_stage(android_checked["candidate-android"][1], manifest["stages"]["candidate-android"], "android", candidate=candidate)
    control_stage = manifest["stages"][CONTROL_STAGE]
    ios_control_report = _stage_report(ios_checked[CONTROL_STAGE][1], control_stage)
    android_control_report = _stage_report(android_checked[CONTROL_STAGE][1], control_stage)
    ios_selected = _platform_row(ios_control_report, "ios")
    android_selected = _platform_row(android_control_report, "android")
    if ios_controls["classification"] == "NOT_RUN" and ios_selected and ios_selected.get("classification") == "PASS":
        _verify_native_stage(ios_checked[CONTROL_STAGE][1], control_stage, "ios", candidate=candidate, partial_controls=True)
    if android_controls["classification"] == "NOT_RUN" and android_selected and android_selected.get("classification") == "PASS":
        _verify_native_stage(android_checked[CONTROL_STAGE][1], control_stage, "android", candidate=candidate, partial_controls=True)
    control_source_classes = [ios_controls["classification"], android_controls["classification"]]
    control_failure = next(
        (status for status in ("INFRA_FAILURE", "INVALID_HISTORY", "NOT_RUN", "INCONCLUSIVE", "SEMANTIC_FAIL")
         if status in control_source_classes),
        None,
    )
    both_selected_reports_pass = all(
        isinstance(row, dict) and row["classification"] == "PASS"
        for row in (_platform_row(ios_control_report, "ios"), _platform_row(android_control_report, "android"))
    )
    controls_derived_classification = (
        "PASS"
        if ios_controls["classification"] == android_controls["classification"] == "NOT_RUN"
        and all(row["classification"] == "PASS" for row in (ios_candidate, android_candidate))
        and both_selected_reports_pass
        else control_failure or "INCONCLUSIVE"
    )
    derived_controls = {
        "classification": controls_derived_classification,
        "sourceReports": {
            "ios": _sha256(ios_checked[CONTROL_STAGE][1] / CONTROL_STAGE / "report.json"),
            "android": _sha256(android_checked[CONTROL_STAGE][1] / CONTROL_STAGE / "report.json"),
        },
        "controlResults": [
            row for report in (ios_control_report, android_control_report)
            for row in report["controlResults"]
        ],
        "traceBindings": [
            row for report in (ios_control_report, android_control_report)
            for row in report["traceBindings"]
        ],
        "modelReportSha256": _sha256(ios_checked[CONTROL_STAGE][1] / CONTROL_STAGE / control_stage["modelReportPath"]),
        "mutantModelReportSha256": {
            mutant: _sha256(ios_checked[CONTROL_STAGE][1] / CONTROL_STAGE / "model" / "mutants" / mutant / "report.json")
            for mutant in control_stage["requiredMutantWitnesses"]
        },
    }
    if (
        derived_controls["classification"] == "PASS"
        and derived_controls["modelReportSha256"] != _sha256(
            android_checked[CONTROL_STAGE][1] / CONTROL_STAGE / control_stage["modelReportPath"]
        )
    ):
        raise AggregateError("platform ledgers contain different baseline model artifacts")
    if derived_controls["classification"] == "PASS":
        for mutant in control_stage["requiredMutantWitnesses"]:
            if derived_controls["mutantModelReportSha256"][mutant] != _sha256(
                android_checked[CONTROL_STAGE][1] / CONTROL_STAGE / "model" / "mutants" / mutant / "report.json"
            ):
                raise AggregateError(f"platform ledgers contain different model mutant artifact: {mutant}")
        expected_controls = {
            (platform, control_id)
            for platform in ("ios", "android")
            for control_id in control_stage["requiredScenarioIds"]
        }
        actual_controls = {
            (row["platform"], row["controlId"])
            for row in derived_controls["controlResults"]
        }
        expected_bindings = {
            (row["platform"], row["scenarioId"], row["variantId"])
            for row in control_stage["expectedTraceBindings"]
        }
        actual_bindings = {
            (row["platform"], row["scenarioId"], row["variantId"])
            for row in derived_controls["traceBindings"]
        }
        if actual_controls != expected_controls or actual_bindings != expected_bindings:
            raise AggregateError("derived integration-controls report omits a required platform case")

    ordered_rows = [
        {"stageId": "integration-red", "classification": ios_red["classification"], "bindingClassification": "PASS"},
        {"stageId": "candidate-ios", "classification": ios_candidate["classification"], "bindingClassification": "PASS"},
        {"stageId": "candidate-android", "classification": android_candidate["classification"], "bindingClassification": "PASS"},
        {"stageId": CONTROL_STAGE, "classification": derived_controls["classification"], "bindingClassification": "PASS"},
        {"stageId": "legacy-full", "classification": ios_legacy["classification"], "bindingClassification": "PASS"},
    ]
    suite = reproduce.aggregate_suite_results(ordered_rows)
    result = {
        "version": 1,
        "classification": suite["classification"],
        "manifestDigest": manifest_digest,
        "candidateDigest": candidate_digest,
        "frozenSourceDigest": manifest["frozenSourceDigest"],
        "selectedPlatforms": {"ios": IOS_STAGES, "android": ANDROID_STAGES},
        "stageResults": suite["stageResults"],
        "derivedIntegrationControls": derived_controls,
        "platformLedgers": {
            "ios": {"classification": _json(Path(ios_ledger) / "suite-report.json")["classification"], "attempts": ios_results},
            "android": {"classification": _json(Path(android_ledger) / "suite-report.json")["classification"], "attempts": android_results},
        },
        "budget": {
            "attempts": len(all_records),
            "durationSeconds": sum(ios_durations + android_durations),
            "maxAttempts": manifest["maxAttempts"],
            "maxAttemptsPerStage": per_stage_limit,
            "attemptsByStage": counts_by_stage,
            "maxTotalSeconds": manifest["maxTotalSeconds"],
        },
    }
    if output is not None:
        protocol.write_json(Path(output), result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--manifest-digest", required=True)
    parser.add_argument("--ios-ledger", required=True)
    parser.add_argument("--android-ledger", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = aggregate_ledgers(
            candidate=Path(args.candidate),
            manifest_path=Path(args.manifest),
            manifest_digest=args.manifest_digest,
            ios_ledger=Path(args.ios_ledger),
            android_ledger=Path(args.android_ledger),
            output=Path(args.output),
        )
    except (AggregateError, protocol.ProtocolError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        result = {"classification": "INFRA_FAILURE", "detail": str(exc)}
        print(json.dumps(result, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return reproduce._exit_code(result["classification"])


if __name__ == "__main__":
    sys.exit(main())

