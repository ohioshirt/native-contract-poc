package nativecontract.demo.contract


/** Evaluator-owned hook inventory used by Debug controls and Release hooks. */
enum class HookPoint(val wireValue: String) {
    BEFORE_BOOTSTRAP_CLEAR("beforeBootstrapClear"),
    AFTER_MANAGED("afterManaged"),
    BEFORE_STORE("beforeStore"),
    BEFORE_PUBLISH("beforePublish"),
    AFTER_PUBLISH_ACK("afterPublishAck"),
    AFTER_LOGOUT_RECEIPT("afterLogoutReceipt"),
    INGRESS_HELD("ingressHeld"),
    BEFORE_DEFERRED_CONTROL_CLEAR("beforeDeferredControlClear"),
}

/** Frozen, redacted store projection. No credential bytes or token fields exist here. */
sealed interface StoreObservation {
    fun toRedactedFields(): Map<String, Any>

    data object Absent : StoreObservation {
        override fun toRedactedFields(): Map<String, Any> = mapOf("kind" to "Absent")
    }

    data class Present(val account: String, val version: Long) : StoreObservation {
        init {
            require(account in setOf("A", "B") && version >= 0L)
        }

        override fun toRedactedFields(): Map<String, Any> = mapOf(
            "kind" to "Present",
            "account" to account,
            "version" to version,
        )
    }

    data class Unknown(val errorCode: String) : StoreObservation {
        init {
            require(errorCode.isNotBlank())
        }

        override fun toRedactedFields(): Map<String, Any> = mapOf(
            "kind" to "Unknown",
            "errorCode" to errorCode,
        )
    }
}
