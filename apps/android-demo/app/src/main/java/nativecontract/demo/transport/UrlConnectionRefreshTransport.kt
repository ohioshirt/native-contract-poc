package nativecontract.demo.transport

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.SocketTimeoutException
import java.net.URL
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.concurrent.atomic.AtomicInteger
import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.RefreshSlot

/**
 * Foreground refresh over [HttpURLConnection] on a dedicated HTTP executor. The
 * callback only parses and hands the completion to the coordinator; it never
 * touches storage or UI. Cancellation is best-effort physical disconnection.
 */
class UrlConnectionRefreshTransport(
    baseUrl: String,
    private val runId: String,
    private val onCompletionCaptured: ((Completion) -> Unit)? = null,
    private val executor: ExecutorService = Executors.newCachedThreadPool { runnable ->
        Thread(runnable, "native-contract-http-${THREADS.incrementAndGet()}").apply { isDaemon = true }
    },
) : RefreshTransport {
    private val endpoint: String? = try {
        RefreshWire.endpoint(baseUrl)
    } catch (_: RefreshWire.InvalidRequestException) {
        null
    }

    override fun start(slot: RefreshSlot, credential: Credential, completion: (Completion) -> Unit): TransportHandle {
        val handle = ConnectionHandle()
        val body = try {
            if (endpoint == null) throw RefreshWire.InvalidRequestException()
            RefreshWire.requestBody(runId, slot, credential)
        } catch (_: RefreshWire.InvalidRequestException) {
            executor.execute { deliver(handle, Completion(slot, RefreshOutcome.Failure("invalidRequest")), completion) }
            return handle
        }
        executor.execute {
            val outcome = perform(handle, endpoint, body, slot)
            deliver(handle, Completion(slot, outcome), completion)
        }
        return handle
    }

    private fun deliver(handle: ConnectionHandle, result: Completion, completion: (Completion) -> Unit) {
        try {
            onCompletionCaptured?.invoke(result)
            completion(result)
        } finally {
            handle.markCompleted()
        }
    }

    private fun perform(handle: ConnectionHandle, endpoint: String, body: ByteArray, slot: RefreshSlot): RefreshOutcome {
        var connection: HttpURLConnection? = null
        return try {
            connection = URL(endpoint).openConnection() as HttpURLConnection
            if (!handle.attach(connection)) return RefreshOutcome.Failure("disconnected")
            connection.instanceFollowRedirects = false
            connection.useCaches = false
            connection.connectTimeout = 10_000
            connection.readTimeout = 75_000
            connection.requestMethod = "POST"
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.setRequestProperty("Accept", "application/json")
            connection.setFixedLengthStreamingMode(body.size)
            connection.connect()
            // A cancel that raced the connect could not disconnect a socket that did not exist yet.
            if (handle.isCancelled) return RefreshOutcome.Failure("disconnected")
            connection.outputStream.use { it.write(body) }
            val status = connection.responseCode
            val stream = if (status >= 400) connection.errorStream else connection.inputStream
            val response = stream?.use { readBounded(it) } ?: ByteArray(0)
            if (response.size > RefreshWire.MAXIMUM_BODY_BYTES) {
                RefreshOutcome.Failure("malformed")
            } else {
                RefreshWire.parseResponse(response, status, runId, slot)
            }
        } catch (_: SocketTimeoutException) {
            RefreshOutcome.Failure("timeout")
        } catch (_: IOException) {
            RefreshOutcome.Failure("disconnected")
        } finally {
            connection?.disconnect()
        }
    }

    /** Reads at most one byte past the limit so oversize bodies are detected without buffering them. */
    private fun readBounded(stream: InputStream): ByteArray {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(4096)
        while (out.size() <= RefreshWire.MAXIMUM_BODY_BYTES) {
            val count = stream.read(buffer, 0, minOf(buffer.size, RefreshWire.MAXIMUM_BODY_BYTES + 1 - out.size()))
            if (count < 0) break
            out.write(buffer, 0, count)
        }
        return out.toByteArray()
    }

    private class ConnectionHandle : FencedTransportHandle {
        private val settled = CountDownLatch(1)
        private var connection: HttpURLConnection? = null
        private var cancelled = false

        /** Returns false when cancellation already happened before the connection existed. */
        @Synchronized
        fun attach(value: HttpURLConnection): Boolean {
            if (cancelled) return false
            connection = value
            return true
        }

        val isCancelled: Boolean @Synchronized get() = cancelled

        fun markCompleted() = settled.countDown()

        override fun cancel() {
            val current = synchronized(this) {
                cancelled = true
                connection
            }
            current?.disconnect()
        }

        override fun cancelAndWait(timeoutMillis: Long) {
            if (timeoutMillis <= 0L) throw TimeoutException("transport fence deadline exhausted")
            cancel()
            if (!settled.await(timeoutMillis, TimeUnit.MILLISECONDS)) {
                throw TimeoutException("transport producer did not settle")
            }
        }
    }

    private companion object {
        val THREADS = AtomicInteger()
    }
}
