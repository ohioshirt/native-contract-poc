"""CLI wrappers around the frozen change protocol and named integration stages."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

from integration import protocol_config
from verification import change_protocol as protocol


SUITE_STAGES = (
    "integration-red",
    "candidate-ios",
    "candidate-android",
    "integration-controls",
    "legacy-full",
)


def _within(candidate: Path, path: Path) -> Path:
    candidate = Path(candidate).resolve()
    path = Path(path)
    if not path.is_absolute():
        path = candidate / path
    path = path.resolve()
    try:
        path.relative_to(candidate)
    except ValueError as exc:
        raise protocol.ProtocolError("output must remain inside the candidate") from exc
    return path


def _sha256_id(value):
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value):
        return "sha256:" + value
    return value


def freeze(candidate: Path, output: Path) -> dict:
    """Build config and delegate manifest creation/binding to change_protocol."""
    candidate = Path(candidate).resolve()
    output = _within(candidate, Path(output))
    if output.exists():
        raise protocol.ProtocolError("freeze output must be a fresh directory")
    if not output.name or output.name in {".", ".."}:
        raise protocol.ProtocolError("freeze output directory needs a stable unique name")
    output.mkdir(parents=True)
    output_root = Path("reports/standalone/attempts") / output.name
    config = protocol_config.build_config(candidate, output_root, protocol_config.acceptance_baseline(candidate))
    config_path = output / "protocol-config.json"
    manifest_path = output / "manifest.json"
    protocol.write_json(config_path, config)
    manifest_digest = protocol.freeze(candidate, config, manifest_path)
    (output / "manifest.sha256").write_text(manifest_digest + "\n")
    return {
        "classification": "PASS",
        "manifest": str(manifest_path),
        "manifestDigest": manifest_digest,
        "protocolConfig": str(config_path),
        "outputDirectory": str(output),
    }


def run_one(candidate: Path, manifest: Path, manifest_digest: str, stage: str, attempt: str) -> dict:
    """Run one fixed stage through the authoritative frozen protocol."""
    return protocol.run(manifest, manifest_digest, candidate, stage, attempt)


def run(*, candidate: Path, output: Path, stages: list[str]) -> dict:
    """Run named stages using the manifest saved by :func:`freeze`."""
    candidate = Path(candidate).resolve()
    output = _within(candidate, Path(output))
    manifest = output / "manifest.json"
    digest_path = output / "manifest.sha256"
    if not manifest.is_file() or not digest_path.is_file():
        raise protocol.ProtocolError("output directory does not contain a frozen manifest and digest")
    if not isinstance(stages, list) or not stages or any(not isinstance(stage, str) or not stage for stage in stages):
        raise protocol.ProtocolError("stages must be a nonempty list of frozen stage IDs")
    if len(stages) != len(set(stages)):
        raise protocol.ProtocolError("stage list contains a duplicate")
    digest = digest_path.read_text().strip()
    results = []
    for stage_id in stages:
        attempt = "auto-" + stage_id
        results.append(run_one(candidate, manifest, digest, stage_id, attempt))
    priority = ("INFRA_FAILURE", "INVALID_HISTORY", "NOT_RUN", "INCONCLUSIVE", "SEMANTIC_FAIL", "PASS")
    classification = next(
        (status for status in priority if any(result["classification"] == status for result in results)),
        "INFRA_FAILURE",
    )
    return {"classification": classification, "stageResults": results, "manifest": str(manifest), "manifestDigest": digest}


def aggregate_suite_results(stage_results: list[dict], expected_stages: list[str] | None = None) -> dict:
    """Accept only five bound stages; integration-red is an expected semantic failure."""
    expected_stages = list(SUITE_STAGES) if expected_stages is None else expected_stages
    if not isinstance(stage_results, list) or any(not isinstance(row, dict) for row in stage_results):
        return {"classification": "INVALID_HISTORY", "stageResults": []}
    if [row.get("stageId") for row in stage_results] != expected_stages:
        return {"classification": "INVALID_HISTORY", "stageResults": stage_results}

    for row in stage_results:
        if row.get("bindingClassification") != "PASS":
            row["acceptanceClassification"] = "INFRA_FAILURE"
        elif row["stageId"] == "integration-red":
            row["acceptanceClassification"] = (
                "PASS" if row.get("classification") == "SEMANTIC_FAIL"
                else "INFRA_FAILURE" if row.get("classification") == "PASS"
                else row.get("classification", "INFRA_FAILURE")
            )
        else:
            row["acceptanceClassification"] = row.get("classification", "INFRA_FAILURE")

    priority = ("INFRA_FAILURE", "INVALID_HISTORY", "NOT_RUN", "INCONCLUSIVE", "SEMANTIC_FAIL", "PASS")
    classification = next(
        (status for status in priority if any(row["acceptanceClassification"] == status for row in stage_results)),
        "INFRA_FAILURE",
    )
    return {"classification": classification, "stageResults": stage_results}


def run_suite(*, candidate: Path, output: Path) -> dict:
    """Run, bind, and aggregate all frozen acceptance stages in order."""
    candidate = Path(candidate).resolve()
    manifest_directory = _within(candidate, Path(output))
    manifest = manifest_directory / "manifest.json"
    digest_path = manifest_directory / "manifest.sha256"
    if not manifest.is_file() or not digest_path.is_file():
        raise protocol.ProtocolError("manifest directory does not contain a frozen manifest and digest")
    digest = digest_path.read_text().strip()
    frozen = protocol.read_manifest(manifest, digest)
    ledger_root = _within(candidate, Path(frozen["outputRoot"]))
    return run_stages(
        candidate=candidate,
        output=ledger_root,
        stages=list(SUITE_STAGES),
        manifest=manifest,
        manifest_digest=digest,
    )


def run_stages(
    *, candidate: Path, output: Path, stages: list[str], manifest: Path, manifest_digest: str
) -> dict:
    """Run a unique subset of frozen stages in a platform-specific CI ledger."""
    candidate = Path(candidate).resolve()
    output = _within(candidate, Path(output))
    manifest = _within(candidate, Path(manifest))
    frozen = protocol.read_manifest(manifest, manifest_digest)
    frozen_output = _within(candidate, Path(frozen["outputRoot"]))
    if output != frozen_output:
        raise protocol.ProtocolError("stage output root differs from frozen manifest outputRoot")
    suite_report_path = output / "suite-report.json"
    if suite_report_path.exists():
        raise protocol.ProtocolError("stage report path already exists")
    if (
        not isinstance(stages, list) or not stages
        or any(not isinstance(stage, str) or stage not in SUITE_STAGES for stage in stages)
        or len(stages) != len(set(stages))
    ):
        raise protocol.ProtocolError("stage list must contain unique frozen suite stage IDs")

    digest = manifest_digest
    bound_results = []
    for stage_id in stages:
        attempt_id = "auto-" + stage_id
        row = run_one(candidate, manifest, digest, stage_id, attempt_id)
        result_directory = row.get("outputDirectory")
        result_path = Path(result_directory) / "result.json" if isinstance(result_directory, str) else None
        if result_path is None or not result_path.is_file():
            binding = {"classification": "INFRA_FAILURE", "bindingClassification": "INFRA_FAILURE", "detail": "stage result artifact is missing"}
        else:
            binding = check(candidate, manifest, digest, result_path)
        row["bindingClassification"] = binding.get("bindingClassification", binding.get("classification", "INFRA_FAILURE"))
        row["bindingResult"] = binding
        bound_results.append(row)

    aggregate = aggregate_suite_results(bound_results, expected_stages=stages)
    owner_path = output / ".manifest-digest"
    if not owner_path.is_file() or owner_path.is_symlink() or owner_path.read_text().strip() != digest:
        raise protocol.ProtocolError("stage ledger does not retain its frozen manifest owner")
    report = {
        "version": 1,
        "classification": aggregate["classification"],
        "manifest": str(manifest),
        "manifestDigest": digest,
        "selectedStages": list(stages),
        "stageResults": aggregate["stageResults"],
    }
    protocol.write_json(suite_report_path, report)
    protocol.write_json(output / "ledger-owner.json", {
        "version": 1,
        "manifestDigest": digest,
        "manifestOwnerSha256": protocol.digest_bytes(owner_path.read_bytes()),
        "selectedStages": list(stages),
        "attemptIds": [row["attemptId"] for row in bound_results],
        "candidateDigests": sorted({
            row["candidateDigest"] for row in bound_results
            if isinstance(row.get("candidateDigest"), str)
        }),
    })
    return report


def check(candidate: Path, manifest: Path, manifest_digest: str, result: Path | None = None) -> dict:
    """Check source integrity or a saved stage result using change_protocol."""
    return protocol.check(manifest, manifest_digest, candidate, result)


def _write_not_run_stage(output: Path, stage_id: str, stage: dict) -> dict:
    output.mkdir(parents=True)
    artifacts = [item["path"] for item in stage["requiredArtifacts"] if item["validator"] != "integration-report"]
    required_scenarios = list(stage["requiredScenarioIds"])
    platform_rows = []
    device_hashes, build_hashes = {}, {}
    for platform in stage["expectedPlatforms"]:
        platform_paths = [path for path in artifacts if path.startswith(f"{stage_id}/{platform}/")]
        platform_rows.append({
            "platform": platform,
            "classification": "NOT_RUN",
            "requiredScenarioIds": required_scenarios,
            "completedScenarioIds": [],
            "missingScenarioIds": required_scenarios,
            "deviceHash": None,
            "buildHash": None,
            **({"validationScope": "not-run"} if "expectedTraceBindings" in stage else {}),
            "requiredArtifacts": platform_paths,
            **({"scenarioBuildHashes": {}} if "expectedControlWitnesses" in stage else {}),
        })
        device_hashes[platform] = None
        build_hashes[platform] = None
    report = {
        "version": 1,
        "stageId": stage_id,
        "classification": "NOT_RUN",
        "requiredScenarioIds": required_scenarios,
        "platformResults": platform_rows,
        "violations": [],
        "deviceHashes": device_hashes,
        "buildHashes": build_hashes,
        "requiredArtifacts": artifacts,
    }
    if "expectedControlWitnesses" in stage:
        report["controlResults"] = []
    if "expectedTraceBindings" in stage:
        report["traceBindings"] = []
    for artifact in stage["requiredArtifacts"]:
        if artifact["validator"] == "integration-report":
            continue
        path = output.parent / artifact["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        if artifact["validator"] == "model-report":
            from integration.model import explore
            explore(output=path.parent)
            continue
        if artifact["validator"] == "model-mutant-report":
            from integration.model import explore
            mutant = artifact["path"].split("/")[3]
            explore(output=path.parent, mutant=mutant)
            continue
        if artifact["validator"] == "json-object":
            protocol.write_json(path, {"classification": "NOT_RUN", "stageId": stage_id, "artifact": artifact["path"]})
        else:
            path.write_text(f"NOT_RUN: stage runner is not available for {stage_id}\n")
    protocol.write_json(output / "report.json", report)
    return {"classification": "NOT_RUN", "report": report, "exitCode": 3}


def _platform_stage_inputs(candidate: Path, platform: str, stage_id: str, output: Path, stage: dict):
    from integration import controller

    device_variable = "IOS_SIMULATOR_UDID" if platform == "ios" else "ANDROID_SERIAL"
    device = os.environ.get(device_variable)
    evidence_variable = (
        "NATIVE_CONTRACT_OWNED_IOS_DEVICE_EVIDENCE"
        if platform == "ios"
        else "NATIVE_CONTRACT_OWNED_ANDROID_DEVICE_EVIDENCE"
    )
    evidence = os.environ.get(evidence_variable) or os.environ.get("NATIVE_CONTRACT_OWNED_DEVICE_EVIDENCE")
    inventory_name = "control-scenarios.json" if stage_id == "integration-controls" else "scenarios.json"
    inventory_path = Path(candidate) / "integration" / inventory_name
    platform_output = output / platform
    result = controller.run_platform(
        platform,
        candidate=candidate,
        output=platform_output,
        device=device,
        scenarios=inventory_path,
        stage_id=stage_id,
        attempt_id=output.parent.name,
        required_scenario_ids=stage["requiredScenarioIds"],
        owned_device_evidence=evidence,
        timeout_seconds=stage["timeoutSeconds"],
    )
    return result


def _run_candidate_stage(candidate: Path, output: Path, stage_id: str, stage: dict) -> dict:
    output.mkdir(parents=True)
    platform = stage["expectedPlatforms"][0]
    result = _platform_stage_inputs(candidate, platform, stage_id, output, stage)
    platform_row = {
        "platform": platform,
        "classification": result["classification"],
        "requiredScenarioIds": list(stage["requiredScenarioIds"]),
        "completedScenarioIds": result.get("completedScenarioIds", []),
        "missingScenarioIds": result.get("missingScenarioIds", list(stage["requiredScenarioIds"])),
        "deviceHash": _sha256_id(result.get("deviceHash")),
        "buildHash": _sha256_id(result.get("buildHash")),
        "validationScope": result.get("validationScope", "ci"),
        "requiredArtifacts": result["requiredArtifacts"],
    }
    report = {
        "version": 1,
        "stageId": stage_id,
        "classification": result["classification"],
        "requiredScenarioIds": list(stage["requiredScenarioIds"]),
        "platformResults": [platform_row],
        "violations": result.get("violations", []),
        "deviceHashes": {platform: _sha256_id(result.get("deviceHash"))},
        "buildHashes": {platform: _sha256_id(result.get("buildHash"))},
        "requiredArtifacts": [
            row["path"] for row in stage["requiredArtifacts"]
            if row["validator"] != "integration-report"
        ],
        "traceBindings": result.get("traceBindings", []),
    }
    protocol.write_json(output / "report.json", report)
    classification = report["classification"]
    exit_code = 0 if classification == "PASS" else 1 if classification == "SEMANTIC_FAIL" else 2 if classification in {"INFRA_FAILURE", "INVALID_HISTORY"} else 3
    return {"classification": classification, "report": report, "exitCode": exit_code}


def _control_observations(platform, result, output, required_ids, witnesses):
    result_file = Path(output) / platform / "scenario-results.json"
    try:
        document = json.loads(result_file.read_text())
        cases = document.get("cases")
    except (OSError, json.JSONDecodeError):
        cases = None
    case_by_id = {}
    if isinstance(cases, list):
        for case in cases:
            if not isinstance(case, dict) or case.get("scenarioId") in case_by_id:
                case_by_id = {}
                break
            case_by_id[case.get("scenarioId")] = case

    rows = []
    completed_ids = set(result.get("completedScenarioIds", []))
    for control_id in required_ids:
        case = case_by_id.get(control_id, {})
        if (
            control_id not in completed_ids
            or case.get("classification") not in {"PASS", "SEMANTIC_FAIL", "NOT_DETECTED"}
        ):
            continue
        observed = sorted({
            item.get("invariant") for item in case.get("violations", [])
            if isinstance(item, dict) and isinstance(item.get("invariant"), str)
        })
        detected = set(witnesses[control_id]) <= set(observed)
        rows.append({
            "platform": platform,
            "controlId": control_id,
            "classification": "DETECTED" if detected else "NOT_DETECTED",
            "observedWitnesses": observed,
        })
    return rows


def _run_controls_stage(candidate: Path, output: Path, stage: dict) -> dict:
    """Run both platform control inventories and bind every required mutation witness."""
    from integration import model

    output.mkdir(parents=True)
    baseline_path = output / stage["modelReportPath"]
    model.explore(output=baseline_path.parent)
    for mutant in stage["requiredMutantWitnesses"]:
        model.explore(output=output / "model" / "mutants" / mutant, mutant=mutant)

    platforms = []
    control_results = []
    trace_bindings = []
    selected_value = os.environ.get("NATIVE_CONTRACT_CONTROL_PLATFORMS")
    if selected_value is None:
        selected_platforms = list(stage["expectedPlatforms"])
    else:
        selected_platforms = selected_value.split(",")
        if (
            not selected_platforms
            or len(selected_platforms) != len(set(selected_platforms))
            or any(platform not in stage["expectedPlatforms"] for platform in selected_platforms)
        ):
            raise protocol.ProtocolError("selected control platforms must be unique frozen platform IDs")

    overall = "PASS" if set(selected_platforms) == set(stage["expectedPlatforms"]) else "NOT_RUN"
    for platform in stage["expectedPlatforms"]:
        if platform in selected_platforms:
            result = _platform_stage_inputs(candidate, platform, "integration-controls", output, stage)
        else:
            from integration.controller import _write_platform_artifact_shell

            result = {
                "classification": "NOT_RUN",
                "platform": platform,
                "deviceId": None,
                "requiredScenarioIds": list(stage["requiredScenarioIds"]),
                "completedScenarioIds": [],
                "missingScenarioIds": list(stage["requiredScenarioIds"]),
                "deviceHash": None,
                "buildHash": None,
                "validationScope": "not-run",
                "detail": "this platform is evaluated by its separately owned CI ledger",
            }
            control_rows = json.loads((candidate / "integration" / "control-scenarios.json").read_text())["controls"]
            _write_platform_artifact_shell(
                output / platform,
                platform=platform,
                stage_id="integration-controls",
                scenario_rows=control_rows,
                result=result,
            )
        required = list(stage["requiredScenarioIds"])
        witnesses = stage["expectedControlWitnesses"]
        observed_rows = _control_observations(platform, result, output, required, witnesses)
        control_results.extend(observed_rows)
        bindings = result.get("traceBindings", [])
        trace_bindings.extend(bindings if isinstance(bindings, list) else [])
        completed = list(result.get("completedScenarioIds", []))
        missing = list(result.get("missingScenarioIds", [item for item in required if item not in completed]))
        controls_detected = all(row["classification"] == "DETECTED" for row in observed_rows)
        platform_classification = result.get("classification", "INFRA_FAILURE")
        if platform_classification in {"PASS", "SEMANTIC_FAIL"} and completed == required and not missing and controls_detected:
            platform_classification = "PASS"
        elif platform_classification in {"PASS", "SEMANTIC_FAIL"}:
            platform_classification = "INCONCLUSIVE"
        if platform not in selected_platforms:
            platform_classification = "NOT_RUN"
        if platform_classification != "PASS":
            priority = ("INFRA_FAILURE", "INVALID_HISTORY", "NOT_RUN", "INCONCLUSIVE")
            if platform_classification in priority:
                if overall == "PASS" or priority.index(platform_classification) < priority.index(overall):
                    overall = platform_classification
            else:
                overall = "INCONCLUSIVE"
        platforms.append({
            "platform": platform,
            "classification": platform_classification,
            "requiredScenarioIds": required,
            "completedScenarioIds": completed,
            "missingScenarioIds": missing,
            "deviceHash": _sha256_id(result.get("deviceHash")),
            "buildHash": None if "expectedControlWitnesses" in stage else _sha256_id(result.get("buildHash")),
            "validationScope": result.get(
                "validationScope", "ci" if platform in selected_platforms else "not-run"
            ),
            **({"scenarioBuildHashes": {
                scenario_id: _sha256_id(value)
                for scenario_id, value in result.get("scenarioBuildHashes", {}).items()
            }} if "expectedControlWitnesses" in stage else {}),
            "requiredArtifacts": result.get("requiredArtifacts", []),
        })

    if overall == "NOT_RUN" and all(
        row["classification"] in {"PASS", "NOT_RUN"} for row in platforms
    ):
        overall = "NOT_RUN"

    report = {
        "version": 1,
        "stageId": "integration-controls",
        "classification": overall,
        "requiredScenarioIds": list(stage["requiredScenarioIds"]),
        "platformResults": platforms,
        "violations": [],
        "deviceHashes": {row["platform"]: row["deviceHash"] for row in platforms},
        "buildHashes": {row["platform"]: row["buildHash"] for row in platforms},
        "requiredArtifacts": [
            item["path"] for item in stage["requiredArtifacts"]
            if item["validator"] != "integration-report"
        ],
        "traceBindings": trace_bindings,
        "controlResults": control_results,
    }
    protocol.write_json(output / "report.json", report)
    validated = protocol.integration_report(output / "report.json", stage)
    classification = validated["classification"]
    exit_code = 0 if classification == "PASS" else 1 if classification == "SEMANTIC_FAIL" else 2 if classification in {"INFRA_FAILURE", "INVALID_HISTORY"} else 3
    return {"classification": classification, "report": validated, "exitCode": exit_code}


def stage(*, candidate: Path, stage_id: str, output: Path) -> dict:
    """Execute one fixed stage; integration-red is the evaluator-only control."""
    candidate = Path(candidate).resolve()
    output = Path(output).absolute()
    baseline = protocol_config.acceptance_baseline(candidate)
    config = protocol_config.build_config(candidate, "reports/standalone/attempts/stage", baseline)
    if stage_id not in config["stages"] or stage_id == "legacy-full":
        raise protocol.ProtocolError("stage ID is not an integration-comparator stage")
    if output.exists():
        raise protocol.ProtocolError("stage output must be fresh")
    frozen_stage = config["stages"][stage_id]
    if stage_id == "integration-controls":
        return _run_controls_stage(candidate, output, frozen_stage)
    if stage_id != "integration-red":
        if stage_id in {"candidate-ios", "candidate-android"}:
            return _run_candidate_stage(candidate, output, stage_id, frozen_stage)
        _write_not_run_stage(output, stage_id, frozen_stage)
        report = protocol.integration_report(output / "report.json", frozen_stage)
        return {"classification": report["classification"], "report": report, "exitCode": 3}

    output.parent.mkdir(parents=True, exist_ok=True)
    from integration.fixtures.unsafe_adapter import main as unsafe_fixture_main

    fixture_exit = unsafe_fixture_main(["--output", str(output)])
    if fixture_exit != 0:
        raise protocol.ProtocolError("unsafe evaluator fixture did not produce its frozen semantic witness")

    scenario_rows = json.loads((candidate / "integration" / "scenarios.json").read_text())["scenarios"]
    scenarios = {row["id"]: row for row in scenario_rows}
    contract = json.loads((candidate / "integration" / "contract.json").read_text())
    violations = []
    scenario_results = []
    for scenario_id in frozen_stage["requiredScenarioIds"]:
        directory = output / scenario_id
        trace = json.loads((directory / "trace.json").read_text())
        server_events = json.loads((directory / "server-events.json").read_text())
        observations = json.loads((directory / "ui-observations.json").read_text())
        from integration.check import check_trace
        result = check_trace(
            contract, scenarios[scenario_id], trace, server_events, observations
        )
        scenario_results.append({"scenarioId": scenario_id, "classification": result["classification"]})
        for violation in result["violations"]:
            violations.append({"scenarioId": scenario_id, **violation})

    expected_artifacts = [
        item["path"] for item in frozen_stage["requiredArtifacts"] if item["validator"] != "integration-report"
    ]
    complete = all(result["classification"] == "SEMANTIC_FAIL" for result in scenario_results)
    report = {
        "version": 1,
        "stageId": stage_id,
        "classification": "SEMANTIC_FAIL" if complete else "INCONCLUSIVE",
        "requiredScenarioIds": list(frozen_stage["requiredScenarioIds"]),
        "platformResults": [{
            "platform": "evaluator",
            "classification": "SEMANTIC_FAIL" if complete else "INCONCLUSIVE",
            "requiredScenarioIds": list(frozen_stage["requiredScenarioIds"]),
            "completedScenarioIds": list(frozen_stage["requiredScenarioIds"]),
            "missingScenarioIds": [],
            "deviceHash": None,
            "buildHash": None,
            "requiredArtifacts": expected_artifacts,
        }],
        "violations": violations,
        "deviceHashes": {"evaluator": None},
        "buildHashes": {"evaluator": None},
        "requiredArtifacts": expected_artifacts,
        "scenarioResults": scenario_results,
    }
    # scenarioResults is recorded in the sidecar so the frozen report schema
    # remains exact and the protocol validator consumes only report.json.
    result_summary = {key: value for key, value in report.items() if key != "scenarioResults"}
    protocol.write_json(output / "report.json", result_summary)
    validated = protocol.integration_report(output / "report.json", frozen_stage)
    return {"classification": validated["classification"], "report": validated, "exitCode": 1 if complete else 3}


def _exit_code(classification):
    return {"PASS": 0, "SEMANTIC_FAIL": 1, "INVALID_HISTORY": 1, "INFRA_FAILURE": 2, "INCONCLUSIVE": 3, "NOT_RUN": 3}.get(classification, 2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze_parser = sub.add_parser("freeze")
    freeze_parser.add_argument("--candidate", required=True)
    freeze_parser.add_argument("--output", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--candidate", required=True)
    run_parser.add_argument("--manifest", required=True)
    run_parser.add_argument("--manifest-digest", required=True)
    run_parser.add_argument("--stage", required=True)
    run_parser.add_argument("--attempt", required=True)
    run_suite_parser = sub.add_parser("run-suite")
    run_suite_parser.add_argument("--candidate", required=True)
    run_suite_parser.add_argument("--output", required=True)
    run_stages_parser = sub.add_parser("run-stages")
    run_stages_parser.add_argument("--candidate", required=True)
    run_stages_parser.add_argument("--output", required=True)
    run_stages_parser.add_argument("--manifest", required=True)
    run_stages_parser.add_argument("--manifest-digest", required=True)
    run_stages_parser.add_argument("--stage", action="append", required=True)
    check_parser = sub.add_parser("check")
    check_parser.add_argument("--candidate", required=True)
    check_parser.add_argument("--manifest", required=True)
    check_parser.add_argument("--manifest-digest", required=True)
    check_parser.add_argument("--result")
    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--candidate", required=True)
    stage_parser.add_argument("--stage", required=True)
    stage_parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            result = freeze(Path(args.candidate), Path(args.output))
        elif args.command == "run":
            result = run_one(Path(args.candidate), Path(args.manifest), args.manifest_digest, args.stage, args.attempt)
        elif args.command == "run-suite":
            result = run_suite(candidate=Path(args.candidate), output=Path(args.output))
        elif args.command == "run-stages":
            result = run_stages(
                candidate=Path(args.candidate),
                output=Path(args.output),
                stages=args.stage,
                manifest=Path(args.manifest),
                manifest_digest=args.manifest_digest,
            )
        elif args.command == "check":
            result = check(Path(args.candidate), Path(args.manifest), args.manifest_digest, Path(args.result) if args.result else None)
        else:
            candidate = Path(args.candidate).resolve()
            output = _within(candidate, Path(args.output))
            result = stage(candidate=candidate, stage_id=args.stage, output=output)
        print(json.dumps(result, sort_keys=True))
        return _exit_code(result["classification"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        error = {"classification": "INFRA_FAILURE", "detail": str(exc)}
        print(json.dumps(error, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
