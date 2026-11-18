package com.sintu.studio

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { SintuRoot() } }
    }
}

@Composable
private fun SintuRoot() {
    val context = LocalContext.current
    val prefs = remember { context.getSharedPreferences("sintu_app", 0) }
    val scope = rememberCoroutineScope()
    var baseUrl by remember { mutableStateOf(prefs.getString("api_base_url", "http://127.0.0.1:8000/") ?: "http://127.0.0.1:8000/") }
    var api by remember { mutableStateOf<SintuApi?>(null) }
    var username by remember { mutableStateOf("") }
    var loggedIn by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf("Connect to your SINTU server.") }

    LaunchedEffect(Unit) {
        try {
            val client = SintuApi(context, baseUrl)
            api = client
            val session = client.session()
            loggedIn = session.authenticated
            username = session.username.orEmpty()
        } catch (_: Exception) {
            notice = "Please sign in. Default same-device Termux URL: http://127.0.0.1:8000/"
        }
    }

    if (loggedIn && api != null) {
        Column(Modifier.fillMaxSize().padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text("SINTU AI YOUTUBE STUDIO", fontWeight = FontWeight.Bold)
                    Text("Signed in as " + username, style = MaterialTheme.typography.bodySmall)
                }
                OutlinedButton(onClick = {
                    scope.launch {
                        try { api?.logout() } catch (_: Exception) {}
                        loggedIn = false
                    }
                }) { Text("Logout") }
            }
            Spacer(Modifier.height(8.dp))
            StudioTabs(api!!)
        }
    } else {
        var password by remember { mutableStateOf("") }
        var user by remember { mutableStateOf(username) }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.Center) {
            Text("SINTU AI STUDIO", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("Native Android client · free-first local AI")
            Spacer(Modifier.height(24.dp))
            OutlinedTextField(baseUrl, { baseUrl = it }, Modifier.fillMaxWidth(), label = { Text("SINTU server URL") }, singleLine = true)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(user, { user = it }, Modifier.fillMaxWidth(), label = { Text("Username") }, singleLine = true)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Password") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val normalized = SintuApi.normalizeBaseUrl(baseUrl)
                            val client = SintuApi(context, normalized)
                            val result = client.login(user.trim(), password)
                            prefs.edit().putString("api_base_url", normalized).apply()
                            baseUrl = normalized
                            api = client
                            username = result.username
                            loggedIn = result.authenticated
                            notice = if (loggedIn) "Connected." else "Login rejected."
                        } catch (error: Exception) {
                            notice = error.message ?: "Connection failed."
                        } finally { busy = false }
                    }
                },
                enabled = !busy && user.isNotBlank() && password.isNotBlank(),
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (busy) "Connecting…" else "Secure login") }
            Spacer(Modifier.height(12.dp))
            Text(notice, style = MaterialTheme.typography.bodySmall)
            Text("Remote servers require HTTPS. HTTP is allowed only for localhost/127.0.0.1 (same-device Termux).", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun StudioTabs(api: SintuApi) {
    var tab by remember { mutableIntStateOf(0) }
    TabRow(selectedTabIndex = tab) {
        listOf("Assistant", "Video", "Projects").forEachIndexed { i, title ->
            Tab(selected = tab == i, onClick = { tab = i }, text = { Text(title) })
        }
    }
    when (tab) {
        0 -> AssistantScreen(api, Modifier.fillMaxSize())
        1 -> VideoScreen(api, Modifier.fillMaxSize())
        else -> ProjectsScreen(api, Modifier.fillMaxSize())
    }
}

@Composable
private fun AssistantScreen(api: SintuApi, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var chats by remember { mutableStateOf(emptyList<ConversationDto>()) }
    var active by remember { mutableStateOf<Int?>(null) }
    var messages by remember { mutableStateOf(emptyList<MessageDto>()) }
    var draft by remember { mutableStateOf("") }
    var workflow by remember { mutableStateOf("content") }
    var busy by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf("Conversation history is private to your signed-in account.") }

    suspend fun refresh(preferred: Int? = active) {
        chats = api.conversations().conversations
        active = preferred?.takeIf { id -> chats.any { it.id == id } }
        messages = active?.let { api.conversation(it).messages } ?: emptyList()
    }
    LaunchedEffect(api) {
        try { refresh(null) } catch (e: Exception) { notice = e.message ?: "Chat unavailable." }
    }

    Column(modifier.fillMaxWidth().padding(top = 8.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                scope.launch {
                    try {
                        val c = api.createConversation(workflow)
                        refresh(c.id)
                        notice = "New chat ready."
                    } catch (e: Exception) { notice = e.message ?: "Create failed." }
                }
            }) { Text("New chat") }
            OutlinedButton(onClick = {
                scope.launch {
                    try {
                        val id = active ?: return@launch
                        api.deleteConversation(id)
                        refresh(null)
                        notice = "Deleted."
                    } catch (e: Exception) { notice = e.message ?: "Delete failed." }
                }
            }) { Text("Delete") }
        }
        LazyRow(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(vertical = 6.dp)) {
            items(chats) { c ->
                OutlinedButton(onClick = {
                    scope.launch {
                        try { workflow = c.workflow; refresh(c.id) }
                        catch (e: Exception) { notice = e.message ?: "Load failed." }
                    }
                }) { Text(c.title.take(20)) }
            }
        }
        OutlinedTextField(workflow, { workflow = it.take(80) }, Modifier.fillMaxWidth(), label = { Text("Workflow ID: content / research / script / shorts") }, singleLine = true)
        LazyColumn(Modifier.weight(1f).fillMaxWidth().padding(vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(messages) { item ->
                Card(
                    Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = if (item.role == "user") MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant)
                ) {
                    Column(Modifier.padding(12.dp)) {
                        Text(if (item.role == "user") "You" else "SINTU · " + item.status, fontWeight = FontWeight.Bold)
                        Text(item.content)
                        if (item.provider.isNotBlank()) Text(item.provider + " · " + item.model, style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
        OutlinedTextField(draft, { draft = it }, Modifier.fillMaxWidth(), label = { Text("Message SINTU") }, minLines = 2, maxLines = 4)
        Button(
            onClick = {
                scope.launch {
                    val text = draft.trim()
                    if (text.isBlank()) return@launch
                    busy = true
                    try {
                        var id = active
                        if (id == null) id = api.createConversation(workflow).id
                        api.sendMessage(id, text)
                        draft = ""
                        refresh(id)
                        notice = "Reply received."
                    } catch (e: Exception) {
                        try { active?.let { messages = api.conversation(it).messages } } catch (_: Exception) {}
                        notice = e.message ?: "Assistant failed."
                    } finally { busy = false }
                }
            },
            enabled = !busy && draft.isNotBlank(),
            modifier = Modifier.fillMaxWidth()
        ) { Text(if (busy) "Thinking…" else "Send") }
        Text(notice, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun VideoScreen(api: SintuApi, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var title by remember { mutableStateOf("") }
    var topic by remember { mutableStateOf("") }
    var duration by remember { mutableStateOf("60") }
    var output by remember { mutableStateOf("") }
    var notice by remember { mutableStateOf("Generates a script/scene production package, not a final MP4.") }
    var busy by remember { mutableStateOf(false) }
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(top = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Topic-to-production package", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        OutlinedTextField(title, { title = it }, Modifier.fillMaxWidth(), label = { Text("Video title") })
        OutlinedTextField(topic, { topic = it }, Modifier.fillMaxWidth(), label = { Text("Topic / instructions") }, minLines = 4)
        OutlinedTextField(duration, { duration = it.filter(Char::isDigit).take(4) }, label = { Text("Duration (seconds)") })
        Button(
            onClick = {
                if (topic.isBlank()) { notice = "Enter a topic."; return@Button }
                scope.launch {
                    busy = true
                    try {
                        val seconds = duration.toIntOrNull()?.coerceIn(5, 7200) ?: 60
                        val project = api.createProject(
                            ProjectCreateRequest(title.trim().ifBlank { topic.trim().take(100) }, topic.trim(), duration_seconds = seconds)
                        ).project
                        val result = api.generateProject(project.id)
                        output = result.task.output.orEmpty()
                        notice = "Project saved · task #" + result.task.id + " · " + result.task.status + ". Final MP4 needs configured media engines and a separate render."
                    } catch (e: Exception) { notice = e.message ?: "Generation failed." }
                    finally { busy = false }
                }
            },
            enabled = !busy && topic.isNotBlank(),
            modifier = Modifier.fillMaxWidth()
        ) { Text(if (busy) "Generating…" else "Generate script & scene plan") }
        Text(notice, style = MaterialTheme.typography.bodySmall)
        if (output.isNotBlank()) Card(Modifier.fillMaxWidth()) { Text(output, Modifier.padding(12.dp)) }
    }
}

@Composable
private fun ProjectsScreen(api: SintuApi, modifier: Modifier = Modifier) {
    var projects by remember { mutableStateOf(emptyList<ProjectDto>()) }
    var notice by remember { mutableStateOf("Loading projects…") }
    LaunchedEffect(api) {
        try { projects = api.projects().projects; notice = projects.size.toString() + " project(s)" }
        catch (e: Exception) { notice = e.message ?: "Projects unavailable." }
    }
    Column(modifier.fillMaxWidth().padding(top = 12.dp)) {
        Text("Projects", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text(notice, style = MaterialTheme.typography.bodySmall)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(projects) { p ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text(p.name, fontWeight = FontWeight.Bold)
                        Text(p.format_id + " · " + p.status)
                        Text(p.updated_at.orEmpty(), style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}
