package com.sintu.studio

import android.os.Bundle
import android.content.Intent
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.work.WorkInfo
import androidx.work.WorkManager
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

@OptIn(ExperimentalMaterial3Api::class)
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
    val context = LocalContext.current
    var formatId by remember { mutableStateOf("youtube-shorts") }
    var topic by remember { mutableStateOf("") }
    var resolution by remember { mutableStateOf("720x1280") }
    var runId by remember { mutableStateOf("") }
    var runStatus by remember { mutableStateOf("") }
    var notice by remember { mutableStateOf("Create a format-specific production run. Final MP4 is enabled only after all production/reviewer gates pass.") }
    var output by remember { mutableStateOf("") }
    var videoId by remember { mutableStateOf("") }
    var downloadedUri by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var mediaNotice by remember { mutableStateOf("Select files to queue uploads. WorkManager retries when connectivity returns.") }
    val mediaWork = remember(context) {
        WorkManager.getInstance(context).getWorkInfosByTagLiveData(OfflineMediaUploadWorker.TAG)
    }.collectAsState(initial = emptyList())
    val mediaPicker = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenMultipleDocuments()
    ) { uris ->
        if (uris.isNotEmpty()) {
            var queued = 0
            for (uri in uris) {
                try {
                    context.contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    var filename = uri.lastPathSegment?.substringAfterLast('/')?.take(180) ?: "offline-media"
                    context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
                        if (cursor.moveToFirst()) {
                            val index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                            if (index >= 0) filename = cursor.getString(index)?.take(180) ?: filename
                        }
                    }
                    val mime = context.contentResolver.getType(uri) ?: "application/octet-stream"
                    OfflineMediaUploadWorker.enqueue(context, uri, filename, mime)
                    queued += 1
                } catch (error: Exception) {
                    mediaNotice = error.message ?: "Could not queue selected media."
                }
            }
            if (queued > 0) mediaNotice = "$queued file(s) queued. Upload continues under Android WorkManager when network is available."
        }
    }

    Column(
        modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(top = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text("Topic-to-final-MP4 pipeline", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        OutlinedTextField(
            formatId, { formatId = it.trim().take(80) },
            Modifier.fillMaxWidth(), label = { Text("Video format ID (e.g. youtube-shorts)") },
            singleLine = true
        )
        OutlinedTextField(
            topic, { topic = it },
            Modifier.fillMaxWidth(), label = { Text("Topic / instructions") }, minLines = 4
        )
        OutlinedTextField(
            resolution, { resolution = it.trim().take(12) },
            Modifier.fillMaxWidth(), label = { Text("Low-memory output resolution (720x1280 / 1280x720)") },
            singleLine = true
        )
        Button(
            onClick = {
                if (topic.isBlank() || formatId.isBlank()) {
                    notice = "Format ID aur topic dono zaroori hain."
                    return@Button
                }
                scope.launch {
                    busy = true
                    try {
                        val providers = api.providerStatus()
                        val localModel = providers["local"] as? Map<*, *>
                        if (localModel?.get("model_available") != true) {
                            val modelName = localModel?.get("model")?.toString().orEmpty()
                            notice = "Free local text model ready nahi hai" +
                                (if (modelName.isNotBlank()) " ($modelName)" else "") +
                                ". Pehle phone/server par supported local model configure karein. Paid API automatically use nahi hogi."
                            return@launch
                        }
                        val started = api.startProductionRun(formatId, topic.trim())
                        runId = started.run_id
                        runStatus = started.status
                        output = ""
                        videoId = ""
                        downloadedUri = ""
                        notice = started.detail.ifBlank { "Production run queued. Refresh status after worker/checker steps." }
                    } catch (error: Exception) {
                        notice = error.message ?: "Production run could not start."
                    } finally { busy = false }
                }
            },
            enabled = !busy && topic.isNotBlank() && formatId.isNotBlank(),
            modifier = Modifier.fillMaxWidth()
        ) { Text(if (busy) "Starting…" else "Start production + reviewer gates") }

        if (runId.isNotBlank()) {
            Text("Run ID: " + runId, style = MaterialTheme.typography.bodySmall)
            Text("Status: " + runStatus, fontWeight = FontWeight.Bold)
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val status = api.productionRunStatus(runId)
                            runStatus = status["status"]?.toString() ?: "unknown"
                            val role = status["current_role"]?.toString().orEmpty()
                            val error = status["error"]?.toString().orEmpty()
                            val steps = status["steps"] as? List<*>
                            notice = buildString {
                                append("Run status refreshed.")
                                if (role.isNotBlank() && role != "null") append(" Current role: ").append(role)
                                if (!steps.isNullOrEmpty()) append(" · ").append(steps.size).append(" recorded steps.")
                                if (error.isNotBlank() && error != "null") append(" · ").append(error)
                            }
                        } catch (error: Exception) {
                            notice = error.message ?: "Could not refresh production status."
                        } finally { busy = false }
                    }
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (busy) "Checking…" else "Refresh production status") }

            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val result = api.produceApprovedMedia(runId, resolution)
                            runStatus = result["status"]?.toString() ?: runStatus
                            val render = result["render"] as? Map<*, *>
                            videoId = render?.get("video_id")?.toString().orEmpty()
                            val videoUrl = render?.get("url")?.toString().orEmpty()
                            downloadedUri = ""
                            output = if (videoUrl.isNotBlank()) api.normalizedBaseUrl + videoUrl.removePrefix("/")
                                else "MP4 generated; video ID: " + videoId
                            notice = "Final MP4 rendered and attached. Published: " +
                                result["published"]?.toString().orEmpty() +
                                ". YouTube publishing remains a separate manual approval."
                        } catch (error: Exception) {
                            notice = error.message ?: "Final media generation failed."
                        } finally { busy = false }
                    }
                },
                enabled = !busy && runStatus == "completed",
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (busy) "Rendering…" else "Generate final MP4 (offline engines)") }
        }

        Text(notice, style = MaterialTheme.typography.bodySmall)
        if (output.isNotBlank()) {
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text("Final MP4")
                    Text(output, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        if (videoId.isNotBlank()) {
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val uri = api.downloadVideoToGallery(context, videoId)
                            downloadedUri = uri.toString()
                            notice = "MP4 phone gallery mein Movies/SINTU folder mein save ho gaya."
                        } catch (error: Exception) {
                            notice = error.message ?: "MP4 download failed."
                        } finally { busy = false }
                    }
                },
                enabled = !busy,
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (busy) "Downloading…" else "Download MP4 to phone") }
            if (downloadedUri.isNotBlank()) {
                Text("Saved to Movies/SINTU · " + downloadedUri, style = MaterialTheme.typography.bodySmall)
            }
        }
        Divider()
        Text("Native offline media queue", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text("Files remain in Android document storage. WorkManager keeps upload jobs across app restarts and retries on network restoration. Each file is capped at 256 MiB; chunk-level resume is not supported yet.", style = MaterialTheme.typography.bodySmall)
        Button(
            onClick = { mediaPicker.launch(arrayOf("image/*", "audio/*", "video/*")) },
            enabled = !busy,
            modifier = Modifier.fillMaxWidth()
        ) { Text("Select media from phone and queue upload") }
        Text(mediaNotice, style = MaterialTheme.typography.bodySmall)
        if (mediaWork.value.isEmpty()) {
            Text("No native media upload jobs yet.", style = MaterialTheme.typography.bodySmall)
        } else {
            mediaWork.value.take(8).forEach { work ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                        Text(work.state.name, fontWeight = FontWeight.Bold)
                        Text(work.outputData.getString("filename") ?: "Queued media", style = MaterialTheme.typography.bodySmall)
                        work.outputData.getString("sha256")?.takeIf { it.isNotBlank() }?.let {
                            Text("SHA-256: $it", style = MaterialTheme.typography.labelSmall)
                        }
                        work.outputData.getString(OfflineMediaUploadWorker.KEY_ERROR)?.let {
                            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                        }
                    }
                }
            }
        }
        Text(
            "Phone-first media path: procedural scene illustrations (not generative AI), local Hindi TTS when installed, procedural music, FFmpeg MP4. ComfyUI/paid APIs are not required for this fallback.",
            style = MaterialTheme.typography.bodySmall
        )
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
