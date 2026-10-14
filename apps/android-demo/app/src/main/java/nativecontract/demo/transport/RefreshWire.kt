package nativecontract.demo.transport

import java.net.URI
import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.CredentialAccount
import nativecontract.demo.coordinator.Json
import nativecontract.demo.coordinator.JsonFormatException
import nativecontract.demo.coordinator.RefreshSlot

/** Strict versioned refresh envelope shared with integration/wire.py. */
object RefreshWire {
    const val MAXIMUM_BODY_BYTES = 16 * 1024

    class InvalidRequestException : Exception("invalid refresh request")

    /** Returns the absolute refresh endpoint for a plain origin base URL. */
    fun endpoint(baseUrl: String): String {
        val uri = try {
            URI(baseUrl)
        } catch (_: Exception) {
            throw InvalidRequestException()
        }
        val scheme = uri.scheme?.lowercase()
        if ((scheme != "http" && scheme != "https") || uri.host == null || uri.rawQuery != null || uri.rawFragment != null) {
            throw InvalidRequestException()
        }
        val basePath = (uri.rawPath ?: "").trim('/')
        val path = if (basePath.isEmpty()) "/v1/refresh" else "/$basePath/v1/refresh"
        val port = if (uri.port >= 0) ":${uri.port}" else ""
        return "$scheme://${uri.host}$port$path"
    }

    fun requestBody(runId: String, slot: RefreshSlot, credential: Credential): ByteArray {
        val expected = Credential.token(credential.account, credential.version)
        if (!isLabel(runId, 128) || !isLabel(slot.wireTag, 256) || slot.request.requestId <= 0L ||
            credential.account != slot.account || credential.version != slot.seedVersion ||
            credential.accessToken != expected || credential.refreshToken != expected
        ) {
            throw InvalidRequestException()
        }
        val body = Json.encode(
            mapOf(
                "version" to 1L,
                "runId" to runId,
                "requestTag" to slot.wireTag,
                "requestId" to slot.request.requestId.toString(),
                "account" to credential.account.raw,
                "refreshToken" to credential.refreshToken,
            ),
        ).toByteArray(Charsets.UTF_8)
        if (body.size > MAXIMUM_BODY_BYTES) throw InvalidRequestException()
        return body
    }

    fun parseResponse(body: ByteArray, statusCode: Int, expectedRunId: String, slot: RefreshSlot): RefreshOutcome {
        if (body.size > MAXIMUM_BODY_BYTES) return RefreshOutcome.Failure("malformed")
        val fields = try {
            Json.parse(String(body, Charsets.UTF_8)) as? Map<*, *>
        } catch (_: JsonFormatException) {
            null
        } ?: return RefreshOutcome.Failure("malformed")
        val runId = fields["runId"] as? String
        val requestTag = fields["requestTag"] as? String
        val outcome = fields["outcome"] as? String
        if (fields["version"] != 1L || runId == null || requestTag == null || outcome == null) {
            return RefreshOutcome.Failure("malformed")
        }
        if (runId != expectedRunId || requestTag != slot.wireTag) return RefreshOutcome.Failure("wrongCorrelation")

        if (statusCode == 401 || statusCode == 500) {
            val code = fields["failure"] as? String
            val valid = fields.keys == setOf("version", "runId", "requestTag", "outcome", "failure") &&
                outcome == "failure" &&
                ((statusCode == 401 && code == "rejected") || (statusCode == 500 && code == "server"))
            return if (valid) RefreshOutcome.Failure(code) else RefreshOutcome.Failure("malformed")
        }
        val credentialFields = fields["credential"] as? Map<*, *>
        if (statusCode != 200 || outcome != "success" ||
            fields.keys != setOf("version", "runId", "requestTag", "outcome", "credential") ||
            credentialFields == null ||
            credentialFields.keys != setOf("account", "version", "accessToken", "refreshToken") ||
            slot.seedVersion == Long.MAX_VALUE
        ) {
            return RefreshOutcome.Failure("malformed")
        }
        val account = (credentialFields["account"] as? String)?.let(CredentialAccount::fromRaw)
        val version = credentialFields["version"] as? Long
        val accessToken = credentialFields["accessToken"] as? String
        val refreshToken = credentialFields["refreshToken"] as? String
        val expectedVersion = slot.seedVersion + 1L
        val expectedToken = Credential.token(slot.account, expectedVersion)
        if (account != slot.account || version != expectedVersion || accessToken != expectedToken || refreshToken != expectedToken) {
            return RefreshOutcome.Failure("malformed")
        }
        return RefreshOutcome.Success(Credential(account, version, accessToken, refreshToken))
    }

    private fun isLabel(value: String, maximum: Int): Boolean =
        value.isNotEmpty() && value.toByteArray(Charsets.UTF_8).size <= maximum && value.all { it.code in 33..126 }
}
