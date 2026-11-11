const $ = (id) => document.getElementById(id);
$("logout")?.addEventListener("click",async()=>{try{await fetch("/api/auth/logout",{method:"POST"});}finally{location.replace("/login");}});
let latestTaskId = null;
let taskHistoryItems = [];
function renderTaskHistory() {
 const query = $("taskSearch").value.trim().toLowerCase();
 const status = $("taskStatusFilter").value;
 const workflow = $("taskWorkflowFilter").value;
 const filtered = taskHistoryItems.filter(t =>
   (!query || String(t.id).includes(query) || t.prompt.toLowerCase().includes(query)) &&
   (!status || t.status === status) && (!workflow || t.workflow === workflow)
 );
 $("taskFilterSummary").textContent = filtered.length + " of " + taskHistoryItems.length + " recent tasks";
 $("tasks").innerHTML = filtered.length ? filtered.map(t =>
   '<div class="task"><div><b>#'+t.id+' · '+escapeHtml(t.workflow)+'</b><span class="task-status">'+escapeHtml(t.status)+'</span></div>'+
   '<small>'+escapeHtml(t.prompt)+'</small>'+
   (t.output ? '<button class="task-open secondary" data-id="'+t.id+'">View / Download output</button>' : '')+
   (["Failed","Blocked"].includes(t.status) ? ' <button class="task-open secondary" data-retry="'+t.id+'">Retry generation</button>' : '')+
   '</div>'
 ).join("") : '<p class="muted">No tasks match these filters.</p>';
}
$("taskSearch")?.addEventListener("input", renderTaskHistory);
$("taskStatusFilter")?.addEventListener("change", renderTaskHistory);
$("taskWorkflowFilter")?.addEventListener("change", renderTaskHistory);

