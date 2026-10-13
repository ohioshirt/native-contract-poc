package nativecontract.demo

import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.concurrent.CountDownLatch
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue
import nativecontract.async.ManagedAsyncSession
import nativecontract.async.ManagedEffect
import nativecontract.async.ManagedEvent
import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.CredentialAccount
import nativecontract.demo.coordinator.Json
import nativecontract.demo.coordinator.JsonFormatException
import nativecontract.demo.coordinator.RefreshSlot
import nativecontract.demo.coordinator.SessionEpoch
import nativecontract.demo.storage.CredentialBlob
import nativecontract.demo.storage.CredentialStoreException
import nativecontract.demo.transport.Completion
import nativecontract.demo.transport.FencedTransportHandle
import nativecontract.demo.transport.RefreshOutcome
import nativecontract.demo.transport.RefreshWire
import nativecontract.demo.transport.UrlConnectionRefreshTransport

class TransportTest {
    private var server: LoopbackServer? = null

    @AfterTest
    fun stopServer() {
        server?.close()
    }

    @Test
    fun requestBodyHasExactlyTheFrozenVersionOneFields() {
        val slot = slot()
        val body = Json.parse(String(RefreshWire.requestBody("run-1", slot, Credential.demo(CredentialAccount.A, 0L)))) as Map<*, *>

        // integration/wire.py parse_refresh requires exactly these keys.
        assertEquals(setOf("version", "runId", "requestTag", "requestId", "account", "refreshToken"), body.keys)
        assertEquals(1L, body["version"])
        assertEquals(slot.wireTag, body["requestTag"])
        assertEquals(slot.request.requestId.toString(), body["requestId"])
        assertEquals("demo-A-v0", body["refreshToken"])
    }

    @Test
    fun requestRejectsCredentialThatDoesNotMatchTheIssuedSlot() {
        assertFailsWith<RefreshWire.InvalidRequestException> {
            RefreshWire.requestBody("run-1", slot(), Credential.demo(CredentialAccount.B, 0L))
        }
        assertFailsWith<RefreshWire.InvalidRequestException> {
            RefreshWire.requestBody("run 1", slot(), Credential.demo(CredentialAccount.A, 0L))
        }
    }

    @Test
    fun responseParsingAcceptsOnlyCorrelatedExactEnvelopes() {
        val slot = slot()
        val success = """{"version":1,"runId":"run-1","requestTag":"${slot.wireTag}","outcome":"success","credential":{"account":"A","version":1,"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"""
        val parsed = RefreshWire.parseResponse(success.toByteArray(), 200, "run-1", slot)
        assertIs<RefreshOutcome.Success>(parsed)
        assertEquals(Credential.demo(CredentialAccount.A, 1L), parsed.credential)

        fun failure(body: String, status: Int = 200) =
            (RefreshWire.parseResponse(body.toByteArray(), status, "run-1", slot) as RefreshOutcome.Failure).code
        val tag = slot.wireTag
        assertEquals("rejected", failure("""{"version":1,"runId":"run-1","requestTag":"$tag","outcome":"failure","failure":"rejected"}""", 401))
        assertEquals("server", failure("""{"version":1,"runId":"run-1","requestTag":"$tag","outcome":"failure","failure":"server"}""", 500))
        assertEquals("malformed", failure("""{"version":1,"runId":"run-1","requestTag":"$tag","outcome":"failure","failure":"server"}""", 401))
        assertEquals("wrongCorrelation", failure(success.replace(tag, "$tag-other")))
        assertEquals("wrongCorrelation", failure(success.replace("run-1", "run-2")))
        assertEquals("malformed", failure(success.replace("\"version\":1,", "\"version\":1,\"version\":1,")))
        assertEquals("malformed", failure(success.replace("\"version\":1,\"runId\"", "\"version\":1.0,\"runId\"")))
        assertEquals("malformed", failure(success.replace("demo-A-v1\",\"refreshToken\"", "demo-A-v2\",\"refreshToken\"")))
        assertEquals("malformed", failure(success.replace("\"version\":1,\"accessToken\"", "\"version\":2,\"accessToken\"")))
        assertEquals("malformed", failure(success, 302))
        assertEquals("malformed", failure(" ".repeat(RefreshWire.MAXIMUM_BODY_BYTES + 1)))
    }

