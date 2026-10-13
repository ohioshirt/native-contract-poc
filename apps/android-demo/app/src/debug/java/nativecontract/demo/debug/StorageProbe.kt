package nativecontract.demo.debug

import android.content.Context
import java.io.File
import org.json.JSONObject
import nativecontract.demo.contract.StoreObservation

/**
 * Read-only uncached probe of the app-private test namespace. This parser and
 * file walk are independent of the candidate AtomicFileCredentialStore.
 */
object StorageProbe {
    private val credentialKeys = setOf("account", "version", "accessToken", "refreshToken")

    fun testNamespaceRelativePath(attemptId: String, scenarioId: String): String? {
        if (!isLabel(attemptId) || !isLabel(scenarioId)) return null
        return "demo-session/test-$attemptId/$scenarioId"
    }

    fun read(
        context: Context,
        attemptId: String,
        scenarioId: String,
        probeId: String,
        processInstanceId: String,
    ): ProbeResult {
        val namespace = testNamespaceRelativePath(attemptId, scenarioId)
            ?: return ProbeResult(probeId, processInstanceId, StoreObservation.Unknown("invalidProbeArgument"))
        val directory = File(context.noBackupFilesDir, namespace)
        val base = File(directory, "credential.json")
        val backup = File(directory, "credential.json.bak")
        val replacement = File(directory, "credential.json.new")
        val hasSidecar = backup.exists() || replacement.exists()
        if (!base.exists() && !hasSidecar) {
            return ProbeResult(probeId, processInstanceId, StoreObservation.Absent)
        }
        if (!base.isFile || hasSidecar) {
            return ProbeResult(probeId, processInstanceId, StoreObservation.Unknown("atomicSidecarPresent"))
        }
        val observation = try {
            redactCredentialBlob(base.readBytes())
        } catch (_: SecurityException) {
            StoreObservation.Unknown("readPermissionDenied")
        } catch (_: Exception) {
            StoreObservation.Unknown("readFailed")
        }
        return ProbeResult(probeId, processInstanceId, observation)
    }

    fun redactCredentialBlob(bytes: ByteArray): StoreObservation {
        return try {
            val json = JSONObject(String(bytes, Charsets.UTF_8))
            val keys = json.keys().asSequence().toSet()
            if (keys != credentialKeys) return StoreObservation.Unknown("invalidBlob")
            val account = json.get("account") as? String ?: return StoreObservation.Unknown("invalidBlob")
            if (account !in setOf("A", "B")) return StoreObservation.Unknown("invalidBlob")
            val rawVersion = json.get("version") as? Number ?: return StoreObservation.Unknown("invalidVersion")
            val version = rawVersion.toLong()
            val numericVersion = rawVersion.toDouble()
            if (version < 0L || !numericVersion.isFinite() || numericVersion != version.toDouble()) {
                return StoreObservation.Unknown("invalidVersion")
            }
            val expectedToken = "demo-$account-v$version"
            if (json.get("accessToken") != expectedToken || json.get("refreshToken") != expectedToken) {
                return StoreObservation.Unknown("tokenMismatch")
            }
            StoreObservation.Present(account, version)
        } catch (_: Exception) {
            StoreObservation.Unknown("invalidBlob")
        }
    }

    private fun isLabel(value: String): Boolean =
        value.length in 1..64 && value.all {
            it in 'A'..'Z' || it in 'a'..'z' || it in '0'..'9' || it == '-' || it == '_'
        }
}
