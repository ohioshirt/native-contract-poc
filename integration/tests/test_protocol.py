import json
import contextlib
import copy
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from integration import aggregate as integration_aggregate, protocol_config, reproduce
from integration import model as integration_model
from verification import change_protocol


ROOT = Path(__file__).resolve().parents[2]
# reports/ is untracked, so a fresh clone (CI) has no temporary-directory parent yet.
(ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)
BASELINE = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def setUpModule():
    (ROOT / "reports" / "standalone").mkdir(parents=True, exist_ok=True)


class ProtocolConfigurationTests(unittest.TestCase):
    def test_toolchain_record_separates_acceptance_pins_from_local_mismatches(self):
        toolchain = json.loads((ROOT / "integration" / "toolchain.json").read_text())

        self.assertEqual(toolchain["baselineCommit"], "d2ce1847cb2644252f7c4d069ef9e36142bb327b")
        self.assertEqual(protocol_config.acceptance_baseline(ROOT), toolchain["baselineCommit"])
        local_scope = toolchain["localValidationScope"]
        self.assertEqual(local_scope["id"], "local-observed")
        self.assertEqual(local_scope["classification"], "LOCAL_VALIDATION_ONLY")
        self.assertFalse(local_scope["acceptedByCiAggregate"])
        self.assertEqual(local_scope["ios"]["xcode"], "27.1")
        self.assertEqual(local_scope["ios"]["runtimeBuild"], "22G86")
        self.assertEqual(local_scope["android"]["abi"], "arm64-v8a")
        self.assertEqual(toolchain["acceptancePins"]["python"]["version"], "3.12.8")
        self.assertEqual(toolchain["localObserved"]["pythonCommand"]["version"], "3.9.6")
        self.assertFalse(toolchain["localObserved"]["pythonCommand"]["matchesAcceptancePin"])
        self.assertEqual(toolchain["localObserved"]["testInterpreter"]["version"], "3.12.9")
        self.assertFalse(toolchain["localObserved"]["testInterpreter"]["matchesAcceptancePin"])
        self.assertEqual(toolchain["localObserved"]["ownedAcceptanceInterpreter"]["version"], "3.12.8")
        self.assertTrue(toolchain["localObserved"]["ownedAcceptanceInterpreter"]["matchesAcceptancePin"])
        self.assertEqual(toolchain["pendingPinPreflight"]["python3128LocalInstall"], "PASS")
        self.assertEqual(toolchain["python3128TestReruns"]["verificationSuite"], "PASS")
        self.assertEqual(toolchain["python3128TestReruns"]["integrationSuite"], "PASS")

    def test_ci_workflow_pins_actions_and_checks_xcode_project_before_build(self):
        workflow_path = ROOT / ".github" / "workflows" / "integration.yml"
        self.assertTrue(workflow_path.is_file(), "the standalone integration preflight workflow is missing")
        lines = workflow_path.read_text().splitlines()
        text = "\n".join(lines)
        toolchain = json.loads((ROOT / "integration" / "toolchain.json").read_text())
        declared_actions = {
            (row["repository"], row["commit"], row["version"])
            for row in toolchain["ciActions"]
        }
        # Every workflow pins each action by full commit SHA, annotated with its declared release tag.
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            with self.subTest(workflow=path.name):
                workflow_text = path.read_text()
                uses_lines = re.findall(r"^\s*(?:- )?uses:.*$", workflow_text, flags=re.MULTILINE)
                pinned = [
                    re.fullmatch(r"\s*(?:- )?uses: ([^@\s]+)@([0-9a-f]{40}) # (v[0-9][0-9.]*)", line)
                    for line in uses_lines
                ]
                self.assertTrue(uses_lines, "workflow has no actions")
                self.assertEqual([line for line, match in zip(uses_lines, pinned) if match is None], [])
                self.assertTrue({match.groups() for match in pinned} <= declared_actions)
        action_refs = re.findall(r"^\s*uses: ([^@\s]+)@([0-9a-f]{40}) # (v[0-9][0-9.]*)$", text, flags=re.MULTILINE)
        self.assertEqual(set(action_refs), declared_actions)
        normalized = " ".join(re.sub(r"\\\n\s*", " ", text).split())
        for project_step in (
            "xcodebuild -list -project apps/ios-demo/NativeContractDemo.xcodeproj",
            "xcodebuild -resolvePackageDependencies -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo",
        ):
            self.assertIn(project_step, text)
        self.assertIn("xcode-version: '16.2'", text)
        self.assertIn("./apps/android-demo/gradlew -p apps/android-demo :contract-async:jar :app:assembleDebug :app:assembleDebugAndroidTest", normalized)
        list_index = normalized.index("xcodebuild -list -project apps/ios-demo/NativeContractDemo.xcodeproj")
        resolve_index = normalized.index("xcodebuild -resolvePackageDependencies -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo")
        build_index = normalized.index("xcodebuild -project apps/ios-demo/NativeContractDemo.xcodeproj -scheme NativeContractDemo")
        self.assertLess(list_index, resolve_index)
        self.assertLess(resolve_index, build_index)
        self.assertNotIn("DEVELOPMENT_TEAM", text)

    def test_ci_workflow_runs_native_ledgers_on_pull_requests_only_with_the_native_ci_label(self):
        workflow = (ROOT / ".github" / "workflows" / "integration.yml").read_text()
        trigger = workflow[workflow.index("\non:\n"):workflow.index("\njobs:\n")]
        self.assertIn("types: [opened, synchronize, reopened, labeled]", trigger)
        self.assertIn("workflow_dispatch:", trigger)
        self.assertIn("branches: [main]", trigger)
        self.assertIn("cancel-in-progress: ${{ github.event_name == 'pull_request' }}", workflow)
        jobs = re.split(r"(?m)^  (?=[a-z-]+:$)", workflow[workflow.index("\njobs:\n"):])[1:]
        headers = {block.split(":", 1)[0]: block.split("\n    steps:", 1)[0] for block in jobs}
        self.assertEqual(set(headers), {"evaluator-and-freeze", "ios-native", "android-native", "native-acceptance"})
        native_gate = "contains(github.event.pull_request.labels.*.name, 'native-ci')"
        for job in ("ios-native", "android-native", "native-acceptance"):
            with self.subTest(job=job):
                self.assertIn("github.event_name != 'pull_request' || " + native_gate, headers[job])
        self.assertNotIn(native_gate, headers["evaluator-and-freeze"])
        # Adding an unrelated label must not rerun anything.
        for job, header in headers.items():
            with self.subTest(job=job):
                self.assertIn("github.event.action != 'labeled' || github.event.label.name == 'native-ci'", header)

    def test_ci_workflows_bound_every_job_and_stream_stage_progress(self):
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            workflow = path.read_text()
            jobs = re.split(r"(?m)^  (?=[a-z-]+:$)", workflow[workflow.index("\njobs:\n"):])[1:]
            for block in jobs:
                with self.subTest(workflow=path.name, job=block.split(":", 1)[0]):
                    header = block.split("\n    steps:", 1)[0]
                    self.assertRegex(header, r"\n    timeout-minutes: [1-9][0-9]*(\n|$)")
        workflow = (ROOT / ".github" / "workflows" / "integration.yml").read_text()
        for platform in ("ios", "android"):
            with self.subTest(platform=platform):
                self.assertIn(f'export NATIVE_CONTRACT_PROGRESS_LOG="$RUNNER_TEMP/native-contract-{platform}/progress.log"', workflow)
        self.assertEqual(workflow.count('python -m integration.progress summary "$suite_report"'), 2)
        self.assertEqual(workflow.count(">> \"$GITHUB_STEP_SUMMARY\""), 2)
        self.assertEqual(workflow.count("CONTINUE_FLAG: ${{ inputs.continue_after_failure && '--continue-after-failure' || '' }}"), 2)
        self.assertIn("continue_after_failure:\n        description:", workflow)

    def test_ci_workflow_runs_the_frozen_full_gate_and_cleans_only_owned_devices(self):
        workflow = (ROOT / ".github" / "workflows" / "integration.yml").read_text()
        self.assertIn("native-acceptance:", workflow)
        self.assertIn("python scripts/ci-native-devices.py prepare", workflow)
        self.assertIn("python apps/ios-demo/scripts/prepare-ci-runtime.py", workflow)
        self.assertIn("python -m integration.reproduce run-stages", workflow)
        self.assertIn("python -m integration.aggregate", workflow)
        self.assertIn("python scripts/ci-native-devices.py cleanup", workflow)
        self.assertNotIn("if-no-artifact-found:", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn("--github-env \"$GITHUB_ENV\"", workflow)
        self.assertEqual(workflow.count('manifest="$GITHUB_WORKSPACE/reports/standalone/${RUN_LABEL}-manifest/manifest.json"'), 2)
        stage_manifest_flags = [
            line.strip() for line in workflow.splitlines()
            if line.strip() == '--manifest "$manifest" ' + chr(92)
        ]
        self.assertEqual(len(stage_manifest_flags), 2)
        self.assertEqual(workflow.count('--manifest-digest "$manifest_digest"'), 2)
        self.assertEqual(workflow.count('path: |\n            ${{ env.NATIVE_CONTRACT_OUTPUT_ROOT }}/'), 2)
        self.assertEqual(workflow.count("include-hidden-files: true"), 2)
        self.assertEqual(
            workflow.count("NATIVE_CONTRACT_OUTPUT_ROOT: reports/standalone/attempts/ci-${{ github.run_id }}-${{ github.run_attempt }}-manifest"),
            2,
        )
        device_bootstrap = (ROOT / "integration" / "ci_devices.py").read_text()
        self.assertIn("NATIVE_CONTRACT_OWNED_IOS_DEVICE_EVIDENCE", device_bootstrap)
        self.assertIn("NATIVE_CONTRACT_OWNED_ANDROID_DEVICE_EVIDENCE", device_bootstrap)
        self.assertIn("NATIVE_CONTRACT_CONTROL_PLATFORMS: ios", workflow)
        self.assertIn("NATIVE_CONTRACT_CONTROL_PLATFORMS: android", workflow)
        toolchain = json.loads((ROOT / "integration" / "toolchain.json").read_text())
        self.assertIn("scripts/ci-native-devices.py", toolchain["ciWorkflow"]["deviceBootstrap"])
        self.assertIn("integration.aggregate", toolchain["ciWorkflow"]["stageAggregation"])
        self.assertEqual(toolchain["ciWorkflow"]["runtimeExecution"], "HOSTED_CI_NOT_RUN")
        self.assertEqual(toolchain["ciWorkflow"]["maxAttemptsPerStage"], 2)

    def test_native_observe_is_fifo_command_but_not_in_current_automated_inventories(self):
        plan_text = (ROOT / "docs" / "experiments" / "standalone-app-plan.md").read_text()
        self.assertIn("| Deliver(Completion) | Observe | RetryCleanup", plan_text)
        self.assertIn("CommandReceipt(id: Int64, status: ReceiptStatus, observation: AppObservation)", plan_text)
        anchor_text = (ROOT / "integration" / "native-anchors.md").read_text()
        self.assertIn("Native `Observe` is a FIFO `AppCommand`", anchor_text)
        self.assertIn("The finite model deliberately abstracts `Observe` projections as stuttering steps", anchor_text)
        self.assertIn("Current frozen automated scenario/control inventories use independent probes", anchor_text)

        model_report = integration_model._base_report("PASS", 0, 0, {})
        self.assertIn("Observe projections", model_report["abstraction"]["excludedNoOps"])

        scenario_documents = (
            json.loads((ROOT / "integration" / "scenarios.json").read_text())["scenarios"],
            json.loads((ROOT / "integration" / "control-scenarios.json").read_text())["controls"],
        )
        commands = []
        for rows in scenario_documents:
            for row in rows:
                commands.extend(row.get("commands", []))
                commands.extend(
                    command
                    for launch in row.get("launches", [])
                    for command in launch.get("commands", [])
                )
                commands.extend(
                    command
                    for variant in row.get("variants", [])
                    for command in variant.get("commands", [])
                )
        self.assertNotIn("Observe", commands)

    def test_app10_freezes_retry_probe_before_login_b_on_both_platform_harnesses(self):
        rows = json.loads((ROOT / "integration" / "scenarios.json").read_text())["scenarios"]
        app10 = next(row for row in rows if row["id"] == "APP-10")
        expected = [
            ["Logout", "APP-10-after-failed-logout"],
            ["RetryCleanup", "APP-10-after-retry"],
        ]
        self.assertEqual(app10.get("receiptProbeOrder"), expected)
        self.assertIn("checkpointPublished", app10["requiredControllerEvents"])
        for variant in app10["variants"]:
            self.assertLess(variant["commands"].index("RetryCleanup"), variant["commands"].index("Login(B)"))

        android = (ROOT / "apps/android-demo/app/src/androidTest/java/nativecontract/demo/ScenarioInstrumentedTest.kt").read_text()
        self.assertIn('if (command == "RetryCleanup")', android)
        self.assertIn('selection.requiredProbes.filter { it.contains("after-retry") && it !in capturedProbes }', android)

    def test_config_builder_declares_fixed_stages_budgets_and_unknown_usage(self):
        output = ROOT / "reports" / "standalone" / "attempts" / "config-test"
        config = protocol_config.build_config(ROOT, output, BASELINE)

        change_protocol.validate_config(config)
        self.assertEqual(config["maxAttempts"], 10)
        self.assertEqual(config["maxTotalSeconds"], 21600)
        self.assertEqual(config["provenance"]["maxAttemptsPerStage"], 2)
        self.assertIsNone(config["metadata"]["tokenUsage"])
        self.assertIsNone(config["metadata"]["costUsd"])
        self.assertEqual(
            set(config["stages"]),
            {"integration-red", "candidate-ios", "candidate-android", "integration-controls", "legacy-full"},
        )
        self.assertEqual(config["stages"]["integration-red"]["timeoutSeconds"], 600)
        self.assertEqual(config["stages"]["candidate-ios"]["timeoutSeconds"], 1800)
        self.assertEqual(config["stages"]["candidate-android"]["timeoutSeconds"], 1200)
        self.assertEqual(config["stages"]["integration-controls"]["timeoutSeconds"], 7200)
        self.assertEqual(config["stages"]["legacy-full"]["timeoutSeconds"], 6600)
        self.assertTrue({
            "verification/__pycache__/",
            "apps/android-demo/.gradle/",
            "apps/android-demo/build/",
            "apps/android-demo/app/build/",
            "ios/.build/",
            "ios/.swift-cache/",
            "android/.gradle/",
            "android/async-library/build/",
            "android/library/build/",
            ".gradle-home/",
            "android/.gradle-home/",
            ".DS_Store",
            ".swift-cache/",
            ".formal-cache/",
            ".python-cache/",
            "scripts/__pycache__/",
            "reports/",
        } <= set(config["ignoredPaths"]))

    def test_third_frozen_stage_attempt_is_recorded_not_launched(self):
        with tempfile.TemporaryDirectory(prefix="standalone-stage-budget-", dir=ROOT / "reports" / "standalone") as temporary:
            temporary_path = Path(temporary)
            attempt_root = ROOT / "reports" / "standalone" / "attempts" / ("per-stage-" + temporary_path.name)
            manifest_path = temporary_path / "manifest.json"
            config = protocol_config.build_config(ROOT, attempt_root, BASELINE)
            digest = change_protocol.freeze(ROOT, config, manifest_path)
            attempt_root.mkdir(parents=True)
            (attempt_root / ".manifest-digest").write_text(digest + "\n")
            for name in ("prior-candidate-ios-1", "prior-candidate-ios-2"):
                previous = attempt_root / name
                previous.mkdir()
                (previous / "result.json").write_text(json.dumps({
                    "manifestDigest": digest,
                    "stageId": "candidate-ios",
                    "durationSeconds": 0.0,
                }))

            result = change_protocol.run(
                manifest_path, digest, ROOT, "candidate-ios", "third-candidate-ios"
            )
            saved = json.loads((attempt_root / "third-candidate-ios" / "result.json").read_text())

        self.assertEqual(result["classification"], "NOT_RUN")
        self.assertEqual(saved["classification"], "NOT_RUN")
        self.assertIn("per-stage", saved["detail"])

    def test_inventory_freeze_validation_rejects_unknown_scenario_and_control_fields(self):
        scenarios = json.loads((ROOT / "integration" / "scenarios.json").read_text())["scenarios"]
        controls = json.loads((ROOT / "integration" / "control-scenarios.json").read_text())["controls"]
        scenarios[0]["unexpectedCancellationPolicy"] = "cancelEverything"
        with self.assertRaisesRegex(change_protocol.ProtocolError, "unknown scenario inventory field"):
            protocol_config.validate_input_inventories(scenarios, controls)

        scenarios = json.loads((ROOT / "integration" / "scenarios.json").read_text())["scenarios"]
        controls[0]["unexpectedAuthority"] = "wireTag"
        with self.assertRaisesRegex(change_protocol.ProtocolError, "unknown control inventory field"):
            protocol_config.validate_input_inventories(scenarios, controls)

    def test_real_tree_freeze_and_check_sources_ignore_generated_outputs(self):
        output_parent = ROOT / "reports" / "standalone"
        output_parent.mkdir(parents=True, exist_ok=True)
        config = protocol_config.build_config(
            ROOT,
            output_parent / "attempts" / "real-tree-snapshot-test",
            BASELINE,
        )
        with tempfile.TemporaryDirectory(prefix="real-tree-manifest-", dir=output_parent) as directory:
            manifest_path = Path(directory) / "manifest.json"
            digest = change_protocol.freeze(ROOT, config, manifest_path)
            manifest = json.loads(manifest_path.read_text())
            frozen_digest = manifest["frozenSourceDigest"]
            self.assertEqual(change_protocol.check_sources(manifest, ROOT), frozen_digest)
            self.assertFalse(any(
                path.startswith("verification/formal/__pycache__/")
                for path in manifest["inputSnapshot"]
            ))
            self.assertNotIn(".DS_Store", manifest["inputSnapshot"])

            sentinel_paths = [
                ROOT / "verification" / "__pycache__" / f".protocol-generated-{os.getpid()}.pyc",
                ROOT / "verification" / "formal" / "__pycache__" / f".protocol-generated-{os.getpid()}.pyc",
                ROOT / "scripts" / "__pycache__" / f".protocol-generated-{os.getpid()}.pyc",
                ROOT / "apps" / "android-demo" / "app" / "build" / f".protocol-generated-{os.getpid()}",
                ROOT / "android" / "library" / "build" / f".protocol-generated-{os.getpid()}",
                ROOT / "android" / ".gradle-home" / "wrapper" / "dists" / f".protocol-generated-{os.getpid()}.part",
            ]
            created_directories = []
            try:
                for path in sentinel_paths:
                    missing = []
                    parent = path.parent
                    while not parent.exists():
                        missing.append(parent)
                        parent = parent.parent
                    path.parent.mkdir(parents=True, exist_ok=True)
                    created_directories.extend(reversed(missing))
                    path.write_text("generated cache output")
                self.assertEqual(change_protocol.check_sources(manifest, ROOT), frozen_digest)
            finally:
                for path in sentinel_paths:
                    path.unlink(missing_ok=True)
                for path in reversed(created_directories):
                    try:
                        path.rmdir()
                    except OSError:
                        pass
            self.assertEqual(digest, change_protocol.digest_bytes(manifest_path.read_bytes()))

    def test_run_stages_accepts_external_manifest_and_executes_real_protocol_stage(self):
        with tempfile.TemporaryDirectory(prefix="external-frozen-ledger-", dir=ROOT / "reports" / "standalone") as directory:
            temporary = Path(directory)
            frozen_directory = temporary / ("freeze-" + temporary.name)
            frozen = reproduce.freeze(ROOT, frozen_directory)
            manifest_path = Path(frozen["manifest"])
            manifest = json.loads(manifest_path.read_text())
            output_root = ROOT / manifest["outputRoot"]
            self.assertFalse((output_root / "manifest.json").exists())
            self.assertFalse((output_root / "manifest.sha256").exists())

            stdout = io.StringIO()
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    try:
                        exit_code = reproduce.main([
                            "run-stages",
                            "--candidate", str(ROOT),
                            "--output", str(output_root),
                            "--manifest", str(manifest_path),
                            "--manifest-digest", frozen["manifestDigest"],
                            "--stage", "integration-red",
                        ])
                    except SystemExit as error:
                        self.fail(f"run-stages rejected external manifest arguments: {error}; {stderr.getvalue()}")

                report = json.loads(stdout.getvalue().splitlines()[-1])
                self.assertEqual(exit_code, 0)
                self.assertEqual(report["classification"], "PASS")
                self.assertEqual(report["stageResults"][0]["classification"], "SEMANTIC_FAIL")
                self.assertEqual(report["stageResults"][0]["bindingClassification"], "PASS")
                self.assertTrue((output_root / "auto-integration-red" / "result.json").is_file())
                self.assertTrue((output_root / "suite-report.json").is_file())
                owner = json.loads((output_root / "ledger-owner.json").read_text())
                self.assertEqual(owner["manifestDigest"], frozen["manifestDigest"])
                self.assertEqual(
                    change_protocol.digest_bytes((output_root / ".manifest-digest").read_bytes()),
                    owner["manifestOwnerSha256"],
                )
                verified_owner = integration_aggregate._verify_ledger_root(
                    output_root,
                    report,
                    frozen["manifestDigest"],
                    owner["candidateDigests"][0],
                    ["integration-red"],
                    "ios",
                )
                self.assertEqual(verified_owner, owner)
            finally:
                if output_root.exists():
                    shutil.rmtree(output_root)

    def test_candidate_scope_does_not_include_protected_debug_or_harness_paths(self):
        config = protocol_config.build_config(
            ROOT,
            ROOT / "reports" / "standalone" / "attempts" / "scope-test",
            BASELINE,
        )
        allowed = config["allowedPaths"]
        protected = config["protectedPaths"]

        self.assertTrue(any(path.startswith("apps/ios-demo/NativeContractDemo/Coordinator/") for path in allowed))
        self.assertTrue(any(path.startswith("apps/android-demo/app/src/main/java/nativecontract/demo/coordinator/") for path in allowed))
        protected_debug = {
            "apps/ios-demo/NativeContractDemo/Debug/StorageProbe.swift",
            "apps/ios-demo/NativeContractDemo/Debug/DebugScenarioControl.swift",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/StorageProbe.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugScenarioControl.kt",
        }
        candidate_debug_glue = {
            "apps/ios-demo/NativeContractDemo/Debug/DefaultDebugScenarioControl.swift",
            "apps/ios-demo/NativeContractDemo/Debug/DebugScenarioHooks.swift",
            "apps/ios-demo/NativeContractDemo/Debug/DemoIngress.swift",
            "apps/ios-demo/NativeContractDemo/Debug/JSONLAuditRecorder.swift",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugDemoApplication.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DebugScenarioHooks.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DefaultDebugScenarioControl.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/DemoIngress.kt",
            "apps/android-demo/app/src/debug/java/nativecontract/demo/debug/JSONLAuditRecorder.kt",
        }
        self.assertTrue(protected_debug <= set(protected))
        self.assertFalse(protected_debug & set(allowed))
        self.assertTrue(candidate_debug_glue <= set(allowed))
        self.assertFalse(any(path.endswith(("/Debug/", "/debug/")) for path in allowed))
        self.assertNotIn("apps/ios-demo/NativeContractDemoUITests/ScenarioUITests.swift", allowed)
        self.assertNotIn("apps/android-demo/app/src/androidTest/java/nativecontract/demo/ScenarioInstrumentedTest.kt", allowed)
        self.assertIn("integration/", protected)
        self.assertIn("scripts/ci-native-devices.py", protected)
        self.assertIn("apps/ios-demo/NativeContractDemo/Debug/DebugScenarioControl.swift", protected)
        self.assertIn("apps/android-demo/app/src/androidTest/java/nativecontract/demo/ScenarioInstrumentedTest.kt", protected)

    def test_candidate_report_binds_every_variant_trace_to_its_platform_build(self):
        config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/trace-binding-config", BASELINE)
        stage = config["stages"]["candidate-ios"]
        artifacts = [item["path"] for item in stage["requiredArtifacts"] if item["validator"] != "integration-report"]
        digest = "sha256:" + "d" * 64
        row = {
            "platform": "ios",
            "classification": "PASS",
            "validationScope": "ci",
            "requiredScenarioIds": stage["requiredScenarioIds"],
            "completedScenarioIds": stage["requiredScenarioIds"],
            "missingScenarioIds": [],
            "deviceHash": digest,
            "buildHash": digest,
            "requiredArtifacts": artifacts,
        }
        report = {
            "version": 1,
            "stageId": "candidate-ios",
            "classification": "PASS",
            "requiredScenarioIds": stage["requiredScenarioIds"],
            "platformResults": [row],
            "violations": [],
            "deviceHashes": {"ios": digest},
            "buildHashes": {"ios": digest},
            "requiredArtifacts": artifacts,
            "traceBindings": [{**binding, "buildHash": digest} for binding in stage["expectedTraceBindings"]],
        }
        with tempfile.TemporaryDirectory(prefix="standalone-ios-trace-bindings-") as directory:
            report_path = Path(directory) / "candidate-ios" / "report.json"
            report_path.parent.mkdir()
            report_path.write_text(json.dumps(report))

            validated = change_protocol.integration_report(report_path, stage)
            missing_variant = copy.deepcopy(report)
            missing_variant["traceBindings"].pop()
            report_path.write_text(json.dumps(missing_variant))
            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.integration_report(report_path, stage)

            mismatched_build = copy.deepcopy(report)
            mismatched_build["traceBindings"][0]["buildHash"] = "sha256:" + "e" * 64
            report_path.write_text(json.dumps(mismatched_build))
            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.integration_report(report_path, stage)

        self.assertEqual(validated["classification"], "PASS")

    def test_config_builder_rejects_noncanonical_output_and_baseline(self):
        with self.assertRaises(ValueError):
            protocol_config.build_config(ROOT, Path(tempfile.gettempdir()) / "outside-output", BASELINE)
        with self.assertRaises(ValueError):
            protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/bad", "short")

    def test_freeze_wrapper_delegates_manifest_binding_without_freezing_here(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            output = Path(temporary) / "freeze-test"
            with patch("integration.reproduce.protocol.freeze", return_value="a" * 64) as frozen:
                result = reproduce.freeze(ROOT, output)
            self.assertTrue((output / "protocol-config.json").is_file())
            self.assertEqual((output / "manifest.sha256").read_text(), "a" * 64 + "\n")

        self.assertEqual(result["classification"], "PASS")
        self.assertEqual(result["manifestDigest"], "a" * 64)
        args = frozen.call_args.args
        self.assertEqual(args[0], ROOT)
        self.assertEqual(args[1]["baselineCommit"], protocol_config.acceptance_baseline(ROOT))
        self.assertEqual(args[2].name, "manifest.json")


class ReproduceWrapperTests(unittest.TestCase):
    def test_suite_aggregation_accepts_only_bound_red_and_requires_every_native_stage(self):
        expected = [
            {"stageId": "integration-red", "classification": "SEMANTIC_FAIL", "bindingClassification": "PASS"},
            *[
                {"stageId": stage, "classification": "PASS", "bindingClassification": "PASS"}
                for stage in ("candidate-ios", "candidate-android", "integration-controls", "legacy-full")
            ],
        ]

        self.assertEqual(reproduce.aggregate_suite_results(expected)["classification"], "PASS")

        false_negative = list(expected)
        false_negative[0] = {**false_negative[0], "classification": "PASS"}
        self.assertEqual(reproduce.aggregate_suite_results(false_negative)["classification"], "INFRA_FAILURE")

        missing_control = expected[:3] + expected[4:]
        self.assertEqual(reproduce.aggregate_suite_results(missing_control)["classification"], "INVALID_HISTORY")

        unbound = list(expected)
        unbound[1] = {**unbound[1], "bindingClassification": "INFRA_FAILURE"}
        self.assertEqual(reproduce.aggregate_suite_results(unbound)["classification"], "INFRA_FAILURE")

    def test_run_suite_checks_each_saved_result_and_writes_bound_aggregate(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as directory:
            temporary = Path(directory)
            manifest_directory = temporary / ("freeze-" + temporary.name)
            frozen = reproduce.freeze(ROOT, manifest_directory)
            manifest = json.loads(Path(frozen["manifest"]).read_text())
            output = ROOT / manifest["outputRoot"]
            self.addCleanup(shutil.rmtree, output, ignore_errors=True)
            output.mkdir(parents=True)
            (output / ".manifest-digest").write_text(frozen["manifestDigest"] + "\n")
            stage_results = [
                {
                    "stageId": stage,
                    "attemptId": "auto-" + stage,
                    "classification": status,
                    "outputDirectory": str(output / ("auto-" + stage)),
                }
                for stage, status in zip(
                    ("integration-red", "candidate-ios", "candidate-android", "integration-controls", "legacy-full"),
                    ("SEMANTIC_FAIL", "PASS", "PASS", "PASS", "PASS"),
                )
            ]
            for row in stage_results:
                result_dir = Path(row["outputDirectory"])
                result_dir.mkdir()
                (result_dir / "result.json").write_text("{}\n")
            operation_order = []

            def fake_run_one(candidate, manifest, digest, stage, attempt):
                operation_order.append(("run", stage))
                return next(row for row in stage_results if row["stageId"] == stage)

            def fake_check(candidate, manifest, digest, result_path):
                operation_order.append(("check", result_path.parent.name.removeprefix("auto-")))
                return {"bindingClassification": "PASS"}

            with patch("integration.reproduce.run_one", side_effect=fake_run_one) as run_call:
                with patch("integration.reproduce.check", side_effect=fake_check) as check_call:
                    result = reproduce.run_suite(candidate=ROOT, output=manifest_directory)
            self.assertTrue((output / "suite-report.json").is_file())

        self.assertEqual(result["classification"], "PASS")
        self.assertEqual(run_call.call_count, 5)
        self.assertEqual(check_call.call_count, 5)
        self.assertEqual(
            operation_order,
            [(action, stage) for stage in ("integration-red", "candidate-ios", "candidate-android", "integration-controls", "legacy-full") for action in ("run", "check")],
        )

    def test_run_stages_records_only_the_frozen_platform_subset(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as directory:
            temporary = Path(directory)
            manifest_directory = temporary / ("freeze-" + temporary.name)
            frozen = reproduce.freeze(ROOT, manifest_directory)
            manifest_path = Path(frozen["manifest"])
            manifest = json.loads(manifest_path.read_text())
            output = ROOT / manifest["outputRoot"]
            self.addCleanup(shutil.rmtree, output, ignore_errors=True)
            output.mkdir(parents=True)
            (output / ".manifest-digest").write_text(frozen["manifestDigest"] + "\n")
            output_directory = output / "auto-candidate-ios"
            output_directory.mkdir(parents=True)
            (output_directory / "result.json").write_text("{}\n")
            with patch("integration.reproduce.run_one", return_value={
                "classification": "PASS",
                "stageId": "candidate-ios",
                "attemptId": "auto-candidate-ios",
                "outputDirectory": str(output_directory),
            }) as run_one, patch("integration.reproduce.check", return_value={
                "classification": "PASS",
                "bindingClassification": "PASS",
            }):
                report = reproduce.run_stages(
                    candidate=ROOT,
                    output=output,
                    stages=["candidate-ios"],
                    manifest=manifest_path,
                    manifest_digest=frozen["manifestDigest"],
                )

            self.assertEqual(run_one.call_count, 1)
            self.assertEqual(report["selectedStages"], ["candidate-ios"])
            self.assertEqual(report["classification"], "PASS")
            self.assertEqual(report["stageResults"][0]["bindingClassification"], "PASS")

    def _run_stages_with(self, outcomes, *, stages, continue_after_failure=False):
        """Run the real run_stages with a stubbed per-stage protocol run."""
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as directory:
            temporary = Path(directory)
            frozen = reproduce.freeze(ROOT, temporary / ("freeze-" + temporary.name))
            manifest_path = Path(frozen["manifest"])
            output = ROOT / json.loads(manifest_path.read_text())["outputRoot"]
            self.addCleanup(shutil.rmtree, output, ignore_errors=True)
            output.mkdir(parents=True)
            (output / ".manifest-digest").write_text(frozen["manifestDigest"] + "\n")
            progress = temporary / "progress.log"
            calls = []

            def run_one(candidate, manifest, digest, stage_id, attempt_id):
                calls.append(stage_id)
                directory = output / attempt_id
                directory.mkdir(parents=True)
                (directory / "result.json").write_text("{}\n")
                classification, timed_out = outcomes[stage_id]
                return {
                    "classification": classification,
                    "stageId": stage_id,
                    "attemptId": attempt_id,
                    "outputDirectory": str(directory),
                    "timedOut": timed_out,
                    "durationSeconds": 1.5,
                    "detail": f"{stage_id} detail",
                }

            with patch.dict(os.environ, {"NATIVE_CONTRACT_PROGRESS_LOG": str(progress)}), \
                    patch("integration.reproduce.run_one", side_effect=run_one), \
                    patch("integration.reproduce.check", return_value={"classification": "PASS", "bindingClassification": "PASS"}):
                report = reproduce.run_stages(
                    candidate=ROOT,
                    output=output,
                    stages=stages,
                    manifest=manifest_path,
                    manifest_digest=frozen["manifestDigest"],
                    continue_after_failure=continue_after_failure,
                )
            owner = json.loads((output / "ledger-owner.json").read_text())
            return report, calls, progress.read_text(), owner

    IOS_STAGES = ["integration-red", "candidate-ios", "integration-controls", "legacy-full"]

    def test_run_stages_stops_after_an_infra_failure_and_records_skipped_stages(self):
        report, calls, progress, owner = self._run_stages_with(
            {
                "integration-red": ("SEMANTIC_FAIL", False),
                "candidate-ios": ("INFRA_FAILURE", True),
                "integration-controls": ("PASS", False),
                "legacy-full": ("PASS", False),
            },
            stages=self.IOS_STAGES,
        )

        # integration-red's expected semantic failure does not stop the ledger.
        self.assertEqual(calls, ["integration-red", "candidate-ios"])
        self.assertEqual(report["classification"], "INFRA_FAILURE")
        self.assertEqual([row["stageId"] for row in report["stageResults"]], self.IOS_STAGES)
        skipped = report["stageResults"][2:]
        for row in skipped:
            self.assertEqual(row["classification"], "NOT_RUN")
            self.assertEqual(row["acceptanceClassification"], "NOT_RUN")
            self.assertEqual(row["skippedAfter"], {"stageId": "candidate-ios", "classification": "INFRA_FAILURE", "timedOut": True})
        self.assertEqual(owner["attemptIds"], ["auto-integration-red", "auto-candidate-ios"])
        self.assertIn("stage-start stage=candidate-ios index=2/4", progress)
        self.assertIn("stage-end stage=candidate-ios classification=INFRA_FAILURE timedOut=true", progress)
        self.assertIn("stage-skip stage=integration-controls after=candidate-ios", progress)
        self.assertIn("stage-skip stage=legacy-full after=candidate-ios", progress)

    def test_run_stages_runs_every_stage_when_asked_to_continue_for_diagnosis(self):
        report, calls, _, owner = self._run_stages_with(
            {
                "integration-red": ("SEMANTIC_FAIL", False),
                "candidate-ios": ("INFRA_FAILURE", True),
                "integration-controls": ("PASS", False),
                "legacy-full": ("PASS", False),
            },
            stages=self.IOS_STAGES,
            continue_after_failure=True,
        )

        self.assertEqual(calls, self.IOS_STAGES)
        self.assertFalse(any("skippedAfter" in row for row in report["stageResults"]))
        self.assertEqual(len(owner["attemptIds"]), 4)

    def test_run_stages_does_not_stop_on_a_semantic_failure(self):
        report, calls, _, _ = self._run_stages_with(
            {
                "integration-red": ("SEMANTIC_FAIL", False),
                "candidate-ios": ("SEMANTIC_FAIL", False),
                "integration-controls": ("PASS", False),
                "legacy-full": ("PASS", False),
            },
            stages=self.IOS_STAGES,
        )

        self.assertEqual(calls, self.IOS_STAGES)
        self.assertEqual(report["classification"], "SEMANTIC_FAIL")

    def test_run_stages_rejects_output_root_different_from_external_manifest(self):
        with tempfile.TemporaryDirectory(prefix="external-manifest-mismatch-", dir=ROOT / "reports" / "standalone") as directory:
            temporary = Path(directory)
            frozen_directory = temporary / ("freeze-" + temporary.name)
            frozen = reproduce.freeze(ROOT, frozen_directory)
            manifest_path = Path(frozen["manifest"])
            wrong_output = ROOT / "reports" / "standalone" / "attempts" / ("wrong-" + temporary.name)

            with self.assertRaisesRegex(change_protocol.ProtocolError, "output root differs from frozen manifest"):
                reproduce.run_stages(
                    candidate=ROOT,
                    output=wrong_output,
                    stages=["integration-red"],
                    manifest=manifest_path,
                    manifest_digest=frozen["manifestDigest"],
                )
            self.assertFalse(wrong_output.exists())

    def test_run_preserves_invalid_history_instead_of_infra_fallback(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as directory:
            output = Path(directory)
            (output / "manifest.json").write_text("{}\n")
            (output / "manifest.sha256").write_text("e" * 64 + "\n")
            with patch("integration.reproduce.run_one", return_value={
                "stageId": "candidate-ios",
                "classification": "INVALID_HISTORY",
            }):
                result = reproduce.run(candidate=ROOT, output=output, stages=["candidate-ios"])

        self.assertEqual(result["classification"], "INVALID_HISTORY")

    def test_run_suite_cli_returns_the_aggregate_verdict(self):
        stdout = io.StringIO()
        aggregate = {"classification": "NOT_RUN", "stageResults": []}
        with patch("integration.reproduce.run_suite", return_value=aggregate):
            with contextlib.redirect_stdout(stdout):
                code = reproduce.main(["run-suite", "--candidate", str(ROOT), "--output", "reports/standalone/suite-cli"])

        self.assertEqual(code, 3)
        self.assertEqual(json.loads(stdout.getvalue())["classification"], "NOT_RUN")

    def test_stage_runs_real_unsafe_adapter_and_builds_bound_semantic_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "integration-red"
            result = reproduce.stage(candidate=ROOT, stage_id="integration-red", output=output)

            self.assertEqual(result["classification"], "SEMANTIC_FAIL")
            report_path = output / "report.json"
            report = json.loads(report_path.read_text())
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/test", BASELINE)
            stage = config["stages"]["integration-red"]
            validated = change_protocol.integration_report(report_path, stage)
            self.assertEqual(validated["classification"], "SEMANTIC_FAIL")
            self.assertEqual(validated["requiredScenarioIds"], ["APP-02", "APP-04"])
            found = {}
            for violation in report["violations"]:
                found.setdefault(violation["scenarioId"], set()).add(violation["invariant"])
            self.assertTrue({"I2", "I3"} <= found["APP-02"])
            self.assertIn("I4", found["APP-04"])
            self.assertTrue(all((output / scenario / name).is_file() for scenario in ("APP-02", "APP-04") for name in ("trace.json", "server-events.json", "ui-observations.json", "report.json")))

    def test_integration_red_cli_returns_bound_semantic_exit(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            output = Path(temporary) / "integration-red"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = reproduce.main([
                    "stage", "--candidate", str(ROOT), "--stage", "integration-red", "--output", str(output)
                ])
            records = [line for line in stdout.getvalue().splitlines() if line.strip().startswith("{")]
            final = json.loads(records[-1])

        self.assertEqual(exit_code, 1)
        self.assertEqual(final["classification"], "SEMANTIC_FAIL")

    def test_manifest_run_and_check_wrappers_delegate_to_change_protocol(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "reports" / "standalone") as temporary:
            output = Path(temporary)
            (output / "manifest.json").write_text("{}\n")
            (output / "manifest.sha256").write_text("b" * 64 + "\n")
            run_result = {"classification": "SEMANTIC_FAIL", "stageId": "integration-red"}
            with patch("integration.reproduce.protocol.run", return_value=run_result) as run_call:
                result = reproduce.run(candidate=ROOT, output=output, stages=["integration-red"])
            self.assertEqual(result["classification"], "SEMANTIC_FAIL")
            self.assertEqual(run_call.call_args.args[1], "b" * 64)

            with patch("integration.reproduce.protocol.check", return_value={"classification": "PASS"}) as check_call:
                checked = reproduce.check(ROOT, output / "manifest.json", "b" * 64)
            self.assertEqual(checked["classification"], "PASS")
            self.assertEqual(check_call.call_args.args[:3], (output / "manifest.json", "b" * 64, ROOT))

    def test_platform_stage_without_native_runner_is_not_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "candidate-ios"
            environment = os.environ.copy()
            environment.pop("IOS_SIMULATOR_UDID", None)
            environment.pop("ANDROID_SERIAL", None)
            with patch.dict(os.environ, environment, clear=True):
                result = reproduce.stage(candidate=ROOT, stage_id="candidate-ios", output=output)
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/not-run-stage", BASELINE)
            validated = change_protocol.integration_report(output / "report.json", config["stages"]["candidate-ios"])

            self.assertEqual(result["classification"], "NOT_RUN")
            self.assertEqual(validated["classification"], "NOT_RUN")
            self.assertEqual(json.loads((output / "report.json").read_text())["classification"], "NOT_RUN")
            self.assertTrue(all((output.parent / path).is_file() for path in result["report"]["requiredArtifacts"]))

    def test_controls_stage_without_native_runner_remains_not_run_with_checked_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "integration-controls"
            result = reproduce.stage(candidate=ROOT, stage_id="integration-controls", output=output)
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/control-notrun", BASELINE)
            stage = config["stages"]["integration-controls"]
            model_artifact = output / stage["modelReportPath"]
            checked_model = change_protocol.model_report(
                model_artifact, stage["requiredModelWitnesses"]
            )
            artifacts = change_protocol.read_artifacts(Path(temporary), stage, started_ns=0)

        self.assertEqual(result["classification"], "NOT_RUN")
        self.assertEqual(checked_model["classification"], "PASS")
        self.assertEqual(result["report"]["controlResults"], [])
        self.assertIn("integration-controls/model/baseline/report.json", artifacts)

    def test_controls_stage_freezes_per_control_witnesses_and_model_artifact(self):
        config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/control-config", BASELINE)
        stage = config["stages"]["integration-controls"]
        controls = json.loads((ROOT / "integration/control-scenarios.json").read_text())["controls"]
        expected = {row["id"]: row["witnessInvariants"] for row in controls}

        self.assertEqual(stage["expectedControlWitnesses"], expected)
        self.assertEqual(stage["modelReportPath"], "model/baseline/report.json")
        self.assertIn(
            {"platform": "ios", "scenarioId": "APP-13", "variantId": "wrong-correlation-after-login-b"},
            config["stages"]["candidate-ios"]["expectedTraceBindings"],
        )
        self.assertTrue(stage["requiredModelWitnesses"])
        self.assertEqual(stage["requiredMutantWitnesses"], protocol_config.MODEL_MUTANT_WITNESSES)
        self.assertIn(
            {"path": "integration-controls/model/baseline/report.json", "validator": "model-report"},
            stage["requiredArtifacts"],
        )
        self.assertEqual(
            sum(item["validator"] == "model-mutant-report" for item in stage["requiredArtifacts"]),
            len(protocol_config.MODEL_MUTANT_WITNESSES),
        )

    @classmethod
    def setUpClass(cls):
        cls._model_temp = tempfile.TemporaryDirectory(prefix="standalone-protocol-model-")
        cls.model_report = integration_model.explore(output=Path(cls._model_temp.name) / "baseline")
        cls.model_mutants = {
            mutant: integration_model.explore(output=Path(cls._model_temp.name) / mutant, mutant=mutant)
            for mutant in protocol_config.MODEL_MUTANT_WITNESSES
        }

    @classmethod
    def tearDownClass(cls):
        cls._model_temp.cleanup()

    def _complete_controls_report(self, stage):
        artifacts = [item["path"] for item in stage["requiredArtifacts"] if item["validator"] != "integration-report"]
        control_ids = stage["requiredScenarioIds"]
        platform_rows = []
        device_hashes, build_hashes = {}, {}
        for platform in stage["expectedPlatforms"]:
            platform_artifacts = [path for path in artifacts if path.startswith(f"integration-controls/{platform}/")]
            device_digest = "sha256:" + ("a" if platform == "ios" else "b") * 64
            scenario_build_hashes = {
                control_id: "sha256:" + format(index + (1 if platform == "ios" else 20), "064x")
                for index, control_id in enumerate(control_ids)
            }
            platform_rows.append({
                "platform": platform,
                "classification": "PASS",
                "validationScope": "ci",
                "requiredScenarioIds": control_ids,
                "completedScenarioIds": control_ids,
                "missingScenarioIds": [],
                "deviceHash": device_digest,
                "buildHash": None,
                "scenarioBuildHashes": scenario_build_hashes,
                "requiredArtifacts": platform_artifacts,
            })
            device_hashes[platform] = device_digest
            build_hashes[platform] = None
        control_results = []
        trace_bindings = []
        for platform in stage["expectedPlatforms"]:
            scenario_builds = next(row["scenarioBuildHashes"] for row in platform_rows if row["platform"] == platform)
            for binding in stage["expectedTraceBindings"]:
                if binding["platform"] == platform:
                    trace_bindings.append({**binding, "buildHash": scenario_builds[binding["scenarioId"]]})
            for control_id, witnesses in stage["expectedControlWitnesses"].items():
                control_results.append({
                    "platform": platform,
                    "controlId": control_id,
                    "classification": "DETECTED",
                    "observedWitnesses": list(witnesses),
                })
        return {
            "version": 1,
            "stageId": "integration-controls",
            "classification": "PASS",
            "requiredScenarioIds": control_ids,
            "platformResults": platform_rows,
            "violations": [],
            "deviceHashes": device_hashes,
            "buildHashes": build_hashes,
            "requiredArtifacts": artifacts,
            "controlResults": control_results,
            "traceBindings": trace_bindings,
        }

    def _write_model_reports(self, output, stage):
        baseline_path = output / stage["modelReportPath"]
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(self.model_report))
        for mutant in stage["requiredMutantWitnesses"]:
            path = output / "model" / "mutants" / mutant / "report.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.model_mutants[mutant]))

    def test_controls_report_requires_every_per_platform_witness(self):
        with tempfile.TemporaryDirectory(prefix="standalone-control-report-") as directory:
            output = Path(directory) / "integration-controls"
            output.mkdir()
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/control-report", BASELINE)
            stage = config["stages"]["integration-controls"]
            self._write_model_reports(output, stage)
            report_path = output / "report.json"
            report = self._complete_controls_report(stage)
            report_path.write_text(json.dumps(report))

            validated = change_protocol.integration_report(report_path, stage)

        self.assertEqual(validated["classification"], "PASS")

    def test_complete_controls_cannot_pass_with_missing_named_witness(self):
        with tempfile.TemporaryDirectory(prefix="standalone-control-missing-witness-") as directory:
            output = Path(directory) / "integration-controls"
            output.mkdir()
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/control-missing", BASELINE)
            stage = config["stages"]["integration-controls"]
            self._write_model_reports(output, stage)
            report = self._complete_controls_report(stage)
            report["controlResults"][0]["observedWitnesses"] = ["I6"]
            report_path = output / "report.json"
            report_path.write_text(json.dumps(report))

            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.integration_report(report_path, stage)

    def test_complete_controls_cannot_pass_with_missing_variant_or_wrong_trace_build_hash(self):
        with tempfile.TemporaryDirectory(prefix="standalone-control-trace-binding-") as directory:
            output = Path(directory) / "integration-controls"
            output.mkdir()
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/control-trace-binding", BASELINE)
            stage = config["stages"]["integration-controls"]
            self._write_model_reports(output, stage)
            report = self._complete_controls_report(stage)
            report_path = output / "report.json"
            report["traceBindings"].pop()
            report_path.write_text(json.dumps(report))

            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.integration_report(report_path, stage)

            report = self._complete_controls_report(stage)
            report["traceBindings"][0]["buildHash"] = "sha256:" + "c" * 64
            report_path.write_text(json.dumps(report))
            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.integration_report(report_path, stage)

    def test_model_report_replays_witnesses_and_rejects_forged_final_state(self):
        with tempfile.TemporaryDirectory(prefix="standalone-control-model-replay-") as directory:
            output = Path(directory) / "integration-controls"
            output.mkdir()
            config = protocol_config.build_config(ROOT, ROOT / "reports/standalone/attempts/control-model", BASELINE)
            stage = config["stages"]["integration-controls"]
            self._write_model_reports(output, stage)
            forged = copy.deepcopy(self.model_report)
            forged["witnesses"]["APP-02-success-after-logout"]["finalState"]["physicalStore"] = "A1"
            (output / stage["modelReportPath"]).write_text(json.dumps(forged))
            report_path = output / "report.json"
            report_path.write_text(json.dumps(self._complete_controls_report(stage)))

            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.integration_report(report_path, stage)

    def test_each_model_mutant_report_replays_its_frozen_target_invariant(self):
        unexpected_families = {
            "unconditional-success-commit": ["I7", "I8"],
            "reentrant-consumer": [],
            "duplicate-deferred-clear": ["I2"],
            "unverified-publish": ["I3"],
            "failed-clear-ack": ["I3", "I5"],
        }
        for mutant, invariants in protocol_config.MODEL_MUTANT_WITNESSES.items():
            with self.subTest(mutant=mutant):
                with tempfile.TemporaryDirectory(prefix="standalone-model-mutant-report-") as directory:
                    path = Path(directory) / "report.json"
                    path.write_text(json.dumps(self.model_mutants[mutant]))
                    validated = change_protocol.model_mutant_report(path, mutant, invariants)

                self.assertIn(validated["counterexample"]["invariant"], invariants)
                self.assertEqual(validated["unexpectedMutantViolations"], unexpected_families[mutant])

    def test_model_mutant_report_rejects_wrong_named_invariant(self):
        mutant = "unverified-publish"
        report = copy.deepcopy(self.model_mutants[mutant])
        report["counterexample"]["invariant"] = "I4"
        report["invariantChecks"]["violations"] = ["I4"]
        with tempfile.TemporaryDirectory(prefix="standalone-model-mutant-wrong-target-") as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report))

            with self.assertRaises(change_protocol.ProtocolError):
                change_protocol.model_mutant_report(path, mutant, ["I6"])


if __name__ == "__main__":
    unittest.main()
