package nativecontract.demo.mutation

private class N2CompileFixture : N2DuplicateClearMutationHost {
    override fun n2PerformNormalVerifiedLogout(commandId: Long) = Unit
    override fun n2ScheduleDetachedEffect(effectId: String, originCommandId: Long, action: () -> Unit) = action()
    override fun n2PauseBeforeDeferredControlClear(effectId: String, originCommandId: Long) = Unit
    override fun n2PerformDuplicateClearAndRecord(effectId: String, originCommandId: Long) = Unit
}

private class N4CompileFixture : N4FalseLogoutMutationHost<String> {
    override fun n4PublishSignedOutWithoutStoreClear(commandId: Long) = Unit
    override fun n4MakeCompletedLogoutReceipt(commandId: Long) = "Completed:$commandId"
}

fun compileMutationHelpers() {
    N2CompileFixture().debugClearThenScheduleDuplicate(7)
    N4CompileFixture().debugFalseLogoutReceipt(8)
}
