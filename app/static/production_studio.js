/* SINTU Production Studio: server-synced project briefs with offline local fallback. */
(() => {
 const root=document.getElementById("productionStudio");
 if(!root)return;
 const state={catalog:null,format:"youtube-shorts",preset:"mystery-short",localDrafts:[],projects:[],editingProjectId:null,activeRun:null};
 const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const storeKey="sintu.production.drafts.v1";
 function readLocal(){try{state.localDrafts=JSON.parse(localStorage.getItem(storeKey)||"[]");if(!Array.isArray(state.localDrafts))state.localDrafts=[];}catch{state.localDrafts=[];}}
 function saveLocal(){localStorage.setItem(storeKey,JSON.stringify(state.localDrafts.slice(0,100)));renderDrafts();}
 function selectedFormat(){return state.catalog.formats.find(x=>x.id===state.format)||state.catalog.formats[0];}
 function renderFormats(){
  const q=(document.getElementById("formatSearch")?.value||"").toLowerCase();
  const cat=document.getElementById("formatCategory")?.value||"";
  const items=state.catalog.formats.filter(x=>(!cat||x.category===cat)&&(!q||(x.name+" "+x.description).toLowerCase().includes(q)));
  document.getElementById("formatCards").innerHTML=items.map(x=>'<button type="button" class="format-card '+(x.id===state.format?"selected":"")+'" data-format="'+esc(x.id)+'"><b>'+esc(x.name)+'</b><span>'+esc(x.category)+' · '+esc(x.aspect_ratio)+'</span><small>'+esc(x.description)+'</small><em>'+esc(x.stage.replaceAll("_"," "))+'</em></button>').join("")||'<p class="muted">Koi format nahi mila.</p>';
  document.getElementById("formatDetail").textContent=selectedFormat().name+" · "+selectedFormat().recommended_resolution+" · "+selectedFormat().duration;
 }
 function renderPipeline(){document.getElementById("pipelineCards").innerHTML=state.catalog.pipeline.map((x,i)=>'<div class="pipeline-step"><b>'+String(i+1).padStart(2,"0")+' · '+esc(x.name)+'</b><span>'+esc(x.description)+'</span></div>').join("");}
 function renderArchitecture(){
  const scope=state.catalog.scope||{},registry=state.catalog.agent_registry||{};
  document.getElementById("studioArchitectureStats").textContent=(scope.video_format_count||state.catalog.formats.length)+" video formats · "+(scope.studio_module_count||state.catalog.studio_modules.length)+" Studio Modules · "+(registry.specialist_total||0)+" Specialist Agents · "+(registry.checker_total||0)+" independent Checker Agents · ₹0-first policy";
  document.getElementById("studioModulesGrid").innerHTML=(state.catalog.studio_modules||[]).map((name,i)=>'<article class="pipeline-step"><b>'+String(i+1).padStart(2,"0")+' · '+esc(name)+'</b><span>Included in the complete studio architecture</span></article>').join("");
  document.getElementById("studioAgentPairs").innerHTML=(registry.checker_pairs||[]).map((p,i)=>'<div class="agent-pair"><b>'+String(i+1)+'. '+esc(p.specialist)+'</b><span>→ '+esc(p.checker)+'</span></div>').join("");
  const select=document.getElementById("formatCategory"),cats=[...new Set(state.catalog.formats.map(x=>x.category))].sort();
  select.innerHTML='<option value="">All categories</option>'+cats.map(x=>'<option value="'+esc(x)+'">'+esc(x)+'</option>').join("");
 }
 async function loadLatestRun(){
  try{const response=await fetch("/api/studio/runs",{credentials:"same-origin"});const data=await response.json();if(response.ok&&data.runs&&data.runs.length)renderRun(data.runs[0]);}
  catch(error){console.warn("Could not restore latest production run",error);}
 }
 function renderRun(run){
  state.activeRun=run;const p=run.progress||{};const errorLine=run.last_error?'<small>'+esc(run.last_error)+'</small>':'';
  document.getElementById("productionRunStatus").innerHTML='<b>Run '+esc(run.id)+'</b> · '+esc(run.status)+' · '+(p.approved||0)+' / '+(p.total||0)+' approved'+errorLine+'<div class="run-task-list">'+(run.tasks||[]).map(t=>'<div class="agent-pair"><b>'+esc(t.specialist)+'</b> → '+esc(t.checker)+'<span> · '+esc(t.stage_id)+' · '+esc(t.status)+(t.checker_decision?' · '+esc(t.checker_decision):'')+'</span>'+(t.checker_issues?'<small>'+esc(t.checker_issues)+'</small>':'')+'</div>').join("")+'</div>';
  const active=(run.tasks||[]).find(t=>t.id===run.current_task_id);
  document.getElementById("executeNextAgent").disabled=run.status==="in_progress"||!(active&&["pending","needs_revision"].includes(active.status));
  document.getElementById("executeAllAgents").disabled=!run.current_task_id||["in_progress","awaiting_human_approval","completed","approval_rejected"].includes(run.status);
  document.getElementById("executeAllAgents").textContent=run.status==="paused"||run.status==="revision_required"?"Resume All Specialists + Checkers":"Run All Specialists + Checkers";
  document.getElementById("approveProductionRun").disabled=run.status!=="awaiting_human_approval";
 }
 async function saveCurrentProject(){
  const payload=formPayload();if(!payload.brief)throw new Error("Pehle topic ya brief likhein.");
  const editing=state.editingProjectId;
  const r=await fetch(editing?("/api/projects/"+encodeURIComponent(editing)):"/api/projects",{method:editing?"PUT":"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Project save failed.");
  if(editing)state.projects=state.projects.map(x=>x.id===editing?data.project:x);else state.projects.unshift(data.project);
  state.editingProjectId=data.project.id;window.SINTU_ACTIVE_PROJECT_ID=data.project.id;renderDrafts();return data.project;
 }
 async function refreshProjectTools(){
  const projectId=window.SINTU_ACTIVE_PROJECT_ID||state.editingProjectId;const notice=document.getElementById("studioToolsNotice");
  if(!projectId){notice.textContent="Project select/save karein; memory aur assets usi project se linked rahenge.";return;}
  try{
   const [memory,assets,versions,queue]=await Promise.all([
    fetch("/api/studio/memory/"+encodeURIComponent(projectId),{credentials:"same-origin"}).then(r=>r.json()),
    fetch("/api/studio/assets?project_id="+encodeURIComponent(projectId),{credentials:"same-origin"}).then(r=>r.json()),
    fetch("/api/studio/versions/"+encodeURIComponent(projectId),{credentials:"same-origin"}).then(r=>r.json()),
    fetch("/api/studio/render-queue?project_id="+encodeURIComponent(projectId),{credentials:"same-origin"}).then(r=>r.json())
   ]);
   document.getElementById("studioMemoryList").innerHTML=(memory.memory||[]).map(x=>'<div class="agent-pair"><b>'+esc(x.key)+'</b><span>'+esc(x.value)+'</span></div>').join("")||'<p class="muted">No saved project memory.</p>';
   document.getElementById("studioAssetList").innerHTML=(assets.assets||[]).map(x=>'<div class="agent-pair"><b>'+esc(x.name)+'</b><span>'+esc(x.kind)+' · '+esc(x.uri)+'</span><button type="button" class="secondary" data-delete-studio-asset="'+esc(x.id)+'">Delete metadata</button></div>').join("")||'<p class="muted">No project assets yet.</p>';
   document.getElementById("studioVersionList").innerHTML=(versions.versions||[]).map(x=>'<div class="agent-pair"><b>Version '+x.version+'</b><span>'+esc(x.created_at)+'</span></div>').join("")||'<p class="muted">No saved versions.</p>';
   document.getElementById("studioRenderQueueList").innerHTML=(queue.queue||[]).map(x=>'<div class="agent-pair"><b>'+esc(x.id)+'</b><span>'+esc(x.status)+'</span></div>').join("")||'<p class="muted">Render queue empty.</p>';
   notice.textContent="Project tools refreshed · "+(memory.memory||[]).length+" memory items · "+(assets.assets||[]).length+" assets · "+(versions.versions||[]).length+" versions · "+(queue.queue||[]).length+" render jobs.";
  }catch(err){notice.textContent=err.message;}
 }
 function renderDrafts(){
  const el=document.getElementById("localDrafts");if(!el)return;
  const remote=state.projects.map(d=>'<article class="local-draft"><b>'+esc(d.name)+'</b><small>Server saved · '+esc(d.format_id)+(d.last_task_status?' · AI: '+esc(d.last_task_status):'')+' · '+new Date(d.updated_at).toLocaleString()+'</small><p>'+esc(d.brief.slice(0,220))+'</p><div class="actions"><button type="button" class="secondary" data-open-project="'+esc(d.id)+'">Open</button>'+(d.last_task_id?'<button type="button" class="secondary" data-view-project-output="'+esc(d.id)+'">View output #'+esc(d.last_task_id)+'</button>':'')+'<a class="secondary" href="/api/projects/'+esc(d.id)+'/export">Export JSON</a><button type="button" class="secondary" data-delete-project="'+esc(d.id)+'">Delete</button></div></article>').join("");
  const local=state.localDrafts.map((d,i)=>'<article class="local-draft"><b>'+esc(d.name)+'</b><small>Only this device · '+esc(d.formatName)+' · '+new Date(d.updatedAt).toLocaleString()+'</small><p>'+esc(d.topic.slice(0,220))+'</p><div class="actions"><button type="button" class="secondary" data-open-local="'+i+'">Open</button><button type="button" class="secondary" data-delete-local="'+i+'">Delete</button></div></article>').join("");
  el.innerHTML=remote+local||'<p class="muted">Abhi koi saved project nahi hai.</p>';
 }
 function fillForm(d,remote=false){state.editingProjectId=remote?d.id:null;document.getElementById("projectName").value=d.name||"";document.getElementById("projectTopic").value=d.brief||d.topic||"";document.getElementById("projectLanguage").value=d.language||"Hindi";document.getElementById("projectDuration").value=d.duration_seconds||d.duration||60;state.format=d.format_id||d.format||"youtube-shorts";renderFormats();}
 function formPayload(){return {name:document.getElementById("projectName").value.trim()||"Untitled Project",brief:document.getElementById("projectTopic").value.trim(),format_id:state.format,language:document.getElementById("projectLanguage").value.trim()||"Hindi",duration_seconds:Number(document.getElementById("projectDuration").value)||60};}
 function applyPreset(id){const p=state.catalog.presets.find(x=>x.id===id);if(!p)return;state.preset=id;state.format=p.format;document.getElementById("projectName").value=p.name;document.getElementById("projectTopic").value=p.prompt;document.getElementById("projectLanguage").value=p.language;document.getElementById("projectDuration").value=p.duration_seconds;renderFormats();document.getElementById("presetSelect").value=id;}
 async function loadProjects(){try{const r=await fetch("/api/projects",{credentials:"same-origin"});if(!r.ok)throw new Error("Server project sync unavailable");const d=await r.json();state.projects=d.projects||[];document.getElementById("draftNotice").textContent="Server sync connected. Saved projects are available after login on this account.";renderDrafts();}catch{document.getElementById("draftNotice").textContent="Server sync abhi available nahi; local device drafts kaam karenge.";}}
 function init(){
  document.getElementById("formatCards").addEventListener("click",e=>{const b=e.target.closest("[data-format]");if(b){state.format=b.dataset.format;renderFormats();}});
  document.getElementById("formatSearch").addEventListener("input",renderFormats);
  document.getElementById("formatCategory").addEventListener("change",renderFormats);
  document.getElementById("presetSelect").addEventListener("change",e=>{state.editingProjectId=null;applyPreset(e.target.value);});
  document.getElementById("newProjectDraft").addEventListener("click",()=>{state.editingProjectId=null;document.getElementById("projectName").value="My SINTU Video Project";document.getElementById("projectTopic").value="";document.getElementById("projectLanguage").value="Hindi";document.getElementById("projectDuration").value=60;state.format="youtube-shorts";renderFormats();document.getElementById("draftNotice").textContent="New project brief ready.";});
  document.getElementById("saveProjectDraft").addEventListener("click",async()=>{
   const payload=formPayload();if(!payload.brief){alert("Pehle topic ya brief likhein.");return;}
   const notice=document.getElementById("draftNotice");notice.textContent="Project save ho raha hai…";
   try{const editing=state.editingProjectId;const r=await fetch(editing?("/api/projects/"+encodeURIComponent(editing)):"/api/projects",{method:editing?"PUT":"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!r.ok){const e=await r.json().catch(()=>({}));throw new Error(e.detail||"Server save failed");}const data=await r.json();if(editing){state.projects=state.projects.map(x=>x.id===editing?data.project:x);}else{state.projects.unshift(data.project);}state.editingProjectId=data.project.id;renderDrafts();notice.textContent="Project server par save ho gaya. Ab isi account se doosre device par bhi khol sakte hain.";}
   catch(err){state.localDrafts.unshift({id:crypto.randomUUID(),name:payload.name,topic:payload.brief,format:payload.format_id,formatName:selectedFormat().name,language:payload.language,duration:payload.duration_seconds,updatedAt:new Date().toISOString()});saveLocal();notice.textContent="Server save nahi hua; draft is device par save kiya gaya. "+err.message;}
  });
  document.getElementById("generateProductionPackage").addEventListener("click",async()=>{
   const payload=formPayload();if(!payload.brief){alert("Pehle topic ya brief likhein.");return;}
   const preset=selectedFormat().preset;const workflowMap={short:"shorts",long:"long-video",documentary:"long-video",education:"course",ad:"social",live:"content",podcast:"content","2d":"script","3d":"script",motion:"script",film:"long-video",stop:"script",music:"social",vfx:"script",immersive:"script",hybrid:"script",avatar:"script",news:"research"};
   const workflow=workflowMap[preset]||"content";
   const output=document.getElementById("productionPackageOutput");output.hidden=false;output.textContent="AI production package generate ho raha hai…";
   try{
    let projectId=state.editingProjectId;
    const saveResponse=await fetch(projectId?("/api/projects/"+encodeURIComponent(projectId)):"/api/projects",{method:projectId?"PUT":"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const saved=await saveResponse.json().catch(()=>({}));if(!saveResponse.ok)throw new Error(saved.detail||"Project save failed");
    if(projectId){state.projects=state.projects.map(x=>x.id===projectId?saved.project:x);}else{projectId=saved.project.id;state.projects.unshift(saved.project);}
    state.editingProjectId=projectId;window.SINTU_ACTIVE_PROJECT_ID=projectId;renderDrafts();
    const r=await fetch("/api/projects/"+encodeURIComponent(projectId)+"/generate",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({workflow})});
    const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"AI generation failed");
    state.projects=state.projects.map(x=>x.id===projectId?data.project:x);renderDrafts();
    output.textContent="Saved project · Task #"+data.task.id+" · "+data.task.provider+" / "+data.task.model+"\n\n"+data.task.output;
   }catch(err){output.textContent="Generation abhi complete nahi hua: "+err.message+"\n\nLocal Ollama setup karein; paid provider automatically enable nahi hoga.";}
  });
  document.getElementById("refreshStudioTools").addEventListener("click",refreshProjectTools);
  document.getElementById("saveStudioMemory").addEventListener("click",async()=>{
   try{const project=await saveCurrentProject();const r=await fetch("/api/studio/memory",{method:"PUT",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({project_id:project.id,key:document.getElementById("studioMemoryKey").value,value:document.getElementById("studioMemoryValue").value})});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Memory save failed");await refreshProjectTools();}
   catch(err){document.getElementById("studioToolsNotice").textContent=err.message;}
  });
  document.getElementById("addStudioAsset").addEventListener("click",async()=>{
   try{const project=await saveCurrentProject();const r=await fetch("/api/studio/assets",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({project_id:project.id,kind:document.getElementById("studioAssetKind").value,name:document.getElementById("studioAssetName").value,uri:document.getElementById("studioAssetUri").value,metadata:{}})});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Asset save failed");await refreshProjectTools();}
   catch(err){document.getElementById("studioToolsNotice").textContent=err.message;}
  });
  document.getElementById("studioAssetList").addEventListener("click",async(e)=>{
   const b=e.target.closest("[data-delete-studio-asset]");if(!b)return;
   try{const r=await fetch("/api/studio/assets/"+encodeURIComponent(b.dataset.deleteStudioAsset),{method:"DELETE",credentials:"same-origin"});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Asset delete failed");await refreshProjectTools();}
   catch(err){document.getElementById("studioToolsNotice").textContent=err.message;}
  });
  document.getElementById("startProductionRun").addEventListener("click",async()=>{
   const box=document.getElementById("productionRunStatus");box.textContent="Project save aur complete production task queue ban rahi hai…";
   try{const project=await saveCurrentProject();const r=await fetch("/api/studio/runs",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({project_id:project.id,format_id:project.format_id})});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Run create failed");renderRun(data.run);}
   catch(err){box.textContent=err.message;}
  });
  document.getElementById("executeAllAgents").addEventListener("click",async()=>{
   if(!state.activeRun)return;const box=document.getElementById("productionRunStatus");
   try{
    const r=await fetch("/api/studio/runs/"+encodeURIComponent(state.activeRun.id)+"/execute-all",{method:"POST",credentials:"same-origin"});
    const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Background execution failed");
    renderRun(data.run);
    if(data.started){
     box.scrollIntoView({behavior:"smooth",block:"nearest"});
     if(window.SINTU_RUN_POLL)clearInterval(window.SINTU_RUN_POLL);
     window.SINTU_RUN_POLL=setInterval(async()=>{
      try{
       const poll=await fetch("/api/studio/runs/"+encodeURIComponent(state.activeRun.id),{credentials:"same-origin"});
       const latest=await poll.json();if(poll.ok)renderRun(latest.run);
       if(!poll.ok||!["in_progress","queued"].includes(latest.run?.status)){clearInterval(window.SINTU_RUN_POLL);window.SINTU_RUN_POLL=null;}
      }catch(e){clearInterval(window.SINTU_RUN_POLL);window.SINTU_RUN_POLL=null;}
     },3000);
    }
   }catch(err){box.textContent=err.message;}
  });
  document.getElementById("executeNextAgent").addEventListener("click",async()=>{
   if(!state.activeRun)return;const b=document.getElementById("executeNextAgent"),box=document.getElementById("productionRunStatus");b.disabled=true;box.textContent="Local AI specialist aur independent checker alag-alag run ho rahe hain…";
   try{const r=await fetch("/api/studio/runs/"+encodeURIComponent(state.activeRun.id)+"/execute-next",{method:"POST",credentials:"same-origin"});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Agent execution failed");renderRun(data.run);const out=document.getElementById("productionPackageOutput");out.hidden=false;out.textContent="Worker: "+data.worker.role+"\nChecker: "+data.checker.role+" · "+data.checker.decision+"\nEvidence: "+data.checker.evidence+"\n"+(data.checker.issues?"Revision: "+data.checker.issues:"")+"\n\n"+data.worker.output;}
   catch(err){box.textContent=err.message;b.disabled=false;}
  });
  document.getElementById("approveProductionRun").addEventListener("click",async()=>{
   if(!state.activeRun||!confirm("All checker gates pass. Final production run ko approve karna hai?"))return;
   try{const r=await fetch("/api/studio/runs/"+encodeURIComponent(state.activeRun.id)+"/approve",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({approved:true,note:"User approved final production workflow."})});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Approval failed");renderRun(data.run);}
   catch(err){document.getElementById("productionRunStatus").textContent=err.message;}
  });
  document.getElementById("saveProjectVersion").addEventListener("click",async()=>{
   try{const project=await saveCurrentProject();const r=await fetch("/api/studio/versions",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({project_id:project.id})});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Version save failed");document.getElementById("draftNotice").textContent="Version "+data.version.version+" safely saved.";await refreshProjectTools();}
   catch(err){document.getElementById("draftNotice").textContent=err.message;}
  });
  document.getElementById("exportProjectBrief").addEventListener("click",()=>{const d={...formPayload(),format:selectedFormat(),pipeline:state.catalog.pipeline};const blob=new Blob([JSON.stringify(d,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="sintu-project-brief.json";a.click();URL.revokeObjectURL(a.href);});
  document.getElementById("localDrafts").addEventListener("click",async e=>{
   const remoteOpen=e.target.closest("[data-open-project]"),remoteDelete=e.target.closest("[data-delete-project]"),viewTask=e.target.closest("[data-view-project-output]"),localOpen=e.target.closest("[data-open-local]"),localDelete=e.target.closest("[data-delete-local]");
   if(viewTask){const output=document.getElementById("productionPackageOutput");output.hidden=false;output.textContent="Task output load ho raha hai…";try{const r=await fetch("/api/projects/"+encodeURIComponent(viewTask.dataset.viewProjectOutput)+"/task-output",{credentials:"same-origin"});const data=await r.json().catch(()=>({}));if(!r.ok)throw new Error(data.detail||"Task not found");output.textContent="Task #"+data.task.id+" · "+data.task.status+"\n\n"+(data.task.output||data.task.prompt||"No output saved.");}catch(err){output.textContent=err.message;}}
   if(remoteOpen){const d=state.projects.find(x=>x.id===remoteOpen.dataset.openProject);if(d){fillForm(d,true);window.SINTU_ACTIVE_PROJECT_ID=d.id;refreshProjectTools();}}
   if(remoteDelete){const id=remoteDelete.dataset.deleteProject;if(!confirm("Is saved project ko delete karna hai?"))return;try{const r=await fetch("/api/projects/"+encodeURIComponent(id),{method:"DELETE",credentials:"same-origin"});if(!r.ok)throw new Error("Delete failed");state.projects=state.projects.filter(x=>x.id!==id);renderDrafts();}catch(err){alert(err.message);}}
   if(localOpen){const d=state.localDrafts[Number(localOpen.dataset.openLocal)];if(d){fillForm(d,false);window.SINTU_ACTIVE_PROJECT_ID="";}}
   if(localDelete){state.localDrafts.splice(Number(localDelete.dataset.deleteLocal),1);saveLocal();}
  });
  readLocal();renderDrafts();renderPipeline();renderFormats();renderArchitecture();loadProjects();loadLatestRun();
 }
 fetch("/api/production-catalog").then(r=>{if(!r.ok)throw new Error("catalog unavailable");return r.json();}).then(data=>{state.catalog=data;init();}).catch(()=>{root.querySelector("#catalogNotice").textContent="Production catalog load nahi ho paya. Page refresh karein.";});
})();