function parseTimelineEntry(entry) {
 const p=entry.trim().split(":");
 if(p[0]==="image"&&p.length===4&&/^[a-f0-9]{32}$/i.test(p[1]))return {kind:"image",id:p[1].toLowerCase(),duration:Number(p[2]),transition:p[3]};
 if(p[0]==="video"&&p.length===6&&/^[a-f0-9]{32}$/i.test(p[1]))return {kind:"video",id:p[1].toLowerCase(),trimStart:Number(p[2]),trimEnd:p[3]===""?null:Number(p[3]),audioVolume:Number(p[4]),transition:p[5]};
 if(p[0]==="video"&&p.length===5&&/^[a-f0-9]{32}$/i.test(p[1]))return {kind:"video",id:p[1].toLowerCase(),trimStart:Number(p[2]),trimEnd:p[3]===""?null:Number(p[3]),audioVolume:.25,transition:p[4]};
 const legacy=/^(image|video):([a-f0-9]{32}):(\d{1,2}):(cut|fade)$/i.exec(entry.trim());if(!legacy)return null;
 return {kind:legacy[1].toLowerCase(),id:legacy[2].toLowerCase(),duration:legacy[1].toLowerCase()==="image"?Number(legacy[3]):0,trimStart:0,trimEnd:null,audioVolume:.25,transition:legacy[4]};
}
function timelineRows(){const entries=$("renderTimeline").value.split("\n").map(parseTimelineEntry).filter(Boolean),scenes=$("renderScenes").value.split("\n"),subs=$("renderSubtitles").value.split("\n");return entries.map((x,i)=>({...x,scene:scenes[i]||"",subtitle:subs[i]||""}));}
function syncTimelineFields(rows){
 $("renderTimeline").value=rows.map(x=>x.kind==="image"?"image:"+x.id+":"+x.duration+":"+x.transition:"video:"+x.id+":"+(x.trimStart||0)+":"+(x.trimEnd??"")+":"+(x.audioVolume??.25)+":"+x.transition).join("\n");
 $("renderScenes").value=rows.map(x=>x.scene||"").join("\n");$("renderSubtitles").value=rows.map(x=>x.subtitle||"").join("\n");
 $("renderImageIds").value=rows.filter(x=>x.kind==="image").map(x=>x.id).join(", ");$("renderVideoIds").value=rows.filter(x=>x.kind==="video").map(x=>x.id).join(", ");renderTimelineEditor(rows);
}
function renderTimelineEditor(rows=timelineRows()){
 const e=$("timelineEditor");if(!rows.length){e.innerHTML='<p class="muted">Abhi timeline khaali hai. AI image ya AI video generate karein.</p>';return;}
 e.innerHTML=rows.map((x,i)=>{
  const preview=x.kind==="image"?'<img src="/api/images/'+x.id+'" alt="Scene '+(i+1)+' preview" loading="lazy" style="width:100%;max-height:170px;object-fit:contain;background:#111;border-radius:8px">':'<video src="/api/ai-videos/'+x.id+'" controls playsinline preload="metadata" style="width:100%;max-height:170px;background:#111"></video>';
  const edit=x.kind==="image"?'<label>Duration (seconds, 2–12)</label><input type="number" min="2" max="12" data-field="duration" data-index="'+i+'" value="'+x.duration+'">':'<div class="actions"><label>Start (sec)<input type="number" min="0" step="0.1" data-field="trimStart" data-index="'+i+'" value="'+(x.trimStart||0)+'"></label><label>End (sec; blank = full end)<input type="number" min="0.1" step="0.1" data-field="trimEnd" data-index="'+i+'" value="'+(x.trimEnd??"")+'"></label></div><label>Original clip audio: <span data-volume-label="'+i+'">'+Math.round((x.audioVolume??.25)*100)+'%</span></label><input type="range" min="0" max="200" step="5" data-field="audioVolume" data-index="'+i+'" value="'+Math.round((x.audioVolume??.25)*100)+'"><p class="muted">0% = mute, 100% = normal, 200% = double gain. Voiceover/music separately mix honge.</p>';
  return '<article class="panel timeline-row" style="margin:10px 0;padding:12px"><div class="actions"><strong>Scene '+(i+1)+' · '+x.kind.toUpperCase()+'</strong><button type="button" data-action="up" data-index="'+i+'" '+(i===0?'disabled':'')+'>↑</button><button type="button" data-action="down" data-index="'+i+'" '+(i===rows.length-1?'disabled':'')+'>↓</button><button type="button" data-action="remove" data-index="'+i+'">Remove</button></div>'+preview+'<label>Scene description</label><input data-field="scene" data-index="'+i+'" maxlength="1000" value="'+escapeHtml(x.scene||"")+'"><label>Subtitle (optional)</label><input data-field="subtitle" data-index="'+i+'" maxlength="1000" value="'+escapeHtml(x.subtitle||"")+'">'+edit+'<label>Transition after this scene</label><select data-field="transition" data-index="'+i+'"><option value="cut" '+(x.transition==="cut"?"selected":"")+'>Cut</option><option value="fade" '+(x.transition==="fade"?"selected":"")+'>Fade to/from black</option></select></article>';
 }).join("");
}
function queueTimelineAsset(kind,id,sceneText){const rows=timelineRows();if(rows.some(x=>x.kind===kind&&x.id===id))return;rows.push({kind,id,duration:kind==="image"?Number($("sceneSeconds").value||4):0,trimStart:0,trimEnd:null,audioVolume:.25,transition:$("renderTransition").value||"fade",scene:sceneText||"Generated "+kind+" scene",subtitle:""});syncTimelineFields(rows);}
$("timelineEditor").addEventListener("click",event=>{const b=event.target.closest("button[data-action]");if(!b)return;const rows=timelineRows(),i=Number(b.dataset.index);if(b.dataset.action==="remove")rows.splice(i,1);if(b.dataset.action==="up"&&i>0)[rows[i-1],rows[i]]=[rows[i],rows[i-1]];if(b.dataset.action==="down"&&i<rows.length-1)[rows[i+1],rows[i]]=[rows[i],rows[i+1]];syncTimelineFields(rows);});
$("timelineEditor").addEventListener("input",event=>{
 if(event.target.dataset.field!=="audioVolume")return;
 const i=Number(event.target.dataset.index),label=$("timelineEditor").querySelector('[data-volume-label="'+i+'"]');
 if(label)label.textContent=event.target.value+"%";
 const video=event.target.closest(".timeline-row")?.querySelector("video");if(video)video.volume=Math.min(1,Number(event.target.value)/100);
});
$("timelineEditor").addEventListener("change",event=>{
 const field=event.target.dataset.field;if(!field)return;const rows=timelineRows(),x=rows[Number(event.target.dataset.index)];if(!x)return;
 if(field==="duration"){const n=Number(event.target.value);if(!Number.isInteger(n)||n<2||n>12){event.target.value=x.duration;return;}x.duration=n;}
 else if(field==="trimStart"||field==="trimEnd"){const n=event.target.value===""&&field==="trimEnd"?null:Number(event.target.value);if(n!==null&&(!Number.isFinite(n)||n<0)){event.target.value=x[field]??"";return;}if(field==="trimStart")x.trimStart=n;else x.trimEnd=n;if(x.trimEnd!==null&&x.trimEnd<=x.trimStart){event.target.value=x[field]??"";return;}}
 else if(field==="audioVolume")x.audioVolume=Number(event.target.value)/100;
 else x[field]=event.target.value;syncTimelineFields(rows);
});
function playTimelinePreview(){
 const rows=timelineRows(),stage=$("timelinePreviewStage"),notice=$("timelinePreviewNotice");if(!rows.length){notice.textContent="Preview ke liye scenes add karein.";return;}let i=0,timer=null;
 const stop=()=>{if(timer)clearTimeout(timer);const v=stage.querySelector("video");if(v)v.pause();};
 $("timelinePreviewStop").onclick=()=>{stop();notice.textContent="Preview stopped.";};
 const next=()=>{stop();if(i>=rows.length){notice.textContent="Sequence preview complete.";return;}const x=rows[i];notice.textContent="Preview scene "+(i+1)+" / "+rows.length;
  if(x.kind==="image"){stage.innerHTML='<img alt="Timeline scene" style="width:100%;max-height:420px;object-fit:contain" src="/api/images/'+x.id+'">';timer=setTimeout(()=>{i++;next();},x.duration*1000);}
  else{stage.innerHTML='<video controls autoplay playsinline style="width:100%;max-height:420px" src="/api/ai-videos/'+x.id+'"></video>';const v=stage.querySelector("video");v.volume=Math.min(1,x.audioVolume??.25);v.addEventListener("loadedmetadata",()=>{v.currentTime=x.trimStart||0;});v.addEventListener("timeupdate",()=>{if(x.trimEnd!==null&&v.currentTime>=x.trimEnd){v.pause();i++;next();}});v.addEventListener("ended",()=>{i++;next();});}
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
    taskHistoryItems = tasks.tasks;
    renderTaskHistory();
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

function calendarEscape(value) {
 return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
function analyticsEscape(value){return String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));}
function formatAnalyticsDuration(seconds){const n=Math.max(0,Math.round(Number(seconds)||0));return Math.floor(n/60)+"m "+(n%60)+"s";}
async function loadYouTubeAnalytics(){
 const panel=$("youtubeAnalyticsPanel");if(!panel)return;
 const notice=$("youtubeAnalyticsNotice"),button=$("youtubeAnalyticsRefresh");
 button.disabled=true;notice.textContent="YouTube se official analytics load ho rahe hain…";
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const end=$("youtubeAnalyticsEnd").value,start=$("youtubeAnalyticsStart").value;
  const params=new URLSearchParams();if(start)params.set("start_date",start);if(end)params.set("end_date",end);
  const data=await request("/api/admin/youtube/analytics?"+params.toString());
  const t=data.totals||{};
  const cards=[["Views",Number(t.views||0).toLocaleString()],["Watch time",Number(t.estimatedMinutesWatched||0).toLocaleString()+" min"],["Average view",formatAnalyticsDuration(t.averageViewDuration)],["Subscribers gained",Number(t.subscribersGained||0).toLocaleString()],["Subscribers lost",Number(t.subscribersLost||0).toLocaleString()]];
  if(data.revenue?.available){cards.push(["Estimated revenue","₹"+Number(data.revenue.estimated_revenue||0).toFixed(2)]);cards.push(["Ad impressions",Number(data.revenue.ad_impressions||0).toLocaleString()]);cards.push(["Playback CPM","₹"+Number(data.revenue.playback_based_cpm||0).toFixed(2)]);}
  $("youtubeAnalyticsTotals").innerHTML=cards.map(([label,value])=>'<div class="integration-card"><strong>'+analyticsEscape(value)+'</strong><span>'+analyticsEscape(label)+'</span></div>').join("");
  $("youtubeAnalyticsDaily").innerHTML=(data.daily||[]).slice(-31).reverse().map(row=>'<div class="admin-row"><strong>'+analyticsEscape(row.date||"")+'</strong><span>'+Number(row.views||0).toLocaleString()+' views · '+Number(row.watch_minutes||0).toLocaleString()+' min · +'+Number(row.subscribers_gained||0)+' / -'+Number(row.subscribers_lost||0)+' subs</span></div>').join("")||'<p class="muted">Is date range mein daily data nahi mila.</p>';
  $("youtubeAnalyticsVideos").innerHTML=(data.top_videos||[]).map((video,i)=>'<div class="admin-row"><strong>#'+(i+1)+' · '+analyticsEscape(video.video_id)+'</strong><span>'+Number(video.views||0).toLocaleString()+' views · '+Number(video.watch_minutes||0).toLocaleString()+' min · <a href="'+analyticsEscape(video.url)+'" target="_blank" rel="noopener noreferrer">Open video</a></span></div>').join("")||'<p class="muted">Is range mein video report nahi mili.</p>';
  notice.textContent=data.channel+" · "+data.start_date+" to "+data.end_date+" · "+data.note+" · "+(data.revenue?.note||"");
 }catch(error){notice.textContent=error.message;}
 finally{button.disabled=false;}
}
$("youtubeAnalyticsRefresh")?.addEventListener("click",loadYouTubeAnalytics);
async function loadYouTubeReach(){
 const panel=$("youtubeReachPanel");if(!panel)return;
 const notice=$("youtubeReachNotice");
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const data=await request("/api/admin/youtube/reach");
  const setup=$("youtubeReachSetup");setup.hidden=!!data.configured;
  if(data.available){
   const totals=data.totals||{};
   $("youtubeReachTotals").innerHTML=[["Thumbnail impressions",Number(totals.thumbnail_impressions||0).toLocaleString()],["Thumbnail CTR",(Number(totals.thumbnail_ctr||0)*100).toFixed(2)+"%"]]
    .map(([label,value])=>'<div class="integration-card"><strong>'+analyticsEscape(value)+'</strong><span>'+analyticsEscape(label)+'</span></div>').join("");
   $("youtubeReachDaily").innerHTML=(data.daily||[]).slice().reverse().map(x=>'<div class="admin-row"><strong>'+analyticsEscape(x.date)+'</strong><span>'+Number(x.impressions).toLocaleString()+' impressions · '+(Number(x.ctr||0)*100).toFixed(2)+'% CTR</span></div>').join("");
   $("youtubeReachVideos").innerHTML=(data.top_videos||[]).map((x,i)=>'<div class="admin-row"><strong>#'+(i+1)+' · '+analyticsEscape(x.video_id)+'</strong><span>'+Number(x.impressions).toLocaleString()+' impressions · '+(Number(x.ctr||0)*100).toFixed(2)+'% CTR · <a href="'+analyticsEscape(x.url)+'" target="_blank" rel="noopener noreferrer">Open video</a></span></div>').join("");
  }else{
   $("youtubeReachTotals").innerHTML="";$("youtubeReachDaily").innerHTML="";$("youtubeReachVideos").innerHTML="";
  }
  notice.textContent=data.note;
 }catch(e){notice.textContent=e.message;}
}
$("youtubeReachRefresh")?.addEventListener("click",loadYouTubeReach);
$("youtubeReachSetup")?.addEventListener("click",async()=>{
 const button=$("youtubeReachSetup");button.disabled=true;
 try{const result=await request("/api/admin/youtube/reach/setup",{method:"POST"});$("youtubeReachNotice").textContent=result.note;await loadYouTubeReach();
loadYouTubeComments();
if($("youtubeRetentionPanel")){$("youtubeRetentionPanel").hidden=false;}}
 catch(e){$("youtubeReachNotice").textContent=e.message;}
 finally{button.disabled=false;}
});
let youtubeCommentsNextPageToken = "";
let youtubeCommentsCounts = {total:0,possible_spam:0,positive:0,negative:0,questions:0,other:0};
let youtubeCommentsItems = [];
async function loadYouTubeComments(loadMore=false){
 const panel=$("youtubeCommentsPanel");if(!panel)return;
 const button=$("youtubeCommentsRefresh"),more=$("youtubeCommentsMore"),notice=$("youtubeCommentsNotice");
 if(loadMore&&!youtubeCommentsNextPageToken)return;
 button.disabled=true;if(more)more.disabled=true;
 notice.textContent=loadMore?"Aur comments load ho rahe hain…":"Recent YouTube comments analyze ho rahe hain…";
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  if(!loadMore){youtubeCommentsNextPageToken="";youtubeCommentsCounts={total:0,possible_spam:0,positive:0,negative:0,questions:0,other:0};youtubeCommentsItems=[];}
  const query="/api/admin/youtube/comments?limit=50"+(loadMore?"&page_token="+encodeURIComponent(youtubeCommentsNextPageToken):"");
  const data=await request(query),c=data.counts||{};
  Object.keys(youtubeCommentsCounts).forEach(key=>youtubeCommentsCounts[key]+=(Number(c[key])||0));
  youtubeCommentsItems=youtubeCommentsItems.concat(data.comments||[]);
  youtubeCommentsNextPageToken=data.next_page_token||"";
  renderYouTubeCommentTotals();
  renderYouTubeComments();
  if(more)more.hidden=!youtubeCommentsNextPageToken;
  notice.textContent=data.note+" Loaded "+youtubeCommentsItems.length+" comments.";
  if(!loadMore)await loadYouTubeSavedReviews(false);
 }catch(e){notice.textContent=e.message;}
 finally{button.disabled=false;if(more)more.disabled=false;}
}
let youtubeSavedReviewsOffset=0;
let youtubeSavedReviewsTotal=0;
let youtubeSavedReviewsItems=[];
let youtubeSavedReviewSelectedIds=new Set();
async function loadYouTubeSavedReviews(loadMore=false){
 const list=$("youtubeSavedReviewsList"),notice=$("youtubeSavedReviewsNotice"),more=$("youtubeSavedReviewsMore");
 if(!list||!notice)return;
 const status=$("youtubeSavedReviewsFilter")?.value||"";
 const category=$("youtubeSavedReviewsCategory")?.value||"";
 const sort=$("youtubeSavedReviewsSort")?.value||"newest";
 const search=$("youtubeSavedReviewsSearch")?.value.trim()||"";
 const owner=$("youtubeSavedReviewsOwnerFilter")?.value.trim()||"";
 const due=$("youtubeSavedReviewsDueFilter")?.value||"";
 if(!loadMore){youtubeSavedReviewsOffset=0;youtubeSavedReviewsItems=[];youtubeSavedReviewSelectedIds.clear();}
 if(!loadMore&&typeof loadYouTubeFollowUpSummary==="function")loadYouTubeFollowUpSummary();
 notice.textContent="Saved review queue load ho rahi hai…";
 if(more)more.disabled=true;
 try{
  const params=new URLSearchParams({limit:"50",offset:String(youtubeSavedReviewsOffset),sort});
  if(status)params.set("review_status",status);
  if(category)params.set("classification",category);
  if(search)params.set("search",search);
  if(owner)params.set("assigned_to",owner);
  if(due)params.set("follow_up_filter",due);
  const data=await request("/api/admin/youtube/comments/reviews?"+params.toString());
  youtubeSavedReviewsTotal=Number(data.total)||0;
  youtubeSavedReviewsItems=youtubeSavedReviewsItems.concat(data.items||[]);
  youtubeSavedReviewsOffset+=((data.items||[]).length);
  list.innerHTML=youtubeSavedReviewsItems.map((item,index)=>{
   const status=item.review_status||"pending";
   const option=value=>'<option value="'+value+'"'+(status===value?" selected":"")+'>'+({pending:"Pending",reviewed:"Reviewed",follow_up:"Follow-up",resolved:"Resolved"}[value])+'</option>';
   return '<div class="admin-row" data-saved-review-index="'+index+'"><label><input type="checkbox" class="youtube-saved-review-select" data-comment-id="'+analyticsEscape(item.comment_id)+'"'+(youtubeSavedReviewSelectedIds.has(item.comment_id)?" checked":"")+'> Select for bulk review</label><strong>'+analyticsEscape(item.author||"Unknown author")+' · '+analyticsEscape(item.classification||"other")+'</strong><span>'+analyticsEscape(item.text||"Comment text not stored")+'</span><span>'+analyticsEscape(item.video_id)+' · '+Number(item.likes||0).toLocaleString()+' likes · '+analyticsEscape(item.published_at||"")+'</span><label>Assigned to<input class="youtube-saved-review-assignee" maxlength="120" value="'+analyticsEscape(item.assigned_to||"")+'" placeholder="Owner / team member"></label><label>Follow-up date<input class="youtube-saved-review-followup" type="date" value="'+analyticsEscape((item.follow_up_at||"").slice(0,10))+'"></label><label>Review status<select class="youtube-saved-review-status">'+["pending","reviewed","follow_up","resolved"].map(option).join("")+'</select></label><label>Internal review note<textarea class="youtube-saved-review-notes" rows="2" maxlength="1000">'+analyticsEscape(item.notes||"")+'</textarea></label><div class="button-row"><button class="secondary youtube-saved-review-save" type="button">Save changes</button><button class="secondary youtube-saved-review-history" type="button">View history</button></div><div class="muted youtube-saved-review-history-list" aria-live="polite"></div><span class="muted">Last reviewed: '+analyticsEscape(item.updated_at||"")+'</span></div>';
  }).join("")||'<p class="muted">Saved review queue empty hai.</p>';
  if(more)more.hidden=youtubeSavedReviewsOffset>=youtubeSavedReviewsTotal;
  updateYouTubeSavedReviewBulkControls();
  notice.textContent="Saved reviews: "+youtubeSavedReviewsItems.length+" / "+youtubeSavedReviewsTotal+".";
 }catch(e){notice.textContent=e.message;}
 finally{if(more)more.disabled=false;}
}
function renderYouTubeCommentTotals(){
 const totals=youtubeCommentsCounts;
 const reviewTotals={pending:0,reviewed:0,follow_up:0,resolved:0};
 youtubeCommentsItems.forEach(item=>{const status=item.review_status||"pending";if(Object.prototype.hasOwnProperty.call(reviewTotals,status))reviewTotals[status]++;});
 $("youtubeCommentsTotals").innerHTML=[["Total",totals.total],["Possible spam",totals.possible_spam],["Positive",totals.positive],["Negative",totals.negative],["Questions",totals.questions],["Pending review",reviewTotals.pending],["Reviewed",reviewTotals.reviewed],["Follow-up",reviewTotals.follow_up],["Resolved",reviewTotals.resolved]]
  .map(([label,value])=>'<div class="integration-card"><strong>'+analyticsEscape(value)+'</strong><span>'+analyticsEscape(label)+'</span></div>').join("");
}
function getFilteredYouTubeComments(){
 const query=($("youtubeCommentsSearch")?.value||"").trim().toLowerCase();
 const category=$("youtubeCommentsFilter")?.value||"";
 const reviewStatus=$("youtubeCommentsReviewFilter")?.value||"";
 const sort=$("youtubeCommentsSort")?.value||"newest";
 const visible=youtubeCommentsItems.filter(item=>
  (!category||item.classification===category)&&
  (!reviewStatus||(item.review_status||"pending")===reviewStatus)&&
  (!query||(item.text+" "+item.author+" "+(item.review_notes||"")).toLowerCase().includes(query))
 );
 visible.sort((a,b)=>{
  if(sort==="likes")return Number(b.likes||0)-Number(a.likes||0);
  if(sort==="spam")return Number(b.classification==="possible_spam")-Number(a.classification==="possible_spam")||Date.parse(b.published_at||"")-Date.parse(a.published_at||"");
  return Date.parse(b.published_at||"")-Date.parse(a.published_at||"");
 });
 return visible;
}
function renderYouTubeComments(){
 const visible=getFilteredYouTubeComments();
 $("youtubeCommentsList").innerHTML=visible.map((item,index)=>{
  const originalIndex=youtubeCommentsItems.indexOf(item);
  const reviewStatus=item.review_status||"pending";
  const statusOption=value=>'<option value="'+value+'"'+(reviewStatus===value?" selected":"")+'>'+({pending:"Pending",reviewed:"Reviewed",follow_up:"Follow-up",resolved:"Resolved"}[value])+'</option>';
  return '<div class="admin-row" data-comment-index="'+originalIndex+'"><strong>'+analyticsEscape(item.author)+' · '+analyticsEscape(item.classification.replace("_"," "))+'</strong><span>'+analyticsEscape(item.text)+'</span><span>'+Number(item.likes||0).toLocaleString()+' likes · '+analyticsEscape(item.published_at||"")+(item.video_id?' · <a href="https://www.youtube.com/watch?v='+encodeURIComponent(item.video_id)+'" target="_blank" rel="noopener noreferrer">Open video</a>':'')+'</span><label>Review status<select class="youtube-review-status">'+["pending","reviewed","follow_up","resolved"].map(statusOption).join("")+'</select></label><label>Internal review note<textarea class="youtube-review-notes" rows="2" maxlength="1000" placeholder="Optional review note">'+analyticsEscape(item.review_notes||'')+'</textarea></label><button class="secondary youtube-save-review" type="button">Save review</button><span class="muted youtube-review-state">'+analyticsEscape(item.review_status||'pending')+(item.review_updated_at?' · '+analyticsEscape(new Date(item.review_updated_at).toLocaleString()):'')+'</span><label>Reply draft (edit before copying)<textarea class="youtube-reply-draft" rows="2">'+analyticsEscape(item.suggested_reply)+'</textarea></label><button class="secondary youtube-copy-reply" type="button">Copy reply draft</button></div>';
 }).join("")||'<p class="muted">Is filter mein comments nahi mile.</p>';
}
function exportYouTubeCommentsCsv(){
 const rows=getFilteredYouTubeComments();
 if(!rows.length){const n=$("youtubeCommentsNotice");if(n)n.textContent="Export karne ke liye comments nahi hain.";return;}
 const columns=["author","classification","review_status","review_notes","review_updated_at","text","published_at","likes","video_id","suggested_reply"];
 const quote=value=>'"'+String(value??"").replace(/"/g,'""')+'"';
 const csv="\uFEFF"+[columns.join(","),...rows.map(item=>columns.map(key=>quote(item[key])).join(","))].join("\r\n");
 const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));
 const link=document.createElement("a");link.href=url;link.download="sintu-youtube-comments.csv";document.body.appendChild(link);link.click();link.remove();URL.revokeObjectURL(url);
}
$("youtubeCommentsExport")?.addEventListener("click",exportYouTubeCommentsCsv);
$("youtubeCommentsSearch")?.addEventListener("input",renderYouTubeComments);
$("youtubeCommentsFilter")?.addEventListener("change",renderYouTubeComments);
$("youtubeCommentsReviewFilter")?.addEventListener("change",renderYouTubeComments);
$("youtubeCommentsSort")?.addEventListener("change",renderYouTubeComments);
$("youtubeCommentsList")?.addEventListener("click",async event=>{
 const row=event.target.closest(".admin-row");if(!row)return;
 const reviewButton=event.target.closest(".youtube-save-review");
 if(reviewButton){
  const item=youtubeCommentsItems[Number(row.dataset.commentIndex)];if(!item)return;
  reviewButton.disabled=true;
  try{
   const result=await request("/api/admin/youtube/comments/review",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
    comment_id:item.comment_id,video_id:item.video_id,review_status:row.querySelector(".youtube-review-status").value,
    notes:row.querySelector(".youtube-review-notes").value,author:item.author,text:item.text,
    published_at:item.published_at,likes:item.likes,classification:item.classification
   })});
   item.review_status=result.review_status;item.review_notes=result.notes;item.review_updated_at=result.updated_at;
   renderYouTubeCommentTotals();
   $("youtubeCommentsNotice").textContent="Review status saved in SINTU. YouTube comment par koi action nahi hua.";
   renderYouTubeComments();
  }catch(e){row.querySelector(".youtube-review-state").textContent=e.message;}
  finally{reviewButton.disabled=false;}
  return;
 }
 const button=event.target.closest(".youtube-copy-reply");if(!button)return;
 const draft=row.querySelector(".youtube-reply-draft")?.value||"";
 try{await navigator.clipboard.writeText(draft);button.textContent="Copied";}catch(e){button.textContent="Copy unavailable";}
});
$("youtubeSavedReviewsExport")?.addEventListener("click",()=>{
 const params=new URLSearchParams({sort:$("youtubeSavedReviewsSort")?.value||"newest"});
 const status=$("youtubeSavedReviewsFilter")?.value||"",category=$("youtubeSavedReviewsCategory")?.value||"",search=$("youtubeSavedReviewsSearch")?.value.trim()||"";
 if(status)params.set("review_status",status);
 if(category)params.set("classification",category);
 if(search)params.set("search",search);
 window.location.href="/api/admin/youtube/comments/reviews/export?"+params.toString();
});
$("youtubeSavedReviewsRefresh")?.addEventListener("click",()=>loadYouTubeSavedReviews(false));
$("youtubeSavedReviewsFilter")?.addEventListener("change",()=>loadYouTubeSavedReviews(false));
$("youtubeSavedReviewsCategory")?.addEventListener("change",()=>loadYouTubeSavedReviews(false));
$("youtubeSavedReviewsSort")?.addEventListener("change",()=>loadYouTubeSavedReviews(false));
$("youtubeSavedReviewsSearchButton")?.addEventListener("click",()=>loadYouTubeSavedReviews(false));
$("youtubeSavedReviewsSearch")?.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();loadYouTubeSavedReviews(false);}});
$("youtubeSavedReviewsMore")?.addEventListener("click",()=>loadYouTubeSavedReviews(true));
function updateYouTubeSavedReviewBulkControls(){
 const visible=youtubeSavedReviewsItems.map(item=>item.comment_id);
 const selectVisible=$("youtubeSavedReviewsSelectVisible");
 if(selectVisible){
  selectVisible.checked=visible.length>0&&visible.every(id=>youtubeSavedReviewSelectedIds.has(id));
  selectVisible.indeterminate=visible.some(id=>youtubeSavedReviewSelectedIds.has(id))&&!selectVisible.checked;
 }
 const count=$("youtubeSavedReviewsSelectedCount");
 if(count)count.textContent=youtubeSavedReviewSelectedIds.size+" selected";
 const apply=$("youtubeSavedReviewsBulkApply");
 if(apply)apply.disabled=youtubeSavedReviewSelectedIds.size===0;
 const assign=$("youtubeSavedReviewsBulkAssign");if(assign)assign.disabled=youtubeSavedReviewSelectedIds.size===0;
}
$("youtubeSavedReviewsList")?.addEventListener("change",event=>{
 const checkbox=event.target.closest(".youtube-saved-review-select");
 if(!checkbox)return;
 if(checkbox.checked){
  if(youtubeSavedReviewSelectedIds.size>=100){checkbox.checked=false;const notice=$("youtubeSavedReviewsNotice");if(notice)notice.textContent="Ek bulk action mein maximum 100 comments select kar sakte hain.";return;}
  youtubeSavedReviewSelectedIds.add(checkbox.dataset.commentId);
 }else youtubeSavedReviewSelectedIds.delete(checkbox.dataset.commentId);
 updateYouTubeSavedReviewBulkControls();
});
$("youtubeSavedReviewsSelectVisible")?.addEventListener("change",event=>{
 if(event.target.checked){
  const available=100-youtubeSavedReviewSelectedIds.size;
  const remaining=youtubeSavedReviewsItems.filter(item=>!youtubeSavedReviewSelectedIds.has(item.comment_id));
  remaining.slice(0,Math.max(0,available)).forEach(item=>youtubeSavedReviewSelectedIds.add(item.comment_id));
  if(remaining.length>available){event.target.checked=false;const notice=$("youtubeSavedReviewsNotice");if(notice)notice.textContent="Ek bulk action mein maximum 100 comments select ho sakte hain. Baaki items alag batch mein select karein.";}
 }else{
  youtubeSavedReviewsItems.forEach(item=>youtubeSavedReviewSelectedIds.delete(item.comment_id));
 }
 document.querySelectorAll(".youtube-saved-review-select").forEach(box=>{box.checked=youtubeSavedReviewSelectedIds.has(box.dataset.commentId);});
 updateYouTubeSavedReviewBulkControls();
});
$("youtubeSavedReviewsBulkAssign")?.addEventListener("click",async()=>{
 const ids=Array.from(youtubeSavedReviewSelectedIds);if(!ids.length)return;
 const owner=$("youtubeSavedReviewsBulkAssignee").value.trim();
 const due=$("youtubeSavedReviewsBulkFollowUp").value;
 if(!owner&&!due){$("youtubeSavedReviewsNotice").textContent="Owner ya follow-up date mein se kam se kam ek bharein.";return;}
 if(!window.confirm(ids.length+" saved comments ke liye assignment / follow-up save karein? Sirf SINTU records badlenge."))return;
 const button=$("youtubeSavedReviewsBulkAssign"),notice=$("youtubeSavedReviewsNotice");button.disabled=true;
 try{
  const result=await request("/api/admin/youtube/comments/reviews/assign",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({comment_ids:ids,assigned_to:owner,follow_up_at:due})});
  youtubeSavedReviewSelectedIds.clear();await loadYouTubeSavedReviews(false);
  notice.textContent=result.updated+" comments assigned; follow-up details saved internally.";
 }catch(e){notice.textContent=e.message;}
 finally{button.disabled=youtubeSavedReviewSelectedIds.size===0;}
});
$("youtubeSavedReviewsBulkApply")?.addEventListener("click",async()=>{
 const ids=Array.from(youtubeSavedReviewSelectedIds);
 const status=$("youtubeSavedReviewsBulkStatus")?.value||"reviewed";
 if(!ids.length)return;
 const statusLabel={pending:"Pending",reviewed:"Reviewed",follow_up:"Follow-up",resolved:"Resolved"}[status];
 if(!window.confirm(ids.length+" saved comments ko "+statusLabel+" mark karein? Yeh sirf SINTU ke internal records update karega; YouTube par koi action nahi hoga."))return;
 const button=$("youtubeSavedReviewsBulkApply"),notice=$("youtubeSavedReviewsNotice");
 button.disabled=true;notice.textContent="Bulk review save ho raha hai…";
 try{
  const result=await request("/api/admin/youtube/comments/reviews/bulk",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({comment_ids:ids,review_status:status})});
  youtubeSavedReviewSelectedIds.clear();
  await loadYouTubeSavedReviews(false);
  notice.textContent=result.updated+" saved reviews updated to "+statusLabel+". YouTube par koi action nahi hua.";
 }catch(e){notice.textContent=e.message;}
 finally{button.disabled=youtubeSavedReviewSelectedIds.size===0;}
});
$("youtubeSavedReviewsList")?.addEventListener("click",async event=>{
 const row=event.target.closest(".admin-row");
 const historyButton=event.target.closest(".youtube-saved-review-history");
 if(historyButton){
  const item=youtubeSavedReviewsItems[Number(row?.dataset.savedReviewIndex)];
  const historyBox=row.querySelector(".youtube-saved-review-history-list");
  if(!item||!historyBox)return;
  historyButton.disabled=true;historyBox.textContent="History load ho rahi hai…";
  try{
   const data=await request("/api/admin/youtube/comments/reviews/"+encodeURIComponent(item.comment_id)+"/history");
   historyBox.innerHTML=(data.items||[]).map(entry=>'<div>'+analyticsEscape(({created:"Created",bulk_updated:"Bulk status update",assignment_updated:"Assignment update"}[entry.event_type]||"Updated"))+' · '+analyticsEscape(entry.previous_status||"—")+' → '+analyticsEscape(entry.new_status)+' · Owner: '+analyticsEscape(entry.previous_assigned_to||"—")+' → '+analyticsEscape(entry.new_assigned_to||"—")+' · Follow-up: '+analyticsEscape(entry.new_follow_up_at||"—")+' · Note changed: '+(entry.note_changed?"Yes":"No")+' · '+analyticsEscape(entry.changed_at)+'</div>').join("")||"No history available.";
  }catch(e){historyBox.textContent=e.message;}
  finally{historyButton.disabled=false;}
  return;
 }
 const button=event.target.closest(".youtube-saved-review-save");if(!button)return;
 const item=youtubeSavedReviewsItems[Number(row?.dataset.savedReviewIndex)];
 if(!item)return;
 button.disabled=true;
 try{
  const result=await request("/api/admin/youtube/comments/review",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
   comment_id:item.comment_id,video_id:item.video_id,review_status:row.querySelector(".youtube-saved-review-status").value,
   notes:row.querySelector(".youtube-saved-review-notes").value,assigned_to:row.querySelector(".youtube-saved-review-assignee").value,follow_up_at:row.querySelector(".youtube-saved-review-followup").value,author:item.author,text:item.text,
   published_at:item.published_at,likes:item.likes,classification:item.classification
  })});
  item.review_status=result.review_status;item.notes=result.notes;item.assigned_to=result.assigned_to;item.follow_up_at=result.follow_up_at;item.updated_at=result.updated_at;
  await loadYouTubeSavedReviews(false);
  notice.textContent="Saved comment review updated in SINTU. YouTube par koi action nahi hua.";
 }catch(e){notice.textContent=e.message;}
 finally{button.disabled=false;}
});
async function loadYouTubeFollowUpDueInbox(){
 const box=$("youtubeSavedReviewsDueInbox");if(!box)return;
 box.textContent="Due follow-ups load ho rahe hain…";
 try{
  const data=await request("/api/admin/youtube/comments/reviews/follow-ups/due?limit=50");
  const items=data.items||[];
  box.innerHTML='<strong>Action required · '+items.length+'</strong>'+items.map(item=>'<div class="admin-row"><strong>'+analyticsEscape(item.due_state==="overdue"?"OVERDUE":"DUE TODAY")+' · '+analyticsEscape(item.author||"Unknown author")+'</strong><span>'+analyticsEscape(item.text||"Comment text not stored")+'</span><span>Due: '+analyticsEscape(item.follow_up_at)+' · Owner: '+analyticsEscape(item.assigned_to||"Unassigned")+' · '+analyticsEscape(item.review_status)+'</span><button class="secondary youtube-followup-open" data-owner="'+analyticsEscape(item.assigned_to||"")+'" type="button">Open in saved queue</button></div>').join("")||'<p class="muted">Abhi koi overdue ya aaj due follow-up nahi hai.</p>';
 }catch(e){box.textContent=e.message;}
}
$("youtubeSavedReviewsDueInbox")?.addEventListener("click",event=>{
 const button=event.target.closest(".youtube-followup-open");if(!button)return;
 const due=$("youtubeSavedReviewsDueFilter");if(due)due.value=button.closest(".admin-row")?.querySelector("strong")?.textContent.includes("OVERDUE")?"overdue":"today";
 const owner=$("youtubeSavedReviewsOwnerFilter");if(owner)owner.value=button.dataset.owner||"";
 loadYouTubeSavedReviews(false);
});
async function loadYouTubeFollowUpSummary(){
 const box=$("youtubeSavedReviewsWorkload");if(!box)return;
 box.textContent="Workload summary load ho raha hai…";
 try{
  const data=await request("/api/admin/youtube/comments/reviews/follow-ups/summary");
  await loadYouTubeFollowUpDueInbox();
  const totals=data.totals||{};
  const owners=(data.owners||[]).map(row=>'<div class="admin-row"><strong>'+analyticsEscape(row.owner)+'</strong><span>'+Number(row.total||0)+' total · '+Number(row.open||0)+' open · '+Number(row.resolved||0)+' resolved · '+Number(row.overdue||0)+' overdue · '+Number(row.due_today||0)+' due today</span><span>Resolution rate: '+Number(row.resolution_rate||0)+'% · Follow-up coverage: '+Number(row.follow_up_coverage||0)+'%</span></div>').join("");
  box.innerHTML='<strong>Follow-up workload</strong><div>'+Number(totals.total||0)+' total · '+Number(totals.open||0)+' open · '+Number(totals.overdue||0)+' overdue · '+Number(totals.due_today||0)+' due today · '+Number(totals.upcoming||0)+' upcoming · '+Number(totals.unscheduled||0)+' unscheduled · '+Number(totals.resolved||0)+' resolved</div><div>Overall resolution rate: '+Number(totals.resolution_rate||0)+'%</div><strong>Team performance (internal queue)</strong>'+ (owners||'<div>No assigned reviews yet.</div>');
 }catch(e){box.textContent=e.message;}
}
$("youtubeSavedReviewsSummaryRefresh")?.addEventListener("click",loadYouTubeFollowUpSummary);
$("youtubeSavedReviewsWorkloadExport")?.addEventListener("click",()=>{
 const params=new URLSearchParams();
 window.location.href="/api/admin/youtube/comments/reviews/follow-ups/export"+(params.toString()?"?"+params.toString():"");
});
$("youtubeSavedReviewsOwnerFilter")?.addEventListener("change",()=>loadYouTubeSavedReviews(false));
$("youtubeSavedReviewsDueFilter")?.addEventListener("change",()=>loadYouTubeSavedReviews(false));
$("youtubeCommentsRefresh")?.addEventListener("click",async()=>{await loadYouTubeComments(false);await loadYouTubeSavedReviews(false);});
$("youtubeCommentsMore")?.addEventListener("click",()=>loadYouTubeComments(true));
async function loadYouTubeRetention(){
 const panel=$("youtubeRetentionPanel");if(!panel)return;
 const notice=$("youtubeRetentionNotice"),button=$("youtubeRetentionLoad");
 const videoId=$("youtubeRetentionVideoId").value.trim();
 if(!/^[A-Za-z0-9_-]{11,20}$/.test(videoId)){notice.textContent="Valid YouTube video ID daalein.";return;}
 button.disabled=true;notice.textContent="Audience retention load ho rahi hai…";
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const data=await request("/api/admin/youtube/retention?video_id="+encodeURIComponent(videoId));
  const points=data.points||[];
  const first=points[0]||{},last=points[points.length-1]||{};
  $("youtubeRetentionSummary").innerHTML=[["Segments",points.length],["Start watch ratio",(Number(first.audience_watch_ratio||0)*100).toFixed(1)+"%"],["Final watch ratio",(Number(last.audience_watch_ratio||0)*100).toFixed(1)+"%"]]
   .map(([label,value])=>'<div class="integration-card"><strong>'+analyticsEscape(value)+'</strong><span>'+analyticsEscape(label)+'</span></div>').join("");
  $("youtubeRetentionPoints").innerHTML=points.map(p=>{
   const pct=Math.max(0,Math.min(100,Number(p.audience_watch_ratio||0)*100));
   return '<div class="admin-row"><strong>'+(Number(p.elapsed_ratio)*100).toFixed(0)+'% video elapsed</strong><span>Watch ratio '+(Number(p.audience_watch_ratio)*100).toFixed(1)+'% · relative '+(Number(p.relative_retention_performance)*100).toFixed(0)+'% · stopped '+Number(p.stopped_watching||0).toLocaleString()+'</span><div style="height:7px;background:#263246;border-radius:8px;overflow:hidden;margin-top:6px"><div style="height:7px;width:'+pct+'%;background:#54b8ff"></div></div></div>';
  }).join("")||'<p class="muted">Retention data abhi available nahi.</p>';
  notice.textContent=data.note+' · <a href="'+analyticsEscape(data.video_url)+'" target="_blank" rel="noopener noreferrer">Open video</a>';
 }catch(e){notice.textContent=e.message;}
 finally{button.disabled=false;}
}
$("youtubeRetentionLoad")?.addEventListener("click",loadYouTubeRetention);
async function loadAnalyticsOverview(){
 const panel=$("analyticsOverviewPanel");if(!panel)return;
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const data=await request("/api/admin/publishing/history?limit=250");
  const items=data.items||[];
  const published=items.filter(x=>["Published","PUBLISH_COMPLETE"].includes(x.status)).length;
  const processing=items.filter(x=>["PROCESSING_UPLOAD","PROCESSING","PUBLISHING"].includes(x.status)).length;
  const failed=items.filter(x=>["FAILED","PUBLISH_FAILED","ERROR"].includes(x.status)).length;
  const cards=[["Recorded events",items.length],["Published",published],["Processing",processing],["Failed",failed]];
  $("analyticsTotals").innerHTML=cards.map(([name,value])=>'<div class="integration-card"><strong>'+adminEscape(name)+'</strong><span>'+value+'</span></div>').join("");
  const platforms={};items.forEach(x=>{platforms[x.platform]=(platforms[x.platform]||0)+1;});
  $("analyticsPlatforms").innerHTML=Object.entries(platforms).map(([name,count])=>'<div class="admin-row"><strong>'+adminEscape(name)+'</strong><span>'+count+' recorded events</span></div>').join("")||"No publishing events recorded yet.";
  $("analyticsNotice").textContent="Latest 250 recorded events. Views, impressions, CTR, watch time, subscribers and revenue are not yet available from platform analytics APIs.";
 }catch(error){$("analyticsNotice").textContent=error.message;}
}
$("analyticsRefresh")?.addEventListener("click",loadAnalyticsOverview);

