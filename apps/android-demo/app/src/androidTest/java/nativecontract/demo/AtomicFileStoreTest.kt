package nativecontract.demo

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import nativecontract.demo.contract.StoreObservation
import nativecontract.demo.coordinator.Credential
import nativecontract.demo.coordinator.CredentialAccount
import nativecontract.demo.debug.StorageProbe
import nativecontract.demo.storage.AtomicFileCredentialStore
import nativecontract.demo.storage.CredentialStoreException
import nativecontract.demo.storage.CredentialStoreFailure

/**
 * Real AtomicFile storage in an owned no-backup test namespace, observed through
 * the frozen evaluator StorageProbe. Each test cleans only its own suffix.
 */
@RunWith(AndroidJUnit4::class)
class AtomicFileStoreTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val attemptId = "t5-${UUID.randomUUID().toString().take(8)}"
    private val scenarioId = "AtomicFileStoreTest"
    private val directory = File(context.noBackupFilesDir, StorageProbe.testNamespaceRelativePath(attemptId, scenarioId)!!)

    @After
    fun removeOwnedNamespace() {
        directory.listFiles()?.forEach { it.delete() }
        directory.delete()
        directory.parentFile?.delete()
    }

    private fun probe(): StoreObservation = StorageProbe.read(context, attemptId, scenarioId, "probe", "p").observation

    @Test
    fun replaceReadbackAndIdempotentClearAreVisibleToTheFrozenProbe() {
        val store = AtomicFileCredentialStore(directory)
        assertTrue(directory.isDirectory)
        assertEquals(StoreObservation.Absent, probe())

        store.replaceVerified(Credential.demo(CredentialAccount.A, 0L))
        assertEquals(StoreObservation.Present("A", 0L), probe())
        store.replaceVerified(Credential.demo(CredentialAccount.A, 1L))
        assertEquals(Credential.demo(CredentialAccount.A, 1L), store.readVerified())
        assertEquals(StoreObservation.Present("A", 1L), probe())

        store.clearVerified()
        store.clearVerified()
        assertNull(store.readVerified())
        assertEquals(StoreObservation.Absent, probe())
        assertTrue("clear keeps the owned namespace directory", directory.isDirectory)
        assertEquals(emptyList<String>(), directory.list()!!.toList())
    }

    @Test
    fun injectedFaultsMatchTheirRecordedPhysicalEffect() {
        val store = AtomicFileCredentialStore(directory)
        store.replaceVerified(Credential.demo(CredentialAccount.A, 0L))

        store.setStoreFault("replaceBefore")
        val before = expectFailure { store.replaceVerified(Credential.demo(CredentialAccount.A, 1L)) }
        assertFalse(before.mutationApplied)
        assertEquals(StoreObservation.Present("A", 0L), probe())

        store.setStoreFault("replaceAfterBeforeVerify")
        val after = expectFailure { store.replaceVerified(Credential.demo(CredentialAccount.A, 1L)) }
        assertTrue(after.mutationApplied)
        assertEquals(StoreObservation.Unknown("readFailed"), after.observation)
        assertEquals(StoreObservation.Present("A", 1L), probe())

        store.setStoreFault("clearBefore")
        expectFailure { store.clearVerified() }
        assertEquals(StoreObservation.Present("A", 1L), probe())

        store.setStoreFault("clearAfterBeforeVerify")
        val cleared = expectFailure { store.clearVerified() }
        assertEquals(StoreObservation.Unknown("readFailed"), cleared.observation)
        assertEquals(StoreObservation.Absent, probe())
        store.setStoreFault(null)
    }

    @Test
    fun leftoverSidecarIsUnknownNotAbsentAndClearRemovesIt() {
        val store = AtomicFileCredentialStore(directory)
        File(directory, "credential.json.new").writeText("partial")

        try {
            store.readVerified()
            fail("a read must not repair or ignore an AtomicFile sidecar")
        } catch (_: CredentialStoreException) {
        }
        assertEquals(StoreObservation.Unknown("atomicSidecarPresent"), probe())

        store.clearVerified()
        assertEquals(StoreObservation.Absent, probe())
    }

    @Test
    fun malformedOwnedBlobIsRejectedThenDeletable() {
        val store = AtomicFileCredentialStore(directory)
        File(directory, "credential.json").writeText("""{"account":"A","version":0,"accessToken":"x","refreshToken":"x"}""")

        try {
            store.readVerified()
            fail("token mismatch must not decode")
        } catch (_: CredentialStoreException) {
        }
        store.clearVerified()
        assertEquals(StoreObservation.Absent, probe())
    }

    private fun expectFailure(block: () -> Unit): CredentialStoreFailure {
        try {
            block()
        } catch (failure: CredentialStoreFailure) {
            return failure
        }
        fail("expected an injected CredentialStoreFailure")
        error("unreachable")
    }
}
