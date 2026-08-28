package fixture

import androidx.compose.runtime.Composable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.ui.unit.dp

private val ContentPadding = 16.dp

@Composable
fun HomeScreen() {
    Column(modifier = Modifier.fillMaxWidth().padding(16.dp)) {
        Text("Projects")
        Button(onClick = {}) {
            Text("Create project")
        }
    }
}