async function loadSchedulerQueue(){
 const panel=$("schedulerQueuePanel");if(!panel)return;
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const data=await request("/api/admin/scheduler/queue?hours=24"),s=data.summary||{};
  $("schedulerQueueTotals").innerHTML=[["Awaiting approval",s.awaiting_approval||0],["Due — manual action",s.due_for_manual_action||0],["Next 24 hours",s.approved_next_window||0],["Later",s.approved_later||0]]
   .map(([label,value])=>'<div class="integration-card"><strong>'+calendarEscape(value)+'</strong><span>'+calendarEscape(label)+'</span></div>').join("");
  $("schedulerQueueItems").innerHTML=data.items.length?data.items.map(item=>{
   const when=new Date(item.scheduled_at_utc||item.scheduled_at).toLocaleString();
   const labels={awaiting_approval:"Approval needed",overdue_awaiting_manual_publish:"Due — publish manually",approved_upcoming:"Upcoming in 24 hours",scheduled_later:"Approved — later",not_approved:"Not approved",invalid_schedule:"Invalid schedule"};
   return '<article class="calendar-item"><div><strong>'+calendarEscape(item.title)+'</strong><span>'+calendarEscape(item.platform)+' · '+calendarEscape(labels[item.queue_state]||item.queue_state)+'</span><small>'+calendarEscape(when)+'</small></div></article>';
  }).join(""):'<p class="muted">Queue mein koi pending item nahi hai.</p>';
  $("schedulerQueueNotice").textContent=data.notice;
 }catch(error){$("schedulerQueueNotice").textContent=error.message;}
}
$("schedulerQueueRefresh")?.addEventListener("click",loadSchedulerQueue);

