package nativecontract.demo.coordinator

import java.util.UUID
import nativecontract.async.RefreshRequest

/** Reference identity replaced whenever the logical managed owner changes. */
class SessionEpoch(val id: String = "epoch-${UUID.randomUUID()}")

/**
 * An opaque request capability retained from the managed effect through delivery.
 * Deliberately not a data class: eligibility compares slots and epochs with `===`.
 */
class RefreshSlot(
    val slotId: String,
    val request: RefreshRequest,
    val epoch: SessionEpoch,
    val issuanceCommandId: Long,
    val wireTag: String,
    val account: CredentialAccount,
    val seedVersion: Long,
    val ownerId: String,
)
