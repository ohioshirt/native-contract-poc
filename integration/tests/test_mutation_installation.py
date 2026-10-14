import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from integration.mutation_installation import (
    MutationInstallationError,
    mutation_for_control,
    prepare_mutation_workspace,
)


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "integration/mutation_matrix.json"
MUTATIONS = json.loads(MATRIX.read_text())["mutations"]


def _function(language, name, body):
    keyword = "func" if language == "swift" else "fun"
    return f"    {keyword} {name}() {{\n        {body}\n    }}\n"


def _candidate_source(language):
    anchors = [mutation["anchors"][language] for mutation in MUTATIONS]
    declarations = []
    for anchor in anchors:
        body = anchor["before"].replace("\n", "\n        ")
        declarations.append(_function(language, anchor["function"], body))
    if language == "swift":
        host_methods = """    func n2PerformNormalVerifiedLogout(commandID: Int64) async throws {}
    func n2PauseBeforeDeferredControlClear(effectID: String, originCommandID: Int64) async {}
    func n2PerformDuplicateClearAndRecord(effectID: String, originCommandID: Int64) async {}
    func n4PublishSignedOutWithoutStoreClear(commandID: Int64) async {}
    func n4MakeCompletedLogoutReceipt(commandID: Int64) async -> CommandReceipt { CommandReceipt() }
"""
        return "actor SessionCoordinator {\n" + "\n".join(declarations) + host_methods + "}\n"
    host_methods = """    fun n2PerformNormalVerifiedLogout(commandId: Long) {}
    fun n2ScheduleDetachedEffect(effectId: String, originCommandId: Long, action: () -> Unit) { action() }
    fun n2PauseBeforeDeferredControlClear(effectId: String, originCommandId: Long) {}
    fun n2PerformDuplicateClearAndRecord(effectId: String, originCommandId: Long) {}
    fun n4PublishSignedOutWithoutStoreClear(commandId: Long) {}
    fun n4MakeCompletedLogoutReceipt(commandId: Long): CommandReceipt = CommandReceipt()
"""
    return "package nativecontract.demo.coordinator\n\nclass SessionCoordinator() {\n" + "\n".join(declarations) + host_methods + "}\n"


def _typed_swift_candidate():
    return '''import Foundation

struct Credential: Sendable {}
struct CommandReceipt: Sendable {}
struct Store {
    func replaceVerified(_ credential: Credential) throws {}
}
struct CompletionOutcome: Sendable { var isSuccess: Bool { true } }
struct Completion: Sendable { let outcome = CompletionOutcome() }

actor SessionCoordinator {
    let store = Store()
    func handleRefreshCompletion() {
        let eligible = true
        let acceptedSuccess = true
        let completion = Completion()
        let admittedSuccess = eligible && acceptedSuccess
        _ = (completion, admittedSuccess)
    }
    func handleLogout(commandID: Int64) async throws {
        try await clearThenPublishSignedOut(commandID: commandID)
    }
    func clearThenPublishSignedOut(commandID: Int64) async throws {}
    func commitRefreshSuccess(credential: Credential, commandID: Int64) async throws {
        try store.replaceVerified(credential)
        await publishSignedIn(credential, commandID: commandID)
    }
    func publishSignedIn(_ credential: Credential, commandID: Int64) async {}
    func handleLogoutClearFailure(error: Error, commandID: Int64) async -> CommandReceipt {
        return await lockAfterStoreFailure(error, commandID: commandID)
    }
    func lockAfterStoreFailure(_ error: Error, commandID: Int64) async -> CommandReceipt {
        CommandReceipt()
    }
    func n2PerformNormalVerifiedLogout(commandID: Int64) async throws {
        try await clearThenPublishSignedOut(commandID: commandID)
    }
    func n2PauseBeforeDeferredControlClear(effectID: String, originCommandID: Int64) async {}
    func n2PerformDuplicateClearAndRecord(effectID: String, originCommandID: Int64) async {}
    func n4PublishSignedOutWithoutStoreClear(commandID: Int64) async {}
    func n4MakeCompletedLogoutReceipt(commandID: Int64) async -> CommandReceipt { CommandReceipt() }
}
'''


