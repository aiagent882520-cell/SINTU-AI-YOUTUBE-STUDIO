package com.sintu.studio

import android.os.Bundle
import androidx.compose.ui.viewinterop.AndroidView
import android.widget.VideoView
import android.widget.MediaController
import android.net.Uri
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.content.Intent
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.livedata.observeAsState
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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
    var sessionInfo by remember { mutableStateOf<SessionResponse?>(null) }
    var busy by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf("Connect to your SINTU server.") }

    LaunchedEffect(Unit) {
        try {
            val client = SintuApi(context, baseUrl)
            api = client
            val session = client.session()
            sessionInfo = session
            loggedIn = session.authenticated
            username = session.username.orEmpty()
        } catch (_: Exception) {
            notice = "Please sign in. Default same-device Termux URL: http://127.0.0.1:8000/"
        }
    }

    if (loggedIn && api != null) {
        Column(Modifier.fillMaxSize().padding(12.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                    Image(
                        painter = painterResource(id = R.drawable.sintu_icon_foreground),
                        contentDescription = "SINTU AI Studio logo",
                        modifier = Modifier.size(42.dp)
                    )
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text("SINTU AI YOUTUBE STUDIO", fontWeight = FontWeight.Bold)
                        Text("Signed in as " + username, style = MaterialTheme.typography.bodySmall)
                    }
                }
                OutlinedButton(onClick = {
                    scope.launch {
                        try { api?.logout() } catch (_: Exception) {}
                        loggedIn = false
                        sessionInfo = null
                    }
                }) { Text("Logout") }
            }
            Spacer(Modifier.height(8.dp))
            StudioTabs(api!!, sessionInfo)
        }
    } else {
        var password by remember { mutableStateOf("") }
        var otpCode by remember { mutableStateOf("") }
        var user by remember { mutableStateOf(username) }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.Center) {
            Image(
                painter = painterResource(id = R.drawable.sintu_icon_foreground),
                contentDescription = "SINTU AI Studio logo",
                modifier = Modifier.size(84.dp)
            )
            Spacer(Modifier.height(12.dp))
            Text("SINTU AI STUDIO", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            Text("Native Android client · free-first local AI")
            Spacer(Modifier.height(24.dp))
            OutlinedTextField(baseUrl, { baseUrl = it }, Modifier.fillMaxWidth(), label = { Text("SINTU server URL") }, singleLine = true)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(user, { user = it }, Modifier.fillMaxWidth(), label = { Text("Username") }, singleLine = true)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth(), label = { Text("Password") }, singleLine = true, visualTransformation = PasswordVisualTransformation())
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                otpCode,
                { otpCode = it.filter(Char::isDigit).take(6) },
                Modifier.fillMaxWidth(),
                label = { Text("Owner mobile OTP (6 digits; team users leave blank)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number)
            )
            Spacer(Modifier.height(12.dp))
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val normalized = SintuApi.normalizeBaseUrl(baseUrl)
                            val client = SintuApi(context, normalized)
                            client.login(user.trim(), password, otpCode.takeIf { it.isNotBlank() })
                            val signedInSession = client.session()
                            prefs.edit().putString("api_base_url", normalized).apply()
                            baseUrl = normalized
                            api = client
                            sessionInfo = signedInSession
                            username = signedInSession.username.orEmpty()
                            loggedIn = signedInSession.authenticated
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
private fun StudioTabs(api: SintuApi, session: SessionResponse?) {
    var tab by remember { mutableIntStateOf(0) }
    val isOwner = session?.is_owner == true
    val features = session?.features?.toSet() ?: emptySet()
    val visibleTabs = buildList {
        if (isOwner || "ai_assistant" in features) add("Assistant")
        if (isOwner || "video_editor" in features) add("Images")
        if (isOwner || ("video_editor" in features && "production" in features)) add("Video")
        if (isOwner || "projects" in features) add("Projects")
    }
    LaunchedEffect(visibleTabs.size) {
        if (tab >= visibleTabs.size) tab = 0
    }
    if (visibleTabs.isEmpty()) {
        Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.Center) {
            if (isOwner || features.isNotEmpty()) {
                Text("Your granted features are not yet available in the Android client.", fontWeight = FontWeight.Bold)
                Text("Open the SINTU web dashboard to use the modules assigned to this account.")
            } else {
                Text("No studio features are assigned to this account.", fontWeight = FontWeight.Bold)
                Text("Ask the SINTU Owner to grant the modules you need.")
            }
        }
        return
    }
    TabRow(selectedTabIndex = tab) {
        visibleTabs.forEachIndexed { i, title ->
            Tab(selected = tab == i, onClick = { tab = i }, text = { Text(title) })
        }
    }
    when (visibleTabs.getOrNull(tab)) {
        "Assistant" -> AssistantScreen(api, Modifier.fillMaxSize())
        "Images" -> ImageStudioScreen(api, Modifier.fillMaxSize())
        "Video" -> VideoScreen(api, Modifier.fillMaxSize())
        "Projects" -> ProjectsScreen(api, Modifier.fillMaxSize())
    }
}

@Composable
private fun AssistantScreen(api: SintuApi, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var chats by remember { mutableStateOf(emptyList<ConversationDto>()) }
    var active by rememberSaveable { mutableStateOf<Int?>(null) }
    var messages by remember { mutableStateOf(emptyList<MessageDto>()) }
    var draft by rememberSaveable { mutableStateOf("") }
    var workflow by rememberSaveable { mutableStateOf("content") }
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
private fun ImageStudioScreen(api: SintuApi, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var prompt by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf("scene") }
    var aspect by rememberSaveable { mutableStateOf("portrait") }
    var imageId by rememberSaveable { mutableStateOf("") }
    var provider by rememberSaveable { mutableStateOf("") }
    var notice by rememberSaveable { mutableStateOf("Checking the configured local image engine…") }
    var canGenerate by remember { mutableStateOf(false) }
    var savedUri by rememberSaveable { mutableStateOf("") }
    var preview by remember { mutableStateOf<Bitmap?>(null) }
    var busy by remember { mutableStateOf(false) }

    LaunchedEffect(api) {
        try {
            val capabilities = api.imageCapabilities()
            val engine = capabilities["local_engine"]?.toString().orEmpty()
            val comfy = capabilities["comfyui_available"] == true
            canGenerate = capabilities["production_enabled"] == true
            notice = if (!canGenerate) {
                "Image generation is paused by the server production safety gate. Enable it only after all readiness checks pass."
            } else if (comfy) {
                "Local ComfyUI AI engine available: " + engine
            } else {
                "AI inference is not configured. Current free fallback: " + engine +
                    ". Procedural artwork is not generative AI."
            }
        } catch (error: Exception) {
            notice = error.message ?: "Image engine status unavailable."
        }
    }

    LaunchedEffect(api, imageId) {
        if (imageId.isBlank()) {
            preview = null
            return@LaunchedEffect
        }
        try {
            val bytes = api.downloadImageBytes(imageId)
            val bitmap = withContext(Dispatchers.IO) {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
                val width = bounds.outWidth
                val height = bounds.outHeight
                require(width in 1..8192 && height in 1..8192 &&
                    width.toLong() * height.toLong() <= 16_000_000L) {
                    "Image dimensions exceed the safe Android preview limit."
                }
                var sampleSize = 1
                while (width / sampleSize > 1600 || height / sampleSize > 1600) {
                    sampleSize *= 2
                }
                val options = BitmapFactory.Options().apply { inSampleSize = sampleSize }
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
            }
            preview = bitmap ?: throw IllegalStateException("Generated image could not be decoded on this device.")
        } catch (error: Exception) {
            preview = null
            notice = error.message ?: "Image preview could not be loaded."
        }
    }

    Column(
        modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(top = 12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text("Image Studio", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
        Text("Use the configured local ComfyUI AI engine when available. Otherwise the server uses clearly labelled procedural art.", style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(
            prompt,
            { prompt = it.take(3000) },
            Modifier.fillMaxWidth(),
            label = { Text("Image prompt") },
            minLines = 4,
            maxLines = 8
        )
        Text("Output type", fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { kind = "scene" }) { Text(if (kind == "scene") "✓ Scene" else "Scene") }
            OutlinedButton(onClick = {
                kind = "thumbnail"
                aspect = "landscape"
            }) { Text(if (kind == "thumbnail") "✓ Thumbnail" else "Thumbnail") }
        }
        Text("Aspect ratio", fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("portrait", "landscape", "square").filter { kind != "thumbnail" || it == "landscape" }.forEach { option ->
                OutlinedButton(onClick = { aspect = option }) {
                    Text((if (aspect == option) "✓ " else "") + when (option) {
                        "portrait" -> "9:16"
                        "landscape" -> "16:9"
                        else -> "1:1"
                    })
                }
            }
        }
        Button(
            onClick = {
                scope.launch {
                    busy = true
                    try {
                        val result = api.generateImage(prompt, kind, aspect)
                        imageId = result.image_id
                        provider = result.provider
                        savedUri = ""
                        notice = result.notice
                    } catch (error: Exception) {
                        notice = error.message ?: "Image generation failed."
                    } finally { busy = false }
                }
            },
            enabled = !busy && prompt.isNotBlank() && canGenerate,
            modifier = Modifier.fillMaxWidth()
        ) { Text(if (busy) "Generating…" else "Generate image") }

        Text(notice, style = MaterialTheme.typography.bodySmall)
        if (imageId.isNotBlank()) {
            Text("Provider: " + provider, fontWeight = FontWeight.Bold)
            if (provider.contains("Procedural", ignoreCase = true)) {
                Text("This output is procedural artwork, not AI-generated imagery.", color = MaterialTheme.colorScheme.tertiary, style = MaterialTheme.typography.bodySmall)
            } else if (provider.contains("ComfyUI", ignoreCase = true)) {
                Text("Generated by the configured local AI inference server.", style = MaterialTheme.typography.bodySmall)
            }
            preview?.let { bitmap ->
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = "Generated SINTU image",
                    modifier = Modifier.fillMaxWidth().heightIn(max = 440.dp),
                    contentScale = ContentScale.Fit
                )
            }
            Button(
                onClick = {
                    scope.launch {
                        busy = true
                        try {
                            val uri = api.saveImageToGallery(context, imageId)
                            savedUri = uri.toString()
                            notice = "Image saved to Pictures/SINTU on this phone."
                        } catch (error: Exception) {
                            notice = error.message ?: "Image could not be saved to the gallery."
                        } finally { busy = false }
                    }
                },
                enabled = !busy && preview != null,
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (busy) "Saving…" else "Save image to phone gallery") }
            if (savedUri.isNotBlank()) {
                Text("Saved · " + savedUri, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun VideoScreen(api: SintuApi, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var formatId by rememberSaveable { mutableStateOf("youtube-shorts") }
    var topic by rememberSaveable { mutableStateOf("") }
    var resolution by rememberSaveable { mutableStateOf("720x1280") }
    var runId by rememberSaveable { mutableStateOf("") }
    var runStatus by rememberSaveable { mutableStateOf("") }
    var notice by rememberSaveable { mutableStateOf("Create a format-specific production run. Final MP4 is enabled only after all production/reviewer gates pass.") }
    var output by rememberSaveable { mutableStateOf("") }
    var videoId by rememberSaveable { mutableStateOf("") }
    var downloadedUri by rememberSaveable { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var mediaNotice by remember { mutableStateOf("Select files to queue uploads. WorkManager retries when connectivity returns.") }
    val mediaWork = remember(context) {
        WorkManager.getInstance(context).getWorkInfosByTagLiveData(OfflineMediaUploadWorker.TAG)
    }.observeAsState(initial = emptyList())
    val videoDownloadWork = remember(context, videoId) {
        WorkManager.getInstance(context)
            .getWorkInfosForUniqueWorkLiveData("sintu-video-download-$videoId")
    }.observeAsState(initial = emptyList())
    val currentVideoDownload = videoDownloadWork.value.firstOrNull()
    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        try {
            VideoDownloadWorker.enqueue(context, videoId)
            notice = if (granted) {
                "MP4 background download queued. Android foreground notification active rahegi."
            } else {
                "Notification permission denied. Download phir bhi background mein chalega; active transfer Android task manager mein dikhega."
            }
        } catch (error: Exception) {
            notice = error.message ?: "MP4 download could not be queued."
        }
    }
    val videoDownloadActive = currentVideoDownload?.state?.let {
        it == WorkInfo.State.ENQUEUED || it == WorkInfo.State.BLOCKED || it == WorkInfo.State.RUNNING
    } == true
    LaunchedEffect(currentVideoDownload?.id, currentVideoDownload?.state) {
        when (currentVideoDownload?.state) {
            WorkInfo.State.SUCCEEDED -> {
                downloadedUri = currentVideoDownload?.outputData?.getString(VideoDownloadWorker.KEY_SAVED_URI).orEmpty()
                if (downloadedUri.isNotBlank()) notice = "MP4 Movies/SINTU mein save ho gaya. App band hone ke baad bhi download complete hua."
            }
            WorkInfo.State.FAILED -> {
                notice = currentVideoDownload?.outputData?.getString(VideoDownloadWorker.KEY_ERROR)
                    ?: "Background MP4 download failed."
            }
            WorkInfo.State.RUNNING -> notice = "MP4 background mein download ho raha hai…"
            WorkInfo.State.ENQUEUED, WorkInfo.State.BLOCKED -> notice = "MP4 download queued; network available hote hi start hoga."
            else -> Unit
        }
    }
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
            Modifier.fillMaxWidth(), label = { Text("Output resolution") },
            singleLine = true,
            isError = !OutputResolutionPolicy.isSupported(resolution)
        )
        Text(
            if (OutputResolutionPolicy.isSupported(resolution))
                "Supported profile: $resolution"
            else "Unsupported profile. Choose: " + OutputResolutionPolicy.supported.joinToString(", "),
            style = MaterialTheme.typography.bodySmall,
            color = if (OutputResolutionPolicy.isSupported(resolution)) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error
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
                            if (!OutputResolutionPolicy.isSupported(resolution)) {
                                notice = "Unsupported output resolution. Choose: " + OutputResolutionPolicy.supported.joinToString(", ")
                                return@launch
                            }
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
                enabled = !busy && runStatus == "completed" && OutputResolutionPolicy.isSupported(resolution),
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
                    val queueDownload = {
                        try {
                            VideoDownloadWorker.enqueue(context, videoId)
                            notice = "MP4 background download queue mein add ho gaya. Android foreground notification active rahegi."
                        } catch (error: Exception) {
                            notice = error.message ?: "MP4 download could not be queued."
                        }
                    }
                    if (android.os.Build.VERSION.SDK_INT >= 33 &&
                        context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED
                    ) {
                        notificationPermissionLauncher.launch(android.Manifest.permission.POST_NOTIFICATIONS)
                    } else {
                        queueDownload()
                    }
                },
                enabled = !busy && !videoDownloadActive && downloadedUri.isBlank(),
                modifier = Modifier.fillMaxWidth()
            ) { Text(if (videoDownloadActive) "MP4 download queued/running…" else "Download MP4 to phone (background)") }
            if (videoDownloadActive) {
                Text("Background download: " + currentVideoDownload?.state?.name, style = MaterialTheme.typography.bodySmall)
                OutlinedButton(onClick = {
                    currentVideoDownload?.let { WorkManager.getInstance(context).cancelWorkById(it.id) }
                    notice = "MP4 download cancelled."
                }) { Text("Cancel MP4 download") }
            }
            if (downloadedUri.isNotBlank()) {
                Text("Saved to Movies/SINTU · " + downloadedUri, style = MaterialTheme.typography.bodySmall)
                Text("In-app MP4 preview", style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                SintuInlineVideoPlayer(downloadedUri)
                OutlinedButton(
                    onClick = {
                        try {
                            val previewIntent = Intent(Intent.ACTION_VIEW).apply {
                                setDataAndType(android.net.Uri.parse(downloadedUri), "video/mp4")
                                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                            }
                            if (previewIntent.resolveActivity(context.packageManager) != null) {
                                context.startActivity(previewIntent)
                            } else {
                                notice = "No compatible video player is installed on this device."
                            }
                        } catch (error: Exception) {
                            notice = error.message ?: "Could not open the saved MP4."
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                ) { Text("Play saved MP4") }
            }
        }
        Divider()
        Text("Native offline media queue", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        Text("Files remain in Android document storage. WorkManager keeps upload jobs across app restarts and retries on network restoration. Each file is capped at 256 MiB. Uploads use SHA-256-verified resumable chunks; WorkManager retries and resumes from the server-confirmed offset.", style = MaterialTheme.typography.bodySmall)
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
                        if (work.state == WorkInfo.State.ENQUEUED ||
                            work.state == WorkInfo.State.BLOCKED ||
                            work.state == WorkInfo.State.RUNNING) {
                            OutlinedButton(onClick = {
                                WorkManager.getInstance(context).cancelWorkById(work.id)
                                mediaNotice = "Upload cancelled. Select the file again to queue a fresh transfer."
                            }) { Text("Cancel upload") }
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
private fun SintuInlineVideoPlayer(contentUri: String) {
    AndroidView(
        modifier = Modifier.fillMaxWidth().aspectRatio(9f / 16f),
        factory = { context ->
            VideoView(context).apply {
                val controls = MediaController(context)
                controls.setAnchorView(this)
                setMediaController(controls)
                tag = contentUri
                setVideoURI(Uri.parse(contentUri))
                setOnPreparedListener { player ->
                    player.isLooping = false
                    start()
                }
            }
        },
        update = { player ->
            if (player.tag != contentUri) {
                player.stopPlayback()
                player.tag = contentUri
                player.setVideoURI(Uri.parse(contentUri))
                player.setOnPreparedListener { prepared ->
                    prepared.isLooping = false
                    player.start()
                }
            }
        }
    )
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
