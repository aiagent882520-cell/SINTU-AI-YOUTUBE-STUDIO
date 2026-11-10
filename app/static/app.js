const $ = (id) => document.getElementById(id);
let latestTaskId = null;

function parseTimelineEntry(entry) {
  const p=entry.trim().split(":");
  if(p[0]==="image"&&p.length===4&&/^[a-f0-9]{32}$/i.test(p[1]))return {kind:"image",id:p[1].toLowerCase(),duration:Number(p[2]),transition:p[3]};
  if(p[0]==="video"&&p.length===5&&/^[a-f0-9]{32}$/i.test(p[1]))return {kind:"video",id:p[1].toLowerCase(),trimStart:Number(p[2]),trimEnd:p[3]===""?null:Number(p[3]),transition:p[4]};
  const legacy=/^(image|video):([a-f0-9]{32}):(\d{1,2}):(cut|fade)$/i.exec(entry.trim());if(!legacy)return null;
  return {kind:legacy[1].toLowerCase(),id:legacy[2].toLowerCase(),duration:legacy[1].toLowerCase()==="image"?Number(legacy[3]):0,trimStart:0,trimEnd:null,transition:legacy[4]};
}
function timelineRows(){const entries=$("renderTimeline").value.split("\n").map(parseTimelineEntry).filter(Boolean),scenes=$("renderScenes").value.split("\n"),subs=$("renderSubtitles").value.split("\n");return entries.map((x,i)=>({...x,scene:scenes[i]||"",subtitle:subs[i]||""}));}
function syncTimelineFields(rows){
  $("renderTimeline").value=rows.map(x=>x.kind==="image"?"image:"+x.id+":"+x.duration+":"+x.transition:"video:"+x.id+":"+(x.trimStart||0)+":"+(x.trimEnd??"")+":"+x.transition).join("\n");
  $("renderScenes").value=rows.map(x=>x.scene||"").join("\n");$("renderSubtitles").value=rows.map(x=>x.subtitle||"").join("\n");
  $("renderImageIds").value=rows.filter(x=>x.kind==="image").map(x=>x.id).join(", ");$("renderVideoIds").value=rows.filter(x=>x.kind==="video").map(x=>x.id).join(", ");renderTimelineEditor(rows);
}
function renderTimelineEditor(rows=timelineRows()){
 const e=$("timelineEditor");if(!rows.length){e.innerHTML='<p class="muted">Abhi timeline khaali hai. AI image ya AI video generate karein.</p>';return;}
 e.innerHTML=rows.map((x,i)=>{
  const preview=x.kind==="image"?'<img src="/api/images/'+x.id+'" alt="Scene '+(i+1)+' preview" loading="lazy" style="width:100%;max-height:170px;object-fit:contain;background:#111;border-radius:8px">':'<video src="/api/ai-videos/'+x.id+'" controls playsinline preload="metadata" style="width:100%;max-height:170px;background:#111"></video>';
  const edit=x.kind==="image"?'<label>Duration (seconds, 2–12)</label><input type="number" min="2" max="12" data-field="duration" data-index="'+i+'" value="'+x.duration+'">':'<div class="actions"><label>Start (sec)<input type="number" min="0" step="0.1" data-field="trimStart" data-index="'+i+'" value="'+(x.trimStart||0)+'"></label><label>End (sec; blank = full end)<input type="number" min="0.1" step="0.1" data-field="trimEnd" data-index="'+i+'" value="'+(x.trimEnd??"")+'"></label></div><p class="muted">Original clip safe rahegi; sirf selected segment render hoga.</p>';
  return '<article class="panel timeline-row" style="margin:10px 0;padding:12px"><div class="actions"><strong>Scene '+(i+1)+' · '+x.kind.toUpperCase()+'</strong><button type="button" data-action="up" data-index="'+i+'" '+(i===0?'disabled':'')+'>↑</button><button type="button" data-action="down" data-index="'+i+'" '+(i===rows.length-1?'disabled':'')+'>↓</button><button type="button" data-action="remove" data-index="'+i+'">Remove</button></div>'+preview+'<label>Scene description</label><input data-field="scene" data-index="'+i+'" maxlength="1000" value="'+escapeHtml(x.scene||"")+'"><label>Subtitle (optional)</label><input data-field="subtitle" data-index="'+i+'" maxlength="1000" value="'+escapeHtml(x.subtitle||"")+'">'+edit+'<label>Transition after this scene</label><select data-field="transition" data-index="'+i+'"><option value="cut" '+(x.transition==="cut"?"selected":"")+'>Cut</option><option value="fade" '+(x.transition==="fade"?"selected":"")+'>Fade to/from black</option></select></article>';
 }).join("");
}
function queueTimelineAsset(kind,id,sceneText){const rows=timelineRows();if(rows.some(x=>x.kind===kind&&x.id===id))return;rows.push({kind,id,duration:kind==="image"?Number($("sceneSeconds").value||4):0,trimStart:0,trimEnd:null,transition:$("renderTransition").value||"fade",scene:sceneText||"Generated "+kind+" scene",subtitle:""});syncTimelineFields(rows);}
$("timelineEditor").addEventListener("click",event=>{const b=event.target.closest("button[data-action]");if(!b)return;const rows=timelineRows(),i=Number(b.dataset.index);if(b.dataset.action==="remove")rows.splice(i,1);if(b.dataset.action==="up"&&i>0)[rows[i-1],rows[i]]=[rows[i],rows[i-1]];if(b.dataset.action==="down"&&i<rows.length-1)[rows[i+1],rows[i]]=[rows[i],rows[i+1]];syncTimelineFields(rows);});
$("timelineEditor").addEventListener("change",event=>{
 const field=event.target.dataset.field;if(!field)return;const rows=timelineRows(),x=rows[Number(event.target.dataset.index)];if(!x)return;
 if(field==="duration"){const n=Number(event.target.value);if(!Number.isInteger(n)||n<2||n>12){event.target.value=x.duration;return;}x.duration=n;}
 else if(field==="trimStart"||field==="trimEnd"){const n=event.target.value===""&&field==="trimEnd"?null:Number(event.target.value);if(n!==null&&(!Number.isFinite(n)||n<0)){event.target.value=x[field]??"";return;}if(field==="trimStart")x.trimStart=n;else x.trimEnd=n;if(x.trimEnd!==null&&x.trimEnd<=x.trimStart){event.target.value=x[field]??"";return;}}
 else x[field]=event.target.value;syncTimelineFields(rows);
});
function playTimelinePreview(){
 const rows=timelineRows(),stage=$("timelinePreviewStage"),notice=$("timelinePreviewNotice");if(!rows.length){notice.textContent="Preview ke liye scenes add karein.";return;}let i=0,timer=null;
 const stop=()=>{if(timer)clearTimeout(timer);const v=stage.querySelector("video");if(v)v.pause();};
 $("timelinePreviewStop").onclick=()=>{stop();notice.textContent="Preview stopped.";};
 const next=()=>{stop();if(i>=rows.length){notice.textContent="Sequence preview complete.";return;}const x=rows[i];notice.textContent="Preview scene "+(i+1)+" / "+rows.length;
  if(x.kind==="image"){stage.innerHTML='<img alt="Timeline scene" style="width:100%;max-height:420px;object-fit:contain" src="/api/images/'+x.id+'">';timer=setTimeout(()=>{i++;next();},x.duration*1000);}
  else{stage.innerHTML='<video controls autoplay playsinline style="width:100%;max-height:420px" src="/api/ai-videos/'+x.id+'"></video>';const v=stage.querySelector("video");v.addEventListener("loadedmetadata",()=>{v.currentTime=x.trimStart||0;});v.addEventListener("timeupdate",()=>{if(x.trimEnd!==null&&v.currentTime>=x.trimEnd){v.pause();i++;next();}});v.addEventListener("ended",()=>{i++;next();});}
 };next();
}
$("timelinePreviewPlay").addEventListener("click",playTimelinePreview);