def _typed_kotlin_candidate():
    return '''package nativecontract.demo.coordinator

data class Credential(val version: Long = 1)
data class CommandReceipt(val id: Long = 1)
data class CompletionOutcome(val isSuccess: Boolean = true)
data class Completion(val outcome: CompletionOutcome = CompletionOutcome())
class Store { fun replaceVerified(credential: Credential) {} }

class SessionCoordinator {
    private val store = Store()
    fun handleRefreshCompletion() {
        val eligible = true
        val acceptedSuccess = true
        val completion = Completion()
        val admittedSuccess = eligible && acceptedSuccess
        println("$completion:$admittedSuccess")
    }
    fun handleLogout(commandId: Long) {
        clearThenPublishSignedOut(commandId)
    }
    fun clearThenPublishSignedOut(commandId: Long) {}
    fun commitRefreshSuccess(credential: Credential, commandId: Long) {
        store.replaceVerified(credential)
        publishSignedIn(credential, commandId)
    }
    fun publishSignedIn(credential: Credential, commandId: Long) {}
    fun handleLogoutClearFailure(error: Throwable, commandId: Long): CommandReceipt {
        return lockAfterStoreFailure(error, commandId)
    }
    fun lockAfterStoreFailure(error: Throwable, commandId: Long): CommandReceipt = CommandReceipt(commandId)
    fun n2PerformNormalVerifiedLogout(commandId: Long) { clearThenPublishSignedOut(commandId) }
    fun n2ScheduleDetachedEffect(effectId: String, originCommandId: Long, action: () -> Unit) { action() }
    fun n2PauseBeforeDeferredControlClear(effectId: String, originCommandId: Long) {}
    fun n2PerformDuplicateClearAndRecord(effectId: String, originCommandId: Long) {}
    fun n4PublishSignedOutWithoutStoreClear(commandId: Long) {}
    fun n4MakeCompletedLogoutReceipt(commandId: Long): CommandReceipt = CommandReceipt(commandId)
}
'''