async function loadPublishingHistory(){
 const panel=$("publishingHistoryPanel");if(!panel)return;
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const params=new URLSearchParams(),platform=$("publishingPlatformFilter")?.value||"",status=$("publishingStatusFilter")?.value||"";
  if(platform)params.set("platform",platform);if(status)params.set("status",status);
  const data=await request("/api/admin/publishing/history?"+params.toString()),totals=data.totals||{};
  $("publishingTotals").innerHTML=[["Events",totals.events||0],["Published",totals.published||0],["Processing",totals.processing||0],["Failed",totals.failed||0]]
   .map(([label,value])=>'<div class="integration-card"><strong>'+calendarEscape(value)+'</strong><span>'+calendarEscape(label)+'</span></div>').join("");
  $("publishingHistoryItems").innerHTML=data.items.length?data.items.map(item=>{
   const when=new Date(item.created_at).toLocaleString(),link=item.post_url?'<a href="'+calendarEscape(item.post_url)+'" target="_blank" rel="noopener noreferrer">Open post</a>':"";
   return '<article class="calendar-item"><div><strong>'+calendarEscape(item.title||("Calendar item #"+item.calendar_id))+'</strong><span>'+calendarEscape(item.platform.replace("_"," "))+' · '+calendarEscape(item.status)+'</span><small>'+calendarEscape(when)+'</small><p>'+calendarEscape(item.detail||"")+'</p>'+link+'</div></article>';
  }).join(""):'<p class="muted">Abhi publishing history record nahi hai.</p>';
  $("publishingHistoryNotice").textContent=data.note;
 }catch(error){$("publishingHistoryNotice").textContent=error.message;}
}
$("publishingHistoryRefresh")?.addEventListener("click",loadPublishingHistory);
$("publishingPlatformFilter")?.addEventListener("change",loadPublishingHistory);
$("publishingStatusFilter")?.addEventListener("change",loadPublishingHistory);