async function request(path, options={}) {
  const response = await fetch(path, {...options, headers:{"Content-Type":"application/json", ...(options.headers || {})}});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
async function refresh() {
  try {
    const [status,agents,tasks,providers,workflows] = await Promise.all([
      request("/api/status"), request("/api/agents"), request("/api/tasks"),
      request("/api/providers"), request("/api/workflows")
    ]);
    $("health").textContent = "API online";
    $("agentCount").textContent = agents.total;
    $("workflowCount").textContent = workflows.total;
    $("taskCount").textContent = status.tasks_saved;
    $("doneCount").textContent = status.tasks_completed;
    const available = [];
    if (providers.openai.configured) available.push("OpenAI");
    if (providers.gemini.configured) available.push("Gemini");
    $("providerStatus").textContent = available.length
      ? "Configured: " + available.join(" + ") + " · selected: " + providers.selected
      : "AI key configured nahi hai — server admin ko OpenAI/Gemini key secure environment mein add karni hogi.";
    $("agents").innerHTML = agents.agents.map(a =>
      '<div class="agent"><span>'+a.id+'. '+escapeHtml(a.name)+'</span><small>'+escapeHtml(a.status)+'</small></div>'
    ).join("");
    $("tasks").innerHTML = tasks.tasks.length ? tasks.tasks.map(t =>
      '<div class="task"><div><b>#'+t.id+' · '+escapeHtml(t.workflow)+'</b><span class="task-status">'+escapeHtml(t.status)+'</span></div>'+
      '<small>'+escapeHtml(t.prompt)+'</small>'+(t.output ? '<button class="task-open secondary" data-id="'+t.id+'">View / Download output</button>' : '')+'</div>'
    ).join("") : "No tasks yet.";
  } catch (error) { $("health").textContent = "API unavailable"; }
}
async function loadTeam() {
  try {
    const workflow = $("workflow").value;
    const data = await request("/api/workflows/" + encodeURIComponent(workflow) + "/team");
    const names = data.team.map(role => role.name).join(" · ");
    $("teamStatus").textContent = "Assigned role team (" + data.team.length + "): " + names +
      " — one configured AI model coordinates these role prompts; these are not 61 independent agents.";
  } catch (error) {
    $("teamStatus").textContent = "Workflow team details unavailable.";
  }
}
$("workflow").addEventListener("change", loadTeam);

async function generate() {
  const prompt = $("prompt").value.trim();
  if (!prompt) { $("notice").textContent = "Pehle apna topic ya prompt likhein."; $("prompt").focus(); return; }
  $("submit").disabled = true;
  $("resultWrap").hidden = true;
  $("notice").textContent = "AI production package generate kar raha hai…";
  try {
    const result = await request("/api/generate", {
      method:"POST",
      body:JSON.stringify({prompt,workflow:$("workflow").value})
    });
    latestTaskId = result.id;
    $("notice").textContent = "Task #"+result.id+" · "+result.provider+" · "+result.model+" · Completed";
    $("result").textContent = result.output;
    $("resultWrap").hidden = false;
    await refresh();
loadTeam();
  } catch (error) {
    $("notice").textContent = error.message;
    await refresh();
  } finally { $("submit").disabled = false; }
}
$("submit").addEventListener("click", generate);
$("clear").addEventListener("click", () => {
  $("prompt").value = "";
  $("notice").textContent = "";
  $("prompt").focus();
});
$("refresh").addEventListener("click", refresh);
function downloadPackage(format) {
  if (!latestTaskId) return;
  window.location.href = "/api/export/" + latestTaskId + "?format=" + format;
}
$("download").addEventListener("click", () => downloadPackage("txt"));
$("downloadMd").addEventListener("click", () => downloadPackage("md"));
$("downloadJson").addEventListener("click", () => downloadPackage("json"));
$("prompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) generate();
});
document.querySelectorAll("[data-workflow]").forEach(button => button.addEventListener("click", () => {
  $("workflow").value = button.dataset.workflow;
  loadTeam();
  $("prompt").focus();
  document.querySelector("#create").scrollIntoView({behavior:"smooth"});
}));
$("tasks").addEventListener("click", async event => {
  const button = event.target.closest("[data-id]");
  if (!button) return;
  latestTaskId = Number(button.dataset.id);
  try {
    const task = await request("/api/tasks/" + latestTaskId);
    $("workflow").value = task.workflow in Object.fromEntries([...$("workflow").options].map(o=>[o.value,true])) ? task.workflow : "content";
    $("prompt").value = task.prompt;
    $("result").textContent = task.output || "";
    $("resultWrap").hidden = !task.output;
    $("notice").textContent = "Task #" + task.id + " loaded.";
    $("create").scrollIntoView({behavior:"smooth"});
  } catch (error) { $("notice").textContent = error.message; }
});
refresh();