    /** Same literals as the Swift wire test: the wire carries plain integers only. */
    @Test
    fun nonIntegerNumberLiteralsAreMalformedLikeTheSwiftWire() {
        val slot = slot()
        fun body(envelope: String, credential: String) =
            """{"version":$envelope,"runId":"run-1","requestTag":"${slot.wireTag}","outcome":"success","credential":{"account":"A","version":$credential,"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"""
        assertIs<RefreshOutcome.Success>(RefreshWire.parseResponse(body("1", "1").toByteArray(), 200, "run-1", slot))
        for (literal in listOf("1.0", "1e0", "1E0", "1.0000000000000001", "10e-1")) {
            for ((envelope, credential) in listOf(literal to "1", "1" to literal)) {
                val outcome = RefreshWire.parseResponse(body(envelope, credential).toByteArray(), 200, "run-1", slot)
                assertEquals(RefreshOutcome.Failure("malformed"), outcome, "envelope $envelope, credential $credential")
            }
        }
    }

    @Test
    fun jsonDecoderIsStrictAndEncoderRoundTrips() {
        assertFailsWith<JsonFormatException> { Json.parse("""{"a":1,"a":2}""") }
        assertFailsWith<JsonFormatException> { Json.parse("""{"a":1} x""") }
        assertFailsWith<JsonFormatException> { Json.parse("""{"a":01}""") }
        assertFailsWith<JsonFormatException> { Json.parse("""{"a":9223372036854775808}""") }
        // integration/wire.py and the probe accept only ASCII JSON digits.
        assertFailsWith<JsonFormatException> { Json.parse("{\"version\":١}") }
        assertFailsWith<JsonFormatException> { Json.parse("{\"version\":1١}") }
        val value = mapOf("b" to listOf(1L, true, null, "q\"\n\u0001"), "a" to mapOf("c" to -2L))
        val encoded = Json.encode(value)
        assertEquals("""{"a":{"c":-2},"b":[1,true,null,"q\"\n\u0001"]}""", encoded)
        assertEquals(value, Json.parse(encoded))
    }

    @Test
    fun credentialBlobMatchesTheFrozenProbeShapeAndRejectsAnythingElse() {
        val credential = Credential.demo(CredentialAccount.B, 3L)
        val encoded = Json.parse(String(CredentialBlob.encode(credential))) as Map<*, *>
        // Frozen StorageProbe / controller redaction require exactly these four keys.
        assertEquals(setOf("account", "version", "accessToken", "refreshToken"), encoded.keys)
        assertEquals(credential, CredentialBlob.decode(CredentialBlob.encode(credential)))
        assertTrue("demo-B-v3" !in credential.toString())
        listOf(
            """{"account":"B","version":3,"accessToken":"demo-B-v3"}""",
            """{"account":"B","version":3,"accessToken":"demo-B-v3","refreshToken":"demo-B-v4"}""",
            """{"account":"C","version":3,"accessToken":"demo-C-v3","refreshToken":"demo-C-v3"}""",
            """{"account":"B","version":3.0,"accessToken":"demo-B-v3","refreshToken":"demo-B-v3"}""",
            """{"account":"B","version":3,"accessToken":"demo-B-v3","refreshToken":"demo-B-v3","extra":1}""",
        ).forEach { blob ->
            assertFailsWith<CredentialStoreException>(blob) { CredentialBlob.decode(blob.toByteArray()) }
        }
    }

    @Test
    fun urlConnectionTransportCompletesAgainstRealLoopbackHttp() {
        val requests = LinkedBlockingQueue<Map<*, *>>()
        val slot = slot()
        startServer { requestBody, socket ->
            val body = Json.parse(String(requestBody)) as Map<*, *>
            requests += body
            val response = """{"version":1,"runId":"run-1","requestTag":"${body["requestTag"]}","outcome":"success","credential":{"account":"A","version":1,"accessToken":"demo-A-v1","refreshToken":"demo-A-v1"}}"""
            respond(socket, "200 OK", response.toByteArray())
        }
        val completions = LinkedBlockingQueue<Completion>()

        UrlConnectionRefreshTransport(baseUrl(), "run-1").start(slot, Credential.demo(CredentialAccount.A, 0L)) { completions += it }
        val completion = completions.poll(10, TimeUnit.SECONDS) ?: error("no completion")

        assertTrue(completion.slot === slot)
        assertIs<RefreshOutcome.Success>(completion.outcome)
        assertEquals(slot.wireTag, requests.single()["requestTag"])
    }