async function loadCalendar() {
 try {
  const [data, session, yt, meta, tt] = await Promise.all([
   request("/api/calendar"), request("/api/auth/session"), request("/api/admin/youtube/status").catch(()=>({connected:false})), request("/api/admin/meta/status").catch(()=>({connected:false,instagram:null})), request("/api/admin/tiktok/status").catch(()=>({connected:false}))
  ]);
  const canPublish = session.authenticated && session.role === "admin" && yt.connected;
  $("calendarItems").innerHTML = data.items.length ? data.items.map(item => {
   const when = new Date(item.scheduled_at).toLocaleString();
   const actions = item.status === "Needs approval"
    ? '<button class="secondary" data-calendar-approve="'+item.id+'">Approve</button> <button class="secondary" data-calendar-cancel="'+item.id+'">Cancel</button>'
    : (item.status === "Approved" ? '<button class="secondary" data-calendar-cancel="'+item.id+'">Cancel</button>' +
       (canPublish && ["youtube","youtube_shorts"].includes(item.platform) ? ' <button data-youtube-publish="'+item.id+'">Upload rendered MP4</button>' : '') +
       (session.authenticated && session.role==="admin" && meta.connected && item.platform==="facebook" ? ' <button data-meta-facebook="'+item.id+'">Publish Facebook video</button>' : '') +
       (session.authenticated && session.role==="admin" && meta.connected && !!meta.instagram && item.platform==="instagram" ? ' <button data-meta-instagram="'+item.id+'">Publish Instagram Reel</button>' : '') +
       (session.authenticated && session.role==="admin" && tt.connected && item.platform==="tiktok" ? ' <button data-tiktok-publish="'+item.id+'">Publish TikTok</button>' : '') +
       (session.authenticated && session.role==="admin" && tt.connected && item.platform==="tiktok" ? ' <button class="secondary" data-tiktok-status="'+item.id+'">Check TikTok status</button>' : '') : "");
   return '<article class="calendar-item"><div><strong>'+calendarEscape(item.title)+'</strong><span>'+calendarEscape(item.platform.replace("_"," "))+' · '+calendarEscape(item.status)+'</span><small>'+calendarEscape(when)+'</small><p>'+calendarEscape(item.prompt)+'</p>'+actions+'</div></article>';
  }).join("") : '<p class="muted">Calendar abhi khaali hai. Pehla content schedule karein.</p>';
  $("calendarNotice").textContent = data.notice;
 } catch(error) { $("calendarNotice").textContent = error.message; }
}
$("calendarForm")?.addEventListener("submit", async event => {
 event.preventDefault();
 const button = event.submitter; button.disabled = true;
 try {
  const localDate = new Date($("calendarDate").value);
  if (!Number.isFinite(localDate.getTime())) throw new Error("Valid date and time choose karein.");
  const result = await request("/api/calendar", {method:"POST",body:JSON.stringify({
   title:$("calendarTitle").value.trim(), platform:$("calendarPlatform").value,
   prompt:$("calendarPrompt").value.trim(), scheduled_at:localDate.toISOString()
  })});
  $("calendarNotice").textContent = "Calendar item #"+result.id+" save ho gaya. Approval required.";
  $("calendarForm").reset(); await loadCalendar();
 } catch(error) { $("calendarNotice").textContent = error.message; }
 finally { button.disabled = false; }
});
$("calendarItems")?.addEventListener("click", async event => {
 const approve = event.target.closest("[data-calendar-approve]");
 const cancel = event.target.closest("[data-calendar-cancel]");
 const publish = event.target.closest("[data-youtube-publish]");
 const metaFacebook=event.target.closest("[data-meta-facebook]");
 const metaInstagram=event.target.closest("[data-meta-instagram]");
 const tiktokPublish=event.target.closest("[data-tiktok-publish]");
 const tiktokStatus=event.target.closest("[data-tiktok-status]");
 if(tiktokPublish){
  const id=Number(tiktokPublish.dataset.tiktokPublish);
  const videoId=window.prompt("Rendered MP4 Video ID (32-character ID):");if(!videoId)return;
  if(!/^[a-f0-9]{32}$/i.test(videoId)){$("calendarNotice").textContent="Video ID format invalid.";return;}
  let creator;
  try{creator=await request("/api/admin/tiktok/creator");}catch(e){$("calendarNotice").textContent=e.message;return;}
  const info=creator.creator||{};
  const options=info.privacy_level_options||[];
  if(!options.length){$("calendarNotice").textContent="TikTok privacy options unavailable.";return;}
  const privacy=window.prompt("TikTok privacy options: "+options.join(", "),options.includes("SELF_ONLY")?"SELF_ONLY":options[0]);
  if(!options.includes(privacy)){$("calendarNotice").textContent="Choose one of the available privacy options.";return;}
  const title=window.prompt("TikTok caption (max 2200 characters):","")||"";
  if(title.length>2200){$("calendarNotice").textContent="Caption is too long.";return;}
  const aigc=window.confirm("Kya yeh video AI-generated hai? OK = AI-generated label, Cancel = not AI-generated.");
  if(!window.confirm("TikTok account @"+(info.creator_username||"creator")+" par video "+privacy+" visibility ke saath bhejna hai?"))return;
  const params=new URLSearchParams({video_id:videoId.toLowerCase(),title,privacy_level:privacy,is_aigc:String(aigc)});
  tiktokPublish.disabled=true;
  try{const result=await request("/api/admin/tiktok/publish/"+id+"?"+params.toString(),{method:"POST"});
   $("calendarNotice").textContent="TikTok transfer complete; processing pending. Publish ID: "+result.publish_id+" · Status button se result check karein.";
   await loadCalendar();
  }catch(e){$("calendarNotice").textContent=e.message;tiktokPublish.disabled=false;}return;
 }
 if(tiktokStatus){
  const id=Number(tiktokStatus.dataset.tiktokStatus);tiktokStatus.disabled=true;
  try{const result=await request("/api/admin/tiktok/status/"+id,{method:"POST"});
   $("calendarNotice").textContent="TikTok status: "+result.status+(result.detail?" · "+result.detail:"");await loadCalendar();await loadPublishingHistory();}
  catch(e){$("calendarNotice").textContent=e.message;tiktokStatus.disabled=false;}return;
 }
 if(metaFacebook||metaInstagram){
  const id=Number((metaFacebook||metaInstagram).dataset[metaFacebook?"metaFacebook":"metaInstagram"]);
  const videoId=window.prompt("Rendered MP4 Video ID (32-character ID):");if(!videoId)return;
  if(!/^[a-f0-9]{32}$/i.test(videoId)){$("calendarNotice").textContent="Video ID format invalid.";return;}
  let url,params;
  if(metaFacebook){
   const title=window.prompt("Facebook video title:");if(!title)return;
   const description=window.prompt("Facebook description (optional):")||"";
   url="/api/admin/meta/facebook/publish/"+id;params=new URLSearchParams({video_id:videoId.toLowerCase(),title,description});
   if(!window.confirm("Approved MP4 connected Facebook Page par publish karein?"))return;
  }else{
   const videoUrl=window.prompt("Public HTTPS MP4 URL (Meta ko video fetch karna hoga):");if(!videoUrl)return;
   const caption=window.prompt("Instagram Reel caption (optional):")||"";
   url="/api/admin/meta/instagram/publish/"+id;params=new URLSearchParams({video_url:videoUrl,caption});
   if(!window.confirm("Public video URL connected Instagram account par Reel ke roop mein publish karein?"))return;
  }
  const b=metaFacebook||metaInstagram;b.disabled=true;
  try{const result=await request(url+"?"+params.toString(),{method:"POST"});
   $("calendarNotice").textContent=(metaFacebook?"Facebook":"Instagram")+" publish successful. "+(result.url||result.message||"");await loadCalendar();await loadPublishingHistory();}
  catch(e){$("calendarNotice").textContent=e.message;b.disabled=false;}return;
 }
 if (publish) {
  const calendarId = Number(publish.dataset.youtubePublish);
  const videoId = window.prompt("Rendered MP4 Video ID (32-character ID from SINTU render result):");
  if (!videoId) return;
  if (!/^[a-f0-9]{32}$/i.test(videoId)) { $("calendarNotice").textContent="Video ID format invalid."; return; }
  const title = window.prompt("YouTube video title (100 characters max):");
  if (!title || title.length > 100) { $("calendarNotice").textContent="Valid YouTube title required."; return; }
  const privacy = window.prompt("Privacy: private, unlisted, or public", "private");
  if (!["private","unlisted","public"].includes(privacy)) { $("calendarNotice").textContent="Privacy value invalid."; return; }
  if (privacy !== "private" && !window.confirm("Video "+privacy+" hoga. Kya aap confirm karte hain?")) return;
  const params = new URLSearchParams({video_id:videoId.toLowerCase(),title,privacy_status:privacy});
  publish.disabled=true;
  try {
   const result=await request("/api/admin/youtube/publish/"+calendarId+"?"+params.toString(),{method:"POST"});
   $("calendarNotice").textContent="YouTube par upload ho gaya: "+result.url;
   await loadCalendar();
  } catch(error) { $("calendarNotice").textContent=error.message; publish.disabled=false; }
  return;
 }
 if (!approve && !cancel) return;
 const id = Number((approve || cancel).dataset[approve ? "calendarApprove" : "calendarCancel"]);
 const action = approve ? "approve" : "cancel";
 try {
  const result = await request("/api/calendar/"+id+"/"+action,{method:"POST"});
  $("calendarNotice").textContent = "Calendar #"+id+": "+result.status;
  await loadCalendar();
 } catch(error) { $("calendarNotice").textContent = error.message; }
});
$("calendarRefresh")?.addEventListener("click", loadCalendar);
loadCalendar();
loadPublishingHistory();
loadSchedulerQueue();
loadAnalyticsOverview();
loadYouTubeAnalytics();
loadYouTubeReach();
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
  const retryButton = event.target.closest("[data-retry]");
  if (retryButton) {
    const id = Number(retryButton.dataset.retry);
    retryButton.disabled = true;
    retryButton.textContent = "Retrying…";
    try {
      const result = await request("/api/tasks/" + id + "/retry", {method:"POST"});
      $("notice").textContent = "Task #" + id + " completed successfully.";
      $("result").textContent = result.output || "";
      $("resultWrap").hidden = !result.output;
      latestTaskId = id;
    } catch (error) {
      $("notice").textContent = error.message;
    } finally {
      await refresh();
    }
    return;
  }
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
        resolution: $("renderResolution").value,
        fps: Number($("renderFps").value),
        quality: $("renderQuality").value,
        transition: $("renderTransition").value,
        motion: $("renderTimeline").value.trim() || $("renderVideoIds").value.trim() ? "none" : $("renderMotion").value,
        subtitles: $("renderTimeline").value.trim() ? timelineRows().map(x => x.subtitle || "") : $("renderSubtitles").value.split("\n").map(x => x.trim()).filter(Boolean)
      })
    });
    $("renderVideo").src = result.url;
    $("renderDownload").href = result.url;
    $("renderNotice").textContent = result.resolution + " · " + (result.fps || 30) + " FPS · " + (result.quality || "high") + " quality · " + result.duration_seconds + " sec · " + result.format + " · Audio: " + result.audio + " · Transition: " + result.transition + " · Motion: " + (result.motion || "none");
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