async function checkRenderer() {
  try {
    const info = await request("/api/render/capabilities");
    $("renderNotice").textContent = info.available
      ? "Ready: " + info.supported_output + " · AI clip assembly with original clip audio, optional narration/music, timed captions and cut/fade transitions; storyboard mode also supports scene images and slow zoom."
      : "Server par FFmpeg available nahi hai. Deployment par FFmpeg install hone ke baad MP4 rendering enable hogi.";
    $("renderButton").disabled = !info.available;
  } catch (error) {
    $("renderNotice").textContent = "Renderer status unavailable.";
    $("renderButton").disabled = true;
  }
}
$("renderButton").addEventListener("click", async () => {
  const title = $("renderTitle").value.trim();
  const scenes = $("renderScenes").value.split("\n").map(x => x.trim()).filter(Boolean);
  const seconds = Number($("sceneSeconds").value || 4);
  if (!title || !scenes.length) {
    $("renderNotice").textContent = "Title aur kam se kam ek scene likhein.";
    return;
  }
  $("renderButton").disabled = true;
  $("renderNotice").textContent = "MP4 render ho raha hai…";
  $("renderResult").hidden = true;
  try {
    const result = await request("/api/render", {
      method: "POST",
      body: JSON.stringify({
        title, scenes, seconds_per_scene: seconds,
        timeline: $("renderTimeline").value.split("\n").map(x => x.trim()).filter(Boolean),
        image_ids: $("renderTimeline").value.trim() ? [] : $("renderImageIds").value.split(",").map(x => x.trim()).filter(Boolean),
        video_ids: $("renderTimeline").value.trim() ? [] : $("renderVideoIds").value.split(",").map(x => x.trim()).filter(Boolean),
        audio_id: $("renderAudioId").value.trim() || null,
        music_id: $("renderMusicId").value.trim() || null,
        music_volume: Number($("musicVolume").value || 0.18),
        transition: $("renderTransition").value,
        motion: $("renderTimeline").value.trim() || $("renderVideoIds").value.trim() ? "none" : $("renderMotion").value,
        subtitles: $("renderTimeline").value.trim() ? timelineRows().map(x => x.subtitle || "") : $("renderSubtitles").value.split("\n").map(x => x.trim()).filter(Boolean)
      })
    });
    $("renderVideo").src = result.url;
    $("renderDownload").href = result.url;
    $("renderNotice").textContent = result.resolution + " · " + result.duration_seconds + " sec · " + result.format + " · Audio: " + result.audio + " · Transition: " + result.transition + " · Motion: " + (result.motion || "none");
    $("renderResult").hidden = false;
  } catch (error) {
    $("renderNotice").textContent = error.message;
  } finally {
    $("renderButton").disabled = false;
  }
});

