package nativecontract.demo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import nativecontract.demo.coordinator.AppCommand
import nativecontract.demo.coordinator.CredentialAccount
import nativecontract.demo.coordinator.SessionPhase

/** Auth labels and controls use the same identifiers as the iOS accessibility IDs. */
@Composable
fun DemoScreen(model: DemoViewModel) {
    val view = model.current
    Column(
        modifier = Modifier.fillMaxWidth().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(model.sessionLabel, style = MaterialTheme.typography.titleLarge, modifier = Modifier.testTag("session-state"))
        Text(model.credentialStatusLabel, modifier = Modifier.testTag("credential-status"))
        Text(model.accountLabel, modifier = Modifier.testTag("account-label"))
        Text(view.processInstanceId, modifier = Modifier.testTag("view-process-id"))
        Text(view.revision.toString(), modifier = Modifier.testTag("view-revision"))
        Text(view.lastCompletedCommandId?.toString() ?: "", modifier = Modifier.testTag("last-command-id"))
        Text(view.lastCommandStatus?.wire ?: "", modifier = Modifier.testTag("last-command-status"))
        if (view.phase == SessionPhase.FAULT_LOCKED) {
            Text("Cleanup failed", modifier = Modifier.testTag("cleanup-error"))
        }
        model.startupError?.let { Text(it, color = Color.Red, modifier = Modifier.testTag("startup-error")) }

        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CommandButton("Login A", "login-A") { model.submit(AppCommand.Login(CredentialAccount.A)) }
            CommandButton("Login B", "login-B") { model.submit(AppCommand.Login(CredentialAccount.B)) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CommandButton("Expire token", "expire") { model.submit(AppCommand.Expire) }
            CommandButton("Logout", "logout") { model.submit(AppCommand.Logout) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            CommandButton("Cancel refresh", "cancel-refresh") { model.submit(AppCommand.CancelRefresh) }
            CommandButton("Retry cleanup", "retry-cleanup") { model.submit(AppCommand.RetryCleanup) }
            CommandButton("Observe", "observe") { model.submit(AppCommand.Observe) }
        }
    }
}

@Composable
private fun CommandButton(label: String, tag: String, onClick: () -> Unit) {
    Button(onClick = onClick, modifier = Modifier.testTag(tag)) { Text(label) }
}