function integrationStatusLabel(status) {
  return ({ready:"Ready",needs_server_key:"Server API key required",needs_ffmpeg:"FFmpeg required",enabled:"Enabled (paid)",disabled:"Disabled",not_connected:"Not connected"})[status] || status;
}
async function loadProviderAdminPanel() {
  const panel = $("providerAdminPanel");
  if (!panel) return;
  try {
    const session = await request("/api/auth/session");
    if (!session.authenticated || session.role !== "admin") { panel.hidden = true; return; }
    panel.hidden = false;
    const [settings, integrations] = await Promise.all([
      request("/api/admin/provider-settings"), request("/api/admin/integrations")
    ]);
    $("selectedProvider").value = settings.selected_provider;
    $("providerCards").innerHTML = Object.entries(settings.providers).map(([key,value]) => `
      <div class="integration-card"><strong>${key==="openai"?"OpenAI":"Google Gemini"}</strong><span>${value.configured?"API key configured":"API key missing"}</span><small>Model: ${adminEscape(value.model)}</small></div>`).join("");
    const rows = [
      ["Text AI", integrations.text_ai.status, integrations.text_ai.selected],
      ["MP4 rendering", integrations.video_rendering.status, "FFmpeg server dependency"],
      ["Paid media generation", integrations.paid_media_generation.status, "Paid usage; requires server toggle and media token"],
      ["YouTube publishing", integrations.youtube_publishing.status, integrations.youtube_publishing.note],
      ["Social publishing", integrations.social_publishing.status, integrations.social_publishing.note],
      ["Channel analytics", integrations.analytics.status, integrations.analytics.note],
      ["Claude / DeepSeek / GLM / Doubao / Kimi", integrations.other_text_providers.status, "Not integrated in current adapter"]
    ];
    $("integrationCards").innerHTML = rows.map(([name,status,detail]) => `
      <div class="integration-card"><strong>${adminEscape(name)}</strong><span>${adminEscape(integrationStatusLabel(status))}</span><small>${adminEscape(detail)}</small></div>`).join("");
    $("providerAdminNotice").textContent = "Provider settings refreshed. Keys are never displayed.";
  } catch(error) { panel.hidden = true; }
}
function adminEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
}
async function loadAdminPanel() {
  const panel = $("adminPanel");
  if (!panel) return;
  try {
    const session = await request("/api/auth/session");
    if (!session.authenticated || session.role !== "admin") { panel.hidden = true; return; }
    panel.hidden = false;
    const [usersData, auditData] = await Promise.all([request("/api/admin/users"), request("/api/admin/audit?limit=40")]);
    $("adminUsers").innerHTML = usersData.users.map(user => `
      <div class="admin-row">
        <div><strong>${adminEscape(user.username)}</strong><small>#${user.id} · ${adminEscape(user.created_at)}</small></div>
        <select data-user-role="${user.id}" aria-label="Role for ${adminEscape(user.username)}">
          <option value="viewer" ${user.role==="viewer"?"selected":""}>Viewer</option>
          <option value="editor" ${user.role==="editor"?"selected":""}>Editor</option>
          <option value="admin" ${user.role==="admin"?"selected":""}>Admin</option>
        </select>
        <span class="role-state">${user.is_active?"Active":"Disabled"}</span>
        <button class="secondary user-reset" data-user-id="${user.id}" type="button">Reset password</button>
        <button class="secondary user-toggle" data-user-id="${user.id}" data-active="${user.is_active?0:1}" type="button">${user.is_active?"Disable":"Enable"}</button>
      </div>`).join("") || "No users.";
    $("adminAudit").innerHTML = auditData.events.map(event => `
      <div class="admin-row audit-row">
        <div><strong>${adminEscape(event.actor_username)} · ${adminEscape(event.actor_role)}</strong><small>${adminEscape(event.created_at)} · ${adminEscape(event.ip_address)}</small></div>
        <div><b>${adminEscape(event.method)} ${adminEscape(event.path)}</b><small>HTTP ${event.status_code}</small></div>
      </div>`).join("") || "No security events yet.";
    $("adminNotice").textContent = "Users: " + usersData.users.length + " · Recent security events: " + auditData.events.length;
    document.querySelectorAll("[data-user-role]").forEach(select => select.addEventListener("change", async () => {
      try { await request("/api/admin/users/" + select.dataset.userRole, {method:"PATCH",body:JSON.stringify({role:select.value})}); await loadAdminPanel(); }
      catch(error) { $("adminNotice").textContent = error.message; }
    }));
    document.querySelectorAll(".user-reset").forEach(button => button.addEventListener("click", async () => {
      const password = window.prompt("Naya temporary password (minimum 12 characters):");
      if (password === null) return;
      if (password.length < 12) { $("adminNotice").textContent = "Password kam se kam 12 characters ka hona chahiye."; return; }
      try {
        await request("/api/admin/users/" + button.dataset.userId, {method:"PATCH",body:JSON.stringify({password})});
        $("adminNotice").textContent = "Password reset ho gaya. Naya password secure channel se user ko share karein.";
      } catch(error) { $("adminNotice").textContent = error.message; }
    }));
    document.querySelectorAll(".user-toggle").forEach(button => button.addEventListener("click", async () => {
      try { await request("/api/admin/users/" + button.dataset.userId, {method:"PATCH",body:JSON.stringify({is_active:button.dataset.active==="1"})}); await loadAdminPanel(); }
      catch(error) { $("adminNotice").textContent = error.message; }
    }));
  } catch(error) { panel.hidden = true; }
}
$("adminUserForm")?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $("adminNotice").textContent = "Creating account…";
  try {
    await request("/api/admin/users", {method:"POST",body:JSON.stringify({
      username:$("newUsername").value.trim(), password:$("newPassword").value, role:$("newRole").value
    })});
    $("adminUserForm").reset();
    $("adminNotice").textContent = "New user created. Password user ko secure channel se share karein.";
    await loadAdminPanel();
  } catch(error) { $("adminNotice").textContent = error.message; }
  finally { button.disabled = false; }
});
$("adminRefresh")?.addEventListener("click", loadAdminPanel);
$("providerSettingsForm")?.addEventListener("submit", async event => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  $("providerAdminNotice").textContent = "Saving provider preference…";
  try {
    const result = await request("/api/admin/provider-settings", {method:"PATCH",body:JSON.stringify({selected_provider:$("selectedProvider").value})});
    $("providerAdminNotice").textContent = "Saved: " + result.selected_provider + ". New AI generation will use this preference.";
    await loadProviderAdminPanel();
  } catch(error) { $("providerAdminNotice").textContent = error.message; }
  finally { button.disabled = false; }
});
$("providerRefresh")?.addEventListener("click", loadProviderAdminPanel);