$("musicUploadButton").addEventListener("click", async () => {
  const file = $("musicFile").files[0];
  if (!file) { $("musicNotice").textContent = "Pehle music file select karein."; return; }
  if (file.size > 15 * 1024 * 1024) { $("musicNotice").textContent = "Music file 15 MB se chhoti honi chahiye."; return; }
  if (!$("mediaToken").value.trim()) { $("musicNotice").textContent = "Media access token enter karein."; return; }
  $("musicUploadButton").disabled = true;
  $("musicNotice").textContent = "Music upload aur validation ho rahi hai…";
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = "";
    for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    const result = await request("/api/music/upload", {
      method: "POST",
      headers: {"X-Media-Token": $("mediaToken").value},
      body: JSON.stringify({filename: file.name, data_base64: btoa(binary)})
    });
    $("renderMusicId").value = result.music_id;
    $("musicNotice").textContent = result.format + " · " + Math.ceil(result.size_bytes / 1024) + " KB · Music ID saved. " + result.notice;
  } catch (error) { $("musicNotice").textContent = error.message; }
  finally { $("musicUploadButton").disabled = false; }
});
checkRenderer();



async function checkAIMusicService() {
  try {
    const info = await request("/api/music/capabilities");
    $("aiMusicStatus").textContent = info.available
      ? "Ready: " + info.provider + " · max " + info.max_duration_seconds + " sec · paid generation; check provider pricing."
      : "AI music disabled: server admin must set ENABLE_PAID_MEDIA_GENERATION=true and STABILITY_API_KEY. API charges may apply.";
    $("aiMusicButton").disabled = !info.available;
  } catch (error) {
    $("aiMusicStatus").textContent = "AI music provider status unavailable.";
    $("aiMusicButton").disabled = true;
  }
}
$("aiMusicButton").addEventListener("click", async () => {
  const prompt = $("aiMusicPrompt").value.trim();
  const duration_seconds = Number($("aiMusicDuration").value || 30);
  if (!prompt) { $("aiMusicNotice").textContent = "Music prompt likhein."; return; }
  if (duration_seconds < 5 || duration_seconds > 360) {
    $("aiMusicNotice").textContent = "Duration 5 se 360 seconds honi chahiye."; return;
  }
  if (!$("mediaToken").value.trim()) {
    $("aiMusicNotice").textContent = "Media access token enter karein."; return;
  }
  $("aiMusicButton").disabled = true;
  $("aiMusicNotice").textContent = "Stable Audio music generate kar raha hai. Ismein kuch minute lag sakte hain…";
  $("aiMusicResult").hidden = true;
  try {
    const result = await request("/api/music/generate", {
      method: "POST",
      headers: {"X-Media-Token": $("mediaToken").value},
      body: JSON.stringify({prompt, duration_seconds})
    });
    $("renderMusicId").value = result.music_id;
    $("aiMusicPreview").src = result.url;
    $("aiMusicDownload").href = result.url;
    $("aiMusicAssetId").textContent = "Music ID: " + result.music_id + " · MP4 renderer ke liye automatically selected.";
    $("aiMusicNotice").textContent = result.provider + " · " + result.model + " · " + result.duration_seconds + " sec · " + Math.ceil(result.size_bytes / 1024) + " KB. " + result.notice;
    $("aiMusicResult").hidden = false;
  } catch (error) {
    $("aiMusicNotice").textContent = error.message;
  } finally {
    $("aiMusicButton").disabled = false;
  }
});
checkAIMusicService();

