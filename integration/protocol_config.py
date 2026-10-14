"""Build the single frozen-stage configuration for standalone integration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from integration.mutations import validate_control_bindings
from verification.change_protocol import IOS_SHARD_STAGES, ProtocolError, validate_config


CHANGE_ID = "standalone-native-app-integration"
MAX_ATTEMPTS = 10
MAX_TOTAL_SECONDS = 21600
MAX_ATTEMPTS_PER_STAGE = 2
MODEL_REQUIRED_WITNESSES = [
    "APP-02-success-after-logout",
    "APP-03-failure-after-logout",
    "APP-04-old-success-after-login-b",
    "APP-05-old-failure-after-login-b",
    "duplicate-delivery",
    "queued-logout-during-pause",
    "fault-retry-cleanup",
    "restart-bootstrap-cleanup",
    "foreign-same-id",
]
MODEL_MUTANT_WITNESSES = {
    "unconditional-success-commit": ["I2", "I3", "I4"],
    "reentrant-consumer": ["I1", "I3"],
    "duplicate-deferred-clear": ["I4"],
    "unverified-publish": ["I6"],
    "failed-clear-ack": ["I8"],
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acceptance_baseline(root: Path) -> str:
    toolchain = json.loads((Path(root) / "integration" / "toolchain.json").read_text())
    baseline = toolchain.get("baselineCommit") if isinstance(toolchain, dict) else None
    if not isinstance(baseline, str) or re.fullmatch(r"[0-9a-f]{40}", baseline) is None:
        raise ValueError("toolchain must freeze one full baseline commit ID")
    return baseline


def _relative_output(root: Path, output: Path) -> str:
    output = Path(output)
    if not output.is_absolute():
        output = root / output
    output = output.absolute()
    try:
        return output.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("outputRoot must remain inside the candidate") from exc


def _integration_argv(stage_id: str) -> list[str]:
    return [
        "python3",
        "-m",
        "integration.reproduce",
        "stage",
        "--candidate",
        "{candidate}",
        "--stage",
        stage_id,
        "--output",
        "{output}/" + stage_id,
    ]


def _file_artifact(path: str, validator="file"):
    return {"path": path, "validator": validator}


def _platform_artifacts(stage_id: str, platform: str):
    prefix = f"{stage_id}/{platform}"
    return [
        _file_artifact(f"{prefix}/device.json", "json-object"),
        _file_artifact(f"{prefix}/build.json", "json-object"),
        _file_artifact(f"{prefix}/scenario-results.json", "json-object"),
        _file_artifact(f"{prefix}/native-trace.jsonl"),
        _file_artifact(f"{prefix}/server-events.json"),
        _file_artifact(f"{prefix}/ui-observations.json"),
        _file_artifact(f"{prefix}/controller-events.json"),
        _file_artifact(f"{prefix}/screenshots/manifest.json", "json-object"),
        _file_artifact(f"{prefix}/platform-report.json", "json-object"),
    ]


def _red_artifacts():
    stage_id = "integration-red"
    artifacts = [
        _file_artifact(f"{stage_id}/report.json", "integration-report"),
        _file_artifact(f"{stage_id}/fixture.json", "json-object"),
        _file_artifact(f"{stage_id}/summary.json", "json-object"),
    ]
    for scenario_id in ("APP-02", "APP-04"):
        prefix = f"{stage_id}/{scenario_id}"
        artifacts.extend([
            _file_artifact(f"{prefix}/fixture.json", "json-object"),
            _file_artifact(f"{prefix}/trace.json", "json-object"),
            _file_artifact(f"{prefix}/server-events.json"),
            _file_artifact(f"{prefix}/ui-observations.json"),
            _file_artifact(f"{prefix}/report.json", "json-object"),
        ])
    return artifacts


def _integration_stage(stage_id, timeout, platforms, scenario_ids, artifacts, *, control_witnesses=None):
    stage = {
        "argv": _integration_argv(stage_id),
        "cwd": "{candidate}",
        "timeoutSeconds": timeout,
        "verdictProtocol": "integration-comparator",
        "expectedPlatforms": platforms,
        "requiredScenarioIds": scenario_ids,
        "requiredArtifacts": artifacts,
    }
    if control_witnesses is not None:
        stage["expectedControlWitnesses"] = control_witnesses
        stage["modelReportPath"] = "model/baseline/report.json"
        stage["requiredModelWitnesses"] = MODEL_REQUIRED_WITNESSES
        stage["requiredMutantWitnesses"] = MODEL_MUTANT_WITNESSES
    return stage


def _trace_bindings(platforms, rows):
    bindings = []
    for platform in platforms:
        for row in rows:
            variant_ids = [item["id"] for item in row["variants"]] if row.get("variants") else [None]
            for variant_id in variant_ids:
                bindings.append({"platform": platform, "scenarioId": row["id"], "variantId": variant_id})
    return bindings


def ios_shard_scenarios(rows):
    """Balance complete scenarios by launches/variants with deterministic ties."""
    shards = [[] for _ in IOS_SHARD_STAGES]
    loads = [0] * len(shards)
    weighted = [
        (max(1, len(row.get('launches', []))) * len(row.get('variants') or [None]), index, row)
        for index, row in enumerate(rows)
    ]
    for weight, index, row in sorted(weighted, key=lambda item: (-item[0], item[1])):
        shard = min(range(len(shards)), key=lambda value: (loads[value], value))
        shards[shard].append((index, row))
        loads[shard] += weight
    return [[row for _, row in sorted(shard)] for shard in shards]


def validate_input_inventories(scenarios, controls):
    """Reject unknown/incomplete inventory fields before a manifest can be frozen."""
    from integration.check import control_inventory_errors, scenario_inventory_errors

    if not isinstance(scenarios, list) or not isinstance(controls, list):
        raise ProtocolError("scenario and control inventories must be arrays")
    for row in scenarios:
        errors = scenario_inventory_errors(row)
        if errors:
            raise ProtocolError("invalid frozen scenario inventory: " + "; ".join(errors))
    for row in controls:
        errors = control_inventory_errors(row)
        if errors:
            raise ProtocolError("invalid frozen control inventory: " + "; ".join(errors))


def build_config(root: Path, output: Path, baseline: str) -> dict:
    """Return a validated frozen-protocol config without freezing or writing files."""
    root = Path(root).resolve()
    if not isinstance(baseline, str) or re.fullmatch(r"[0-9a-f]{40}", baseline) is None:
        raise ValueError("baseline must be a full lowercase Git commit ID")
    output_root = _relative_output(root, Path(output))

    scenario_path = root / "integration" / "scenarios.json"
    control_path = root / "integration" / "control-scenarios.json"
    scenarios = json.loads(scenario_path.read_text())["scenarios"]
    controls = json.loads(control_path.read_text())["controls"]
    validate_input_inventories(scenarios, controls)
    validate_control_bindings(root / "integration" / "mutation_matrix.json", control_path)
    scenario_ids = [row["id"] for row in scenarios]
    control_ids = [row["id"] for row in controls]

    protected = [
        "integration/",
        ".github/workflows/integration.yml",
        ".gitignore",
        "scripts/integration-verify.sh",
        "scripts/ci-native-devices.py",
        "apps/ios-demo/NativeContractDemo.xcodeproj/project.pbxproj",
        "apps/ios-demo/NativeContractDemo.xcodeproj/xcshareddata/xcschemes/NativeContractDemo.xcscheme",
        "apps/ios-demo/NativeContractDemo/Info.plist",
        "apps/ios-demo/Config/Debug.xcconfig",
        "apps/ios-demo/Config/Release.xcconfig",
        "apps/ios-demo/NativeContractDemoUITests/ScenarioUITests.swift",
        "apps/ios-demo/NativeContractDemoTests/ScenarioContractTests.swift",
        "apps/ios-demo/NativeContractDemo/Contracts/NativeContractTypes.swift",
        "apps/ios-demo/NativeContractDemo/Debug/StorageProbe.swift",
        "apps/ios-demo/NativeContractDemo/Debug/DebugScenarioControl.swift",
        "apps/ios-demo/scripts/prepare-ci-runtime.py",
        "apps/ios-demo/scripts/test_prepare_ci_runtime.py",
        "apps/ios-demo/MutationFixtures/N2DuplicateClear.swift",
        "apps/ios-demo/MutationFixtures/N4FalseLogout.swift",
        "apps/ios-demo/MutationFixtures/CompileFixture.swift",
        "apps/android-demo/settings.gradle.kts",
        "apps/android-demo/build.gradle.kts",
        "apps/android-demo/gradle.properties",
        "apps/android-demo/gradlew",
        "apps/android-demo/gradlew.bat",
        "apps/android-demo/gradle/wrapper/gradle-wrapper.jar",
        "apps/android-demo/gradle/wrapper/gradle-wrapper.properties",
        "apps/android-demo/gradle/verification-metadata.xml",
        "apps/android-demo/gradle.lockfile",
        "apps/android-demo/gradle/contract-async.lockfile",
        "apps/android-demo/app/build.gradle.kts",
        "apps/android-demo/app/gradle.lockfile",
        "apps/android-demo/app/src/main/AndroidManifest.xml",
        "apps/android-demo/app/src/debug/AndroidManifest.xml",
        "apps/android-demo/app/src/debug/res/xml/network_security_config.xml",
        "apps/android-demo/app/src/main/java/nativecontract/demo/contract/NativeContractTypes.kt",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/StorageProbe.kt",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugScenarioControl.kt",
        "apps/android-demo/app/src/androidTest/java/nativecontract/demo/ScenarioInstrumentedTest.kt",
        "apps/android-demo/app/src/androidTest/java/nativecontract/demo/DemoTestRunner.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/ScenarioContractTest.kt",
        "apps/android-demo/MutationFixtures/N2DuplicateClear.kt",
        "apps/android-demo/MutationFixtures/N4FalseLogout.kt",
        "apps/android-demo/MutationFixtures/MutationHelperCompileFixture.kt",
        "apps/android-demo/MutationFixtures/compile-isolated.gradle",
    ]
    allowed = [
        "apps/ios-demo/NativeContractDemo/App/",
        "apps/ios-demo/NativeContractDemo/Coordinator/",
        "apps/ios-demo/NativeContractDemo/Transport/",
        "apps/ios-demo/NativeContractDemo/Storage/",
        "apps/ios-demo/NativeContractDemo/UI/",
        "apps/ios-demo/NativeContractDemo/Debug/DefaultDebugScenarioControl.swift",
        "apps/ios-demo/NativeContractDemo/Debug/DebugScenarioHooks.swift",
        "apps/ios-demo/NativeContractDemo/Debug/DemoIngress.swift",
        "apps/ios-demo/NativeContractDemo/Debug/JSONLAuditRecorder.swift",
        "apps/ios-demo/NativeContractDemo/NativeContractDemoApp.swift",
        "apps/ios-demo/NativeContractDemoTests/CoordinatorTests.swift",
        "apps/ios-demo/NativeContractDemoTests/TransportTests.swift",
        "apps/ios-demo/NativeContractDemoTests/KeychainStoreTests.swift",
        "apps/android-demo/app/src/main/java/nativecontract/demo/MainActivity.kt",
        "apps/android-demo/app/src/main/java/nativecontract/demo/DemoApplication.kt",
        "apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/",
        "apps/android-demo/app/src/main/java/nativecontract/demo/transport/",
        "apps/android-demo/app/src/main/java/nativecontract/demo/storage/",
        "apps/android-demo/app/src/main/java/nativecontract/demo/ui/",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugDemoApplication.kt",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugScenarioHooks.kt",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DefaultDebugScenarioControl.kt",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DemoIngress.kt",
        "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/JSONLAuditRecorder.kt",
        "apps/android-demo/app/src/main/res/",
        "apps/android-demo/app/src/test/java/nativecontract/demo/CoordinatorTests.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/TransportTests.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/StorageTests.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/CoordinatorUnitTest.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/TransportUnitTest.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/StorageUnitTest.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/CoordinatorTest.kt",
        "apps/android-demo/app/src/test/java/nativecontract/demo/TransportTest.kt",
        "apps/android-demo/app/src/androidTest/java/nativecontract/demo/AtomicFileStoreTest.kt",
    ]

    red_artifacts = _red_artifacts()
    ios_artifacts = [_file_artifact("candidate-ios/report.json", "integration-report"), *_platform_artifacts("candidate-ios", "ios")]
    android_artifacts = [_file_artifact("candidate-android/report.json", "integration-report"), *_platform_artifacts("candidate-android", "android")]
    controls_artifacts = [
        _file_artifact("integration-controls/report.json", "integration-report"),
        _file_artifact("integration-controls/model/baseline/report.json", "model-report"),
        *[
            _file_artifact(f"integration-controls/model/mutants/{mutant}/report.json", "model-mutant-report")
            for mutant in MODEL_MUTANT_WITNESSES
        ],
        *_platform_artifacts("integration-controls", "ios"),
        *_platform_artifacts("integration-controls", "android"),
    ]
    control_witnesses = {
        row["id"]: row["witnessInvariants"]
        for row in controls
    }
    legacy_artifacts = [_file_artifact("legacy-full/report.md", "full-report")]

    stages = {
        "integration-red": _integration_stage(
            "integration-red", 600, ["evaluator"], ["APP-02", "APP-04"], red_artifacts
        ),
        "candidate-ios": _integration_stage(
            "candidate-ios", 1800, ["ios"], scenario_ids, ios_artifacts
        ),
        "candidate-android": _integration_stage(
            "candidate-android", 1200, ["android"], scenario_ids, android_artifacts
        ),
        "integration-controls": _integration_stage(
            "integration-controls", 7200, ["ios", "android"], control_ids, controls_artifacts,
            control_witnesses=control_witnesses,
        ),
        "legacy-full": {
            "argv": ["bash", "scripts/verify.sh", "{output}/legacy-full"],
            "cwd": "{candidate}",
            "timeoutSeconds": 6600,
            "verdictProtocol": "full-gate",
            "requiredArtifacts": legacy_artifacts,
        },
    }
    for stage_id in ("candidate-ios", "candidate-android"):
        stages[stage_id]["expectedTraceBindings"] = _trace_bindings(
            stages[stage_id]["expectedPlatforms"], scenarios
        )
    for stage_id, rows in zip(IOS_SHARD_STAGES, ios_shard_scenarios(scenarios), strict=True):
        artifacts = [_file_artifact(stage_id + '/report.json', 'integration-report'),
                     *_platform_artifacts(stage_id, 'ios')]
        stages[stage_id] = _integration_stage(stage_id, 1800, ['ios'], [row['id'] for row in rows], artifacts)
        stages[stage_id]['expectedTraceBindings'] = _trace_bindings(['ios'], rows)
    stages["integration-controls"]["expectedTraceBindings"] = _trace_bindings(
        stages["integration-controls"]["expectedPlatforms"], controls
    )

    config = {
        "changeId": CHANGE_ID,
        "baselineCommit": baseline,
        "allowedPaths": allowed,
        "protectedPaths": protected,
        "ignoredPaths": [
            ".git/",
            ".superpowers/",
            ".DS_Store",
            "**/.DS_Store",
            "docs/experiments/control-location.json",
            "reports/",
            "ios/.build/",
            "ios/.swift-cache/",
            "android/.gradle/",
            "android/.gradle-home/",
            "android/async-library/build/",
            "android/library/build/",
            "android/.kotlin/",
            "android/verification-logs/",
            "apps/android-demo/.gradle/",
            "apps/android-demo/build/",
            "apps/android-demo/app/build/",
            "apps/android-demo/.kotlin/",
            "apps/ios-demo/NativeContractDemo.xcodeproj/xcuserdata/",
            "apps/ios-demo/NativeContractDemo.xcodeproj/project.xcworkspace/xcuserdata/",
            "apps/ios-demo/NativeContractDemo.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
            "apps/ios-demo/scripts/__pycache__/",
            ".gradle-home/",
            ".swift-cache/",
            ".formal-cache/",
            ".python-cache/",
            "integration/__pycache__/",
            "integration/fixtures/__pycache__/",
            "integration/tests/__pycache__/",
            "scripts/__pycache__/",
            "verification/__pycache__/",
            "verification/formal/__pycache__/",
        ],
        "outputRoot": output_root,
        "maxAttempts": MAX_ATTEMPTS,
        "maxTotalSeconds": MAX_TOTAL_SECONDS,
        "metadata": {
            "modelId": "Luna",
            "reasoningEffort": "max",
            "arm": "arm64",
            "seed": None,
            "caches": {"build": None, "provider": None},
            "tokenUsage": None,
            "costUsd": None,
        },
        "provenance": {
            "executor": "Luna/max",
            "baselineCommit": baseline,
            "maxAttemptsPerStage": MAX_ATTEMPTS_PER_STAGE,
            "integrationScenariosSha256": _digest(scenario_path),
            "controlScenariosSha256": _digest(control_path),
            "managedSpecificationSha256": _digest(root / "contract" / "specification.json"),
            "toolchainFile": "integration/toolchain.json",
        },
        "stages": stages,
    }
    validate_config(config)
    return config