async function loadPublishingConnections(){
 const panel=$("publishingConnectionsPanel");if(!panel)return;
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const [youtube,meta,tiktok]=await Promise.all([
   request("/api/admin/youtube/status"),request("/api/admin/meta/status"),request("/api/admin/tiktok/status")
  ]);
  const rows=[
   ["YouTube",youtube.connected,"Connected channel: "+(youtube.channel?.title||""),youtube.oauth_configured,youtube.encryption_configured],
   ["Facebook / Instagram",meta.connected,"Facebook Page: "+(meta.page?.name||"")+(meta.instagram?" · Instagram @"+(meta.instagram.username||"linked"):""),meta.oauth_configured,meta.encryption_configured],
   ["TikTok",tiktok.connected,"Creator: "+(tiktok.creator?.display_name||""),tiktok.oauth_configured,tiktok.encryption_configured]
  ];
  $("publishingConnectionsCards").innerHTML=rows.map(([name,connected,detail,oauth,encrypted])=>{
   const state=connected?"Connected":oauth&&encrypted?"Ready to connect":"Setup required";
   const hint=connected?detail:(!oauth?"Developer app credentials missing":!encrypted?"Token encryption key missing":"Account authorization required");
   return '<div class="integration-card"><strong>'+adminEscape(name)+'</strong><span>'+adminEscape(state)+'</span><small>'+adminEscape(hint)+'</small></div>';
  }).join("");
  $("publishingConnectionsNotice").textContent=rows.filter(x=>x[1]).length+" platform group(s) connected. Har post par admin approval aur supported permissions required hain.";
 }catch(error){$("publishingConnectionsNotice").textContent=error.message;}
}
$("publishingConnectionsRefresh")?.addEventListener("click",loadPublishingConnections);

