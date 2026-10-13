package nativecontract.demo.storage

import android.util.AtomicFile
import java.io.File
import java.io.IOException
import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.CredentialAccount
import nativecontract.demo.coordinator.Json
import nativecontract.demo.coordinator.JsonFormatException

/** Strict codec for the one persisted credential blob; independent of the frozen probe parser. */
object CredentialBlob {
    private val keys = setOf("account", "version", "accessToken", "refreshToken")

    fun encode(credential: Credential): ByteArray = Json.encode(
        mapOf(
            "account" to credential.account.raw,
            "version" to credential.version,
            "accessToken" to credential.accessToken,
            "refreshToken" to credential.refreshToken,
        ),
    ).toByteArray(Charsets.UTF_8)

    fun decode(bytes: ByteArray): Credential {
        val fields = try {
            Json.parse(String(bytes, Charsets.UTF_8)) as? Map<*, *>
        } catch (_: JsonFormatException) {
            null
        } ?: throw CredentialStoreException(CredentialStoreErrorCode.MALFORMED_CREDENTIAL)
        if (fields.keys != keys) throw CredentialStoreException(CredentialStoreErrorCode.MALFORMED_CREDENTIAL)
        val account = (fields["account"] as? String)?.let(CredentialAccount::fromRaw)
        val version = fields["version"] as? Long
        val access = fields["accessToken"] as? String
        val refresh = fields["refreshToken"] as? String
        if (account == null || version == null || version < 0L || access == null || refresh == null) {
            throw CredentialStoreException(CredentialStoreErrorCode.MALFORMED_CREDENTIAL)
        }
        val credential = Credential(account, version, access, refresh)
        if (!isValid(credential)) throw CredentialStoreException(CredentialStoreErrorCode.MALFORMED_CREDENTIAL)
        return credential
    }

    fun isValid(credential: Credential): Boolean {
        val expected = Credential.token(credential.account, credential.version)
        return credential.version >= 0L && credential.accessToken == expected && credential.refreshToken == expected
    }
}

/**
 * One synthetic credential in an app-private no-backup directory owned by this
 * store. Writes use [AtomicFile] (`finishWrite` syncs); deletion removes only the
 * owned base file and its AtomicFile sidecars, never the namespace directory.
 */
class AtomicFileCredentialStore(private val directory: File) : CredentialStore, StoreFaultInjecting {
    private val base = File(directory, "credential.json")
    private val replacement = File(directory, "credential.json.new")
    private val legacyBackup = File(directory, "credential.json.bak")
    private val atomic = AtomicFile(base)

    @Volatile
    private var configuredFault: String? = null

    init {
        if (!directory.isDirectory && !directory.mkdirs()) {
            throw CredentialStoreException(CredentialStoreErrorCode.READ_FAILED)
        }
    }

    override fun setStoreFault(kind: String?) {
        configuredFault = kind?.takeIf { it in FAULTS }
    }

    @Synchronized
    override fun readVerified(): Credential? {
        // A sidecar means an interrupted AtomicFile write; never let a read repair it.
        if (replacement.exists() || legacyBackup.exists()) {
            throw CredentialStoreException(CredentialStoreErrorCode.READ_FAILED)
        }
        if (!base.exists()) return null
        if (!base.isFile) throw CredentialStoreException(CredentialStoreErrorCode.READ_FAILED)
        val bytes = try {
            base.readBytes()
        } catch (error: IOException) {
            throw CredentialStoreException(CredentialStoreErrorCode.READ_FAILED, error)
        }
        return CredentialBlob.decode(bytes)
    }

    @Synchronized
    override fun replaceVerified(credential: Credential) {
        if (!CredentialBlob.isValid(credential)) throw CredentialStoreException(CredentialStoreErrorCode.MALFORMED_CREDENTIAL)
        val before = readVerified()?.observation() ?: StoreObservation.Absent
        val fault = configuredFault
        if (fault == "replaceBefore") {
            throw CredentialStoreFailure("replace", fault, false, "notAttempted", before, before, before)
        }
        val stream = try {
            atomic.startWrite()
        } catch (error: IOException) {
            throw CredentialStoreException(CredentialStoreErrorCode.REPLACE_FAILED, error)
        }
        try {
            stream.write(CredentialBlob.encode(credential))
            atomic.finishWrite(stream)
        } catch (error: IOException) {
            atomic.failWrite(stream)
            throw CredentialStoreException(CredentialStoreErrorCode.REPLACE_FAILED, error)
        }
        if (fault == "replaceAfterBeforeVerify") {
            throw CredentialStoreFailure(
                "replace", fault, true, "failed", before,
                StoreObservation.Unknown("readFailed"), credential.observation(),
            )
        }
        if (readVerified() != credential) throw CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
    }

    @Synchronized
    override fun clearVerified() {
        val before = try {
            readVerified()?.observation() ?: StoreObservation.Absent
        } catch (error: CredentialStoreException) {
            StoreObservation.Unknown(error.code.safeCode)
        }
        val fault = configuredFault
        if (fault == "clearBefore") {
            throw CredentialStoreFailure("clear", fault, false, "notAttempted", before, before, before)
        }
        atomic.delete()
        if (base.exists() || replacement.exists() || legacyBackup.exists()) {
            throw CredentialStoreException(CredentialStoreErrorCode.CLEAR_FAILED)
        }
        if (fault == "clearAfterBeforeVerify") {
            throw CredentialStoreFailure(
                "clear", fault, true, "failed", before,
                StoreObservation.Unknown("readFailed"), StoreObservation.Absent,
            )
        }
        if (readVerified() != null) throw CredentialStoreException(CredentialStoreErrorCode.READBACK_FAILED)
    }

    private companion object {
        val FAULTS = setOf("replaceBefore", "replaceAfterBeforeVerify", "clearBefore", "clearAfterBeforeVerify")
    }
}
