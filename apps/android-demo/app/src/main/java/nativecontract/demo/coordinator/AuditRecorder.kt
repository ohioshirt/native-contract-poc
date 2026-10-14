package nativecontract.demo.coordinator

/** App-internal append/sync boundary for redacted native history rows. */
interface AuditRecorder {
    /** Appends one row and returns its positive process-local sequence. */
    fun append(kind: String, fields: Map<String, Any?>): Long
    fun synchronize()
}

/** A recorder that appends, synchronizes and seals the terminal processEnd row. */
interface TerminalAuditRecorder : AuditRecorder {
    fun appendProcessEndAndSeal(fields: Map<String, Any?>): Long
}

class NoopAuditRecorder : AuditRecorder {
    private var sequence = 0L

    @Synchronized
    override fun append(kind: String, fields: Map<String, Any?>): Long {
        if (sequence == Long.MAX_VALUE) FailStop.stop("CounterExhausted: native event sequence")
        sequence += 1
        return sequence
    }

    override fun synchronize() = Unit
}
