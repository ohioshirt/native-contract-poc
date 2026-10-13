package nativecontract.demo.mutation

/** Contract implemented by the copied candidate coordinator only for N2. */
interface N2DuplicateClearMutationHost {
    fun n2PerformNormalVerifiedLogout(commandId: Long)
    fun n2ScheduleDetachedEffect(effectId: String, originCommandId: Long, action: () -> Unit)
    fun n2PauseBeforeDeferredControlClear(effectId: String, originCommandId: Long)
    fun n2PerformDuplicateClearAndRecord(effectId: String, originCommandId: Long)
}

fun N2DuplicateClearMutationHost.debugClearThenScheduleDuplicate(commandId: Long) {
    n2PerformNormalVerifiedLogout(commandId)
    val effectId = "duplicate-logout-$commandId"
    n2ScheduleDetachedEffect(effectId, commandId) {
        n2PauseBeforeDeferredControlClear(effectId, commandId)
        n2PerformDuplicateClearAndRecord(effectId, commandId)
    }
}