async function loadYouTubeAdminPanel() {
 const panel = $("youtubeAdminPanel"); if (!panel) return;
 try {
  const session = await request("/api/auth/session");
  if (!session.authenticated || session.role !== "admin") { panel.hidden = true; return; }
  panel.hidden = false;
  const data = await request("/api/admin/youtube/status");
  $("youtubeConnectionStatus").textContent = data.connected
   ? "Connected channel: "+data.channel.title+" · "+data.channel.id
   : "Not connected. OAuth client: "+(data.oauth_configured?"configured":"missing")+" · token encryption: "+(data.encryption_configured?"configured":"missing");
  $("youtubeConnect").disabled = !data.oauth_configured || !data.encryption_configured;
  $("youtubeDisconnect").hidden = !data.connected;
 } catch(error) { $("youtubeConnectionStatus").textContent = error.message; }
}
$("youtubeConnect")?.addEventListener("click", async () => {
 const button=$("youtubeConnect"); button.disabled=true;
 try { const data=await request("/api/admin/youtube/oauth/start"); window.location.assign(data.authorization_url); }
 catch(error) { $("youtubeConnectionStatus").textContent=error.message; button.disabled=false; }
});
$("youtubeDisconnect")?.addEventListener("click", async () => {
 if (!window.confirm("YouTube channel disconnect karein?")) return;
 try { await request("/api/admin/youtube/disconnect",{method:"POST"}); await loadYouTubeAdminPanel(); }
 catch(error) { $("youtubeConnectionStatus").textContent=error.message; }
});
$("youtubeRefresh")?.addEventListener("click",loadYouTubeAdminPanel);
loadYouTubeAdminPanel();
loadPublishingConnections();

async function loadMetaAdminPanel(){
 const panel=$("metaAdminPanel");if(!panel)return;
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const data=await request("/api/admin/meta/status");
  const ig=data.instagram?" · Instagram: @"+(data.instagram.username||data.instagram.id):" · Instagram Professional account not linked";
  $("metaConnectionStatus").textContent=data.connected?"Facebook Page: "+data.page.name+" ("+data.page.id+")"+ig:
   "Not connected · Meta App: "+(data.oauth_configured?"configured":"missing")+" · encryption: "+(data.encryption_configured?"ready":"missing");
  $("metaConnect").disabled=!data.oauth_configured||!data.encryption_configured;
  $("metaDisconnect").hidden=!data.connected;
 }catch(e){$("metaConnectionStatus").textContent=e.message;}
}
$("metaConnect")?.addEventListener("click",async()=>{
 const b=$("metaConnect");b.disabled=true;
 try{const d=await request("/api/admin/meta/oauth/start");window.location.assign(d.authorization_url);}
 catch(e){$("metaConnectionStatus").textContent=e.message;b.disabled=false;}
});
$("metaDisconnect")?.addEventListener("click",async()=>{
 if(!window.confirm("Facebook Page aur Instagram connection disconnect karein?"))return;
 try{await request("/api/admin/meta/disconnect",{method:"POST"});await loadMetaAdminPanel();}
 catch(e){$("metaConnectionStatus").textContent=e.message;}
});
$("metaRefresh")?.addEventListener("click",loadMetaAdminPanel);
loadMetaAdminPanel();

async function loadTikTokAdminPanel(){
 const panel=$("tiktokAdminPanel");if(!panel)return;
 try{
  const session=await request("/api/auth/session");
  if(!session.authenticated||session.role!=="admin"){panel.hidden=true;return;}
  panel.hidden=false;
  const data=await request("/api/admin/tiktok/status");
  $("tiktokConnectionStatus").textContent=data.connected
   ?"Connected: "+data.creator.display_name+" · Open ID "+data.creator.open_id+" · Scopes: "+data.scopes.join(", ")
   :"Not connected · TikTok App: "+(data.oauth_configured?"configured":"missing")+" · encryption: "+(data.encryption_configured?"ready":"missing");
  $("tiktokConnect").disabled=!data.oauth_configured||!data.encryption_configured;
  $("tiktokDisconnect").hidden=!data.connected;
 }catch(e){$("tiktokConnectionStatus").textContent=e.message;}
}
$("tiktokConnect")?.addEventListener("click",async()=>{
 const b=$("tiktokConnect");b.disabled=true;
 try{const d=await request("/api/admin/tiktok/oauth/start");window.location.assign(d.authorization_url);}
 catch(e){$("tiktokConnectionStatus").textContent=e.message;b.disabled=false;}
});
$("tiktokDisconnect")?.addEventListener("click",async()=>{
 if(!window.confirm("TikTok account disconnect karein?"))return;
 try{await request("/api/admin/tiktok/disconnect",{method:"POST"});await loadTikTokAdminPanel();}
 catch(e){$("tiktokConnectionStatus").textContent=e.message;}
});
$("tiktokRefresh")?.addEventListener("click",loadTikTokAdminPanel);
loadTikTokAdminPanel();
loadAdminPanel();
loadProviderAdminPanel();