async function checkVoiceService() {
  try {
    const info = await request("/api/voice/capabilities");
    $("voiceNotice").textContent = info.available
      ? "Ready: " + info.provider + " · " + info.model + " · MP3. Paid API usage."
      : !info.enabled_by_admin
        ? "Voiceover server administrator ke explicit paid-media enable karne ka wait kar raha hai."
        : "OpenAI API key server par configured nahi hai.";
    $("voiceButton").disabled = !info.available;
  } catch (error) {
    $("voiceNotice").textContent = "Voice service status unavailable.";
    $("voiceButton").disabled = true;
  }
}
$("voiceButton").addEventListener("click", async () => {
  const text = $("voiceText").value.trim();
  if (!text) { $("voiceNotice").textContent = "Pehle narration script likhein."; return; }
  $("voiceButton").disabled = true;
  $("voiceNotice").textContent = "AI voice generate ho rahi hai…";
  $("voiceResult").hidden = true;
  try {
    const result = await request("/api/voice", {
      method: "POST", headers: {"X-Media-Token": $("mediaToken").value}, body: JSON.stringify({text, voice: $("voiceChoice").value})
    });
    $("voiceAudio").src = result.url;
    $("voiceAssetId").textContent = "Audio ID: " + result.audio_id + " · Is ID ko final MP4 panel mein paste karein.";
    $("voiceDownload").href = result.url;
    $("voiceNotice").textContent = result.format + " · " + result.voice + " · " + Math.ceil(result.size_bytes / 1024) + " KB";
    $("voiceResult").hidden = false;
  } catch (error) { $("voiceNotice").textContent = error.message; }
  finally { $("voiceButton").disabled = false; }
});
$("subtitleButton").addEventListener("click", async () => {
  const scenes = $("subtitleScenes").value.split("\n").map(x => x.trim()).filter(Boolean);
  if (!scenes.length) { $("subtitleNotice").textContent = "Subtitle lines add karein."; return; }
  $("subtitleButton").disabled = true;
  $("subtitleNotice").textContent = "SRT subtitles prepare ho rahe hain…";
  try {
    const response = await fetch("/api/subtitles", {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({scenes, seconds_per_scene: Number($("subtitleSeconds").value || 4)})
    });
    if (!response.ok) { const error = await response.json(); throw new Error(error.detail || "Subtitle export failed"); }
    const blob = await response.blob(), url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "sintu-subtitles.srt"; link.click();
    URL.revokeObjectURL(url);
    $("subtitleNotice").textContent = "SRT subtitle file ready.";
  } catch (error) { $("subtitleNotice").textContent = error.message; }
  finally { $("subtitleButton").disabled = false; }
});
checkVoiceService();