    @Test
    fun redirectsAreNotFollowed() {
        val slot = slot()
        startServer { _, socket ->
            respond(socket, "302 Found", ByteArray(0), "Location: /elsewhere\r\n")
        }
        val completions = LinkedBlockingQueue<Completion>()

        UrlConnectionRefreshTransport(baseUrl(), "run-1").start(slot, Credential.demo(CredentialAccount.A, 0L)) { completions += it }

        assertEquals(RefreshOutcome.Failure("malformed"), completions.poll(10, TimeUnit.SECONDS)?.outcome)
    }

    @Test
    fun cancelAndWaitFencesAHeldRequestBeforeReturning() {
        val held = CountDownLatch(1)
        val releaseServer = CountDownLatch(1)
        startServer { _, _ ->
            held.countDown()
            releaseServer.await(20, TimeUnit.SECONDS)
        }
        val completions = LinkedBlockingQueue<Completion>()
        val handle = UrlConnectionRefreshTransport(baseUrl(), "run-1")
            .start(slot(), Credential.demo(CredentialAccount.A, 0L)) { completions += it }
        assertTrue(held.await(10, TimeUnit.SECONDS))

        (handle as FencedTransportHandle).cancelAndWait(10_000)

        assertEquals(RefreshOutcome.Failure("disconnected"), completions.poll()?.outcome)
        releaseServer.countDown()
    }

    private fun startServer(handler: (ByteArray, Socket) -> Unit) {
        server = LoopbackServer(handler)
    }

    private fun baseUrl(): String = "http://127.0.0.1:${server!!.port}"

    private fun respond(socket: Socket, status: String, body: ByteArray, extraHeaders: String = "") {
        val head = "HTTP/1.1 $status\r\nContent-Type: application/json\r\nContent-Length: ${body.size}\r\n${extraHeaders}Connection: close\r\n\r\n"
        socket.getOutputStream().apply {
            write(head.toByteArray(Charsets.US_ASCII))
            write(body)
            flush()
        }
    }

    private fun slot(): RefreshSlot {
        val session = ManagedAsyncSession()
        session.handle(ManagedEvent.LoginSucceeded)
        val request = session.handle(ManagedEvent.TokenExpired).effects
            .filterIsInstance<ManagedEffect.RequestTokenRefresh>().single().request
        return RefreshSlot("slot-A1", request, SessionEpoch(), 3L, "t5/APP-01/p1:refresh:3", CredentialAccount.A, 0L, "owner-test")
    }
}

/** Minimal HTTP/1.1 loopback server (no JDK-internal httpserver on the Android unit-test classpath). */
private class LoopbackServer(private val handler: (ByteArray, Socket) -> Unit) : AutoCloseable {
    private val socket = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
    val port: Int get() = socket.localPort

    init {
        thread(isDaemon = true) {
            while (!socket.isClosed) {
                val client = try {
                    socket.accept()
                } catch (_: IOException) {
                    break
                }
                thread(isDaemon = true) { client.use { handler(readBody(it), it) } }
            }
        }
    }

    override fun close() = socket.close()

    private fun readBody(client: Socket): ByteArray {
        val input = client.getInputStream()
        val header = StringBuilder()
        while (!header.endsWith("\r\n\r\n")) {
            val next = input.read()
            if (next < 0) return ByteArray(0)
            header.append(next.toChar())
        }
        val length = header.lines()
            .firstOrNull { it.startsWith("Content-Length:", ignoreCase = true) }
            ?.substringAfter(':')?.trim()?.toInt() ?: 0
        val body = ByteArray(length)
        var read = 0
        while (read < length) {
            val count = input.read(body, read, length - read)
            if (count < 0) break
            read += count
        }
        return body
    }
}
