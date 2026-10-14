package nativecontract.demo

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import nativecontract.demo.ui.DemoScreen

/** Only re-attaches to the Application-owned view model; recreation never rebuilds the coordinator. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val model = (application as DemoApplication).viewModel
        setContent {
            MaterialTheme {
                Surface {
                    DemoScreen(model)
                }
            }
        }
    }
}