def _synthetic_candidate(root):
    matrix = root / "integration"
    matrix.mkdir(parents=True)
    shutil.copy2(MATRIX, matrix / "mutation_matrix.json")
    shutil.copytree(
        ROOT / "apps/android-demo",
        root / "apps/android-demo",
        ignore=shutil.ignore_patterns(".gradle", "build", ".kotlin"),
    )
    shutil.copytree(
        ROOT / "android/async-library",
        root / "android/async-library",
        ignore=shutil.ignore_patterns("build", ".gradle"),
    )
    for language in ("swift", "kotlin"):
        row = next(item for item in MUTATIONS)
        source_path = root / row["anchors"][language]["path"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(_candidate_source(language), encoding="utf-8")
    shutil.copytree(ROOT / "apps/ios-demo/MutationFixtures", root / "apps/ios-demo/MutationFixtures")
    (root / "apps/ios-demo/NativeContractDemo.xcodeproj").mkdir(parents=True)
    (root / "ios/Sources").mkdir(parents=True)
    shutil.copytree(ROOT / "contract", root / "contract")


class MutationInstallationTests(unittest.TestCase):
    def test_control_inventory_selects_one_hash_bound_source_mutation(self):
        self.assertEqual(
            mutation_for_control(control_id="CTRL-N1-LOGOUT", matrix_path=MATRIX),
            "N1-stale-payload-commit",
        )
        self.assertEqual(
            mutation_for_control(control_id="CTRL-N1-NEW-LOGIN", matrix_path=MATRIX),
            "N1-stale-payload-commit",
        )
        self.assertEqual(
            mutation_for_control(control_id="CTRL-N4-FALSE-LOGOUT", matrix_path=MATRIX),
            "N4-false-logout-ack",
        )
        with self.assertRaises(MutationInstallationError):
            mutation_for_control(control_id="APP-02", matrix_path=MATRIX)

    def test_each_mutant_workspace_is_isolated_and_binds_source_and_helper_hashes(self):
        for mutation in MUTATIONS:
            for platform, language in (("ios", "swift"), ("android", "kotlin")):
                with self.subTest(mutation=mutation["id"], platform=platform), tempfile.TemporaryDirectory(
                    prefix="native-mutant-copy-"
                ) as temporary:
                    root = Path(temporary) / "candidate"
                    root.mkdir()
                    _synthetic_candidate(root)
                    original = root / mutation["anchors"][language]["path"]
                    original_hash = __import__("hashlib").sha256(original.read_bytes()).hexdigest()
                    workspace = root / "reports" / "standalone" / "mutant-workspaces" / mutation["id"] / platform
                    workspace.parent.mkdir(parents=True)

                    provenance = prepare_mutation_workspace(
                        candidate=root,
                        workspace=workspace,
                        mutation_id=mutation["id"],
                        platform=platform,
                        matrix_path=root / "integration/mutation_matrix.json",
                    )

                    self.assertEqual(provenance["mutationId"], mutation["id"])
                    self.assertEqual(provenance["platform"], platform)
                    self.assertEqual(provenance["patchedPlatformSource"]["originalSha256"], original_hash)
                    self.assertNotEqual(
                        provenance["patchedPlatformSource"]["anchorPatchedSha256"], original_hash
                    )
                    self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), original_hash)
                    installed_source = workspace / mutation["anchors"][language]["path"]
                    self.assertEqual(
                        hashlib.sha256(installed_source.read_bytes()).hexdigest(),
                        provenance["patchedPlatformSource"]["materializedSha256"],
                    )
                    self.assertNotEqual(original.read_bytes(), installed_source.read_bytes())
                    self.assertEqual(
                        provenance["helper"] is not None,
                        bool(mutation.get("isolatedHelperRequired", False)),
                    )
                    if provenance["helper"]:
                        helper_file = workspace / provenance["helper"]["materializedPath"]
                        self.assertTrue(helper_file.is_file())
                        installed_coordinator = workspace / mutation["anchors"][language]["path"]
                        coordinator_text = installed_coordinator.read_text()
                        call = "debugClearThenScheduleDuplicate" if "N2" in mutation["id"] else "debugFalseLogoutReceipt"
                        self.assertIn(call, coordinator_text)
                        protocol = "N2DuplicateClearMutationHost" if "N2" in mutation["id"] else "N4FalseLogoutMutationHost"
                        self.assertIn(protocol, helper_file.read_text())
                        if platform == "android":
                            self.assertEqual(
                                provenance["helper"]["helperSha256"],
                                hashlib.sha256(helper_file.read_bytes()).hexdigest(),
                            )
                            self.assertIn(protocol, coordinator_text)
                            adapter_names = (
                                ("n2PerformNormalVerifiedLogout", "n2ScheduleDetachedEffect", "n2PauseBeforeDeferredControlClear", "n2PerformDuplicateClearAndRecord")
                                if "N2" in mutation["id"]
                                else ("n4PublishSignedOutWithoutStoreClear", "n4MakeCompletedLogoutReceipt")
                            )
                            for adapter_name in adapter_names:
                                self.assertIn(f"override fun {adapter_name}(", coordinator_text)
                        else:
                            helper_source = root / provenance["helper"]["helperPath"]
                            self.assertEqual(
                                provenance["helper"]["helperSha256"],
                                hashlib.sha256(helper_source.read_bytes()).hexdigest(),
                            )
                            self.assertIn("extension SessionCoordinator:", coordinator_text)
                    self.assertTrue(provenance["patchManifest"]["files"]["swift"]["mutatedSha256"])
                    self.assertTrue(provenance["patchManifest"]["files"]["kotlin"]["mutatedSha256"])

    def test_n2_n4_require_candidate_adapter_methods_before_helper_install(self):
        mutation = next(row for row in MUTATIONS if row["id"] == "N2-duplicate-deferred-clear")
        with tempfile.TemporaryDirectory(prefix="native-mutant-missing-adapter-") as temporary:
            root = Path(temporary) / "candidate"
            root.mkdir()
            _synthetic_candidate(root)
            source = root / mutation["anchors"]["swift"]["path"]
            source.write_text(source.read_text().replace(
                "func n2PerformDuplicateClearAndRecord(effectID: String, originCommandID: Int64) async {}\n", ""
            ))
            workspace = root / "reports/standalone/mutant-workspaces/N2/ios"
            workspace.parent.mkdir(parents=True)
            with self.assertRaisesRegex(MutationInstallationError, "n2PerformDuplicateClearAndRecord"):
                prepare_mutation_workspace(
                    candidate=root,
                    workspace=workspace,
                    mutation_id=mutation["id"],
                    platform="ios",
                    matrix_path=root / "integration/mutation_matrix.json",
                )

    @unittest.skipUnless(shutil.which("swiftc"), "Swift compiler is unavailable on this runner")
    def test_swift_helper_install_compiles_the_mutated_candidate_actor(self):
        for mutation_id in ("N2-duplicate-deferred-clear", "N4-false-logout-ack"):
            with self.subTest(mutation=mutation_id), tempfile.TemporaryDirectory(prefix="typed-swift-mutant-") as temporary:
                root = Path(temporary) / "candidate"
                root.mkdir()
                _synthetic_candidate(root)
                source_path = root / next(row for row in MUTATIONS if row["id"] == mutation_id)["anchors"]["swift"]["path"]
                source_path.write_text(_typed_swift_candidate(), encoding="utf-8")
                workspace = root / "reports/standalone/mutant-workspaces" / mutation_id / "ios"
                workspace.parent.mkdir(parents=True)
                prepare_mutation_workspace(
                    candidate=root,
                    workspace=workspace,
                    mutation_id=mutation_id,
                    platform="ios",
                    matrix_path=root / "integration/mutation_matrix.json",
                )
                copied_source = workspace / next(row for row in MUTATIONS if row["id"] == mutation_id)["anchors"]["swift"]["path"]
                module_cache = Path(temporary) / "swift-module-cache"
                module_cache.mkdir()
                completed = subprocess.run(
                    [
                        shutil.which("swiftc"), "-swift-version", "6", "-module-cache-path",
                        str(module_cache), "-typecheck", str(copied_source),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