async function checkImageService() {
  try {
    const info = await request("/api/images/capabilities");
    $("imageNotice").textContent = info.available
      ? "Ready: " + info.provider + " · " + info.model + " · PNG source / JPEG download. Paid API usage."
      : !info.enabled_by_admin
        ? "AI image generation server administrator ke explicit paid-media enable karne ka wait kar raha hai."
        : !info.access_token_configured
          ? "Server par MEDIA_GENERATION_TOKEN configure nahi hai."
          : "OpenAI API key server par configured nahi hai.";
    $("imageButton").disabled = !info.available;
  } catch (error) {
    $("imageNotice").textContent = "Image service status unavailable.";
    $("imageButton").disabled = true;
  }
}
$("imageKind").addEventListener("change", () => {
  if ($("imageKind").value === "thumbnail") $("imageAspect").value = "landscape";
});
$("imageButton").addEventListener("click", async () => {
  const prompt = $("imagePrompt").value.trim();
  const kind = $("imageKind").value;
  const aspect = $("imageAspect").value;
  if (!prompt) { $("imageNotice").textContent = "Pehle image prompt likhein."; return; }
  if (kind === "thumbnail" && aspect !== "landscape") {
    $("imageNotice").textContent = "YouTube thumbnail ke liye landscape aspect ratio chunein."; return;
  }
  $("imageButton").disabled = true;
  $("imageNotice").textContent = "AI image generate ho rahi hai. Ismein kuch samay lag sakta hai…";
  $("imageResult").hidden = true;
  try {
    const result = await request("/api/images", {
      method: "POST",
      headers: {"X-Media-Token": $("mediaToken").value},
      body: JSON.stringify({prompt, kind, aspect})
    });
    $("generatedImage").src = result.url;
    $("imageAssetId").textContent = "Image ID: " + result.image_id + " · Har scene image ID ko comma-separated order mein paste karein.";
    if (kind !== "thumbnail") queueTimelineAsset("image", result.image_id, prompt);
    $("imageDownload").href = result.url;
    $("imageNotice").textContent = result.width + " × " + result.height + " · " + result.format + " · " + Math.ceil(result.size_bytes / 1024) + " KB";
    $("imageResult").hidden = false;
  } catch (error) { $("imageNotice").textContent = error.message; }
  finally { $("imageButton").disabled = false; }
});
checkImageService();


async function checkAIVideoService() {
  try {
    const info = await request("/api/video/capabilities");
    $("aiVideoStatus").textContent = info.available
      ? "Ready: " + info.provider + " · " + info.model + " · text/image-to-video · paid API usage."
      : "AI video disabled: server admin must set ENABLE_PAID_MEDIA_GENERATION=true and GEMINI_API_KEY. Paid provider charges apply.";
    $("aiVideoButton").disabled = !info.available;
  } catch (error) {
    $("aiVideoStatus").textContent = "AI video provider status unavailable.";
    $("aiVideoButton").disabled = true;
  }
}
$("aiVideoButton").addEventListener("click", async () => {
  const prompt = $("aiVideoPrompt").value.trim();
  if (!prompt) { $("aiVideoNotice").textContent = "Video scene prompt likhein."; return; }
  if (!$("mediaToken").value.trim()) { $("aiVideoNotice").textContent = "Media access token enter karein."; return; }
  $("aiVideoButton").disabled = true;
  $("aiVideoNotice").textContent = "Gemini AI video clip generate kar raha hai. Ismein kai minute lag sakte hain…";
  $("aiVideoResult").hidden = true;
  try {
    const result = await request("/api/video/generate", {
      method: "POST",
      headers: {"X-Media-Token": $("mediaToken").value},
      body: JSON.stringify({
        prompt,
        style: $("aiVideoStyle").value,
        aspect_ratio: $("aiVideoAspect").value,
        resolution: $("aiVideoResolution").value,
        duration_seconds: Number($("aiVideoDuration").value),
        reference_image_id: $("aiVideoReference").value.trim() || null
      })
    });
    $("aiVideoPreview").src = result.url;
    $("aiVideoDownload").href = result.url;
    $("aiVideoAssetId").textContent = "AI Video ID: " + result.video_id + " · " + result.style + " · " + result.aspect_ratio + " · " + result.resolution + " · " + result.requested_duration_seconds + "s target";
    queueTimelineAsset("video", result.video_id, prompt);
    const existingVideoIds = $("renderVideoIds").value.split(",").map(x => x.trim()).filter(Boolean);
    existingVideoIds.push(result.video_id);
    $("renderVideoIds").value = [...new Set(existingVideoIds)].join(", ");
    $("aiVideoNotice").textContent = result.provider + " · " + result.model + " · MP4 · " + Math.ceil(result.size_bytes / 1024) + " KB. " + result.notice;
    $("aiVideoResult").hidden = false;
  } catch (error) {
    $("aiVideoNotice").textContent = error.message;
  } finally {
    $("aiVideoButton").disabled = false;
  }
});
checkAIVideoService();
