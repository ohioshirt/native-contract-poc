package nativecontract.demo.debug

import java.io.File
import java.io.FileOutputStream
import nativecontract.demo.coordinator.FailStop
import nativecontract.demo.coordinator.Json
import nativecontract.demo.coordinator.TerminalAuditRecorder

/**
 * Process-namespaced native JSONL. Each row is one complete UTF-8 line carrying
 * the frozen event base (processInstanceId, launchOrdinal, localSequence, kind);
 * `synchronize` syncs the file descriptor. After processEnd the stream is sealed.
 */
class JSONLAuditRecorder(
    file: File,
    private val processInstanceId: String,
    private val launchOrdinal: Long,
) : TerminalAuditRecorder {
    private val stream: FileOutputStream
    private var nextSequence = 1L
    private var sealed = false

    init {
        require(launchOrdinal > 0L) { "launchOrdinal must be positive" }
        val directory = file.parentFile ?: error("audit file has no directory")
        check(directory.isDirectory || directory.mkdirs()) { "cannot create native audit directory" }
        check(!file.exists()) { "native audit file already exists for this process namespace" }
        stream = FileOutputStream(file, false)
    }

    @Synchronized
    override fun append(kind: String, fields: Map<String, Any?>): Long {
        check(!sealed) { "native event stream is sealed by processEnd" }
        return appendUnlocked(kind, fields)
    }

    @Synchronized
    override fun appendProcessEndAndSeal(fields: Map<String, Any?>): Long {
        check(!sealed) { "native event stream is sealed by processEnd" }
        val sequence = appendUnlocked("processEnd", fields)
        // Forbid later rows even if the sync below fails; a retry cannot invent another end.
        sealed = true
        stream.fd.sync()
        return sequence
    }

    @Synchronized
    override fun synchronize() {
        stream.fd.sync()
    }

    private fun appendUnlocked(kind: String, fields: Map<String, Any?>): Long {
        if (nextSequence == Long.MAX_VALUE) FailStop.stop("CounterExhausted: native event sequence")
        val row = LinkedHashMap(fields)
        row["processInstanceId"] = processInstanceId
        row["launchOrdinal"] = launchOrdinal
        row["localSequence"] = nextSequence
        row["kind"] = kind
        stream.write((Json.encode(row) + "\n").toByteArray(Charsets.UTF_8))
        val assigned = nextSequence
        nextSequence += 1L
        return assigned
    }
}
