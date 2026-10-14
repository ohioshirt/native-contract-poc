package nativecontract.demo.mutation

/** Contract implemented by the copied candidate coordinator only for N4. */
interface N4FalseLogoutMutationHost<out Receipt> {
    fun n4PublishSignedOutWithoutStoreClear(commandId: Long)
    fun n4MakeCompletedLogoutReceipt(commandId: Long): @UnsafeVariance Receipt
}

fun <Receipt> N4FalseLogoutMutationHost<Receipt>.debugFalseLogoutReceipt(commandId: Long): Receipt {
    n4PublishSignedOutWithoutStoreClear(commandId)
    return n4MakeCompletedLogoutReceipt(commandId)
}
