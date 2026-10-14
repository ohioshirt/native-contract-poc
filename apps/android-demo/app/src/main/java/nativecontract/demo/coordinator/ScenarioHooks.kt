package nativecontract.demo.coordinator

import nativecontract.demo.contract.HookPoint

/**
 * App-internal barrier points. `pauseIfArmed` blocks only the calling thread
 * (the coordinator worker); release always arrives through an independent
 * control channel, never through the auth mailbox.
 */
interface ScenarioHooks {
    val hasPausedHook: Boolean get() = false

    fun pauseIfArmed(point: HookPoint)
    fun releasedActionId(point: HookPoint): Long? = null
    fun commandEnqueued(reference: AppCommandReference, name: String) = Unit
    fun commandStarted(reference: AppCommandReference, name: String) = Unit
    fun commandProcessed(reference: AppCommandReference) = Unit
    fun storeIOChanged(active: Boolean) = Unit
    fun pauseDetachedEffect(effectId: String, originCommandId: Long): Long = 0L
}

object NoopScenarioHooks : ScenarioHooks {
    override fun pauseIfArmed(point: HookPoint) = Unit
}
