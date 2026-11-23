(() => {
  const $ = id => document.getElementById(id);
  const state = {formats:[], plan:null, runs:[]};
  const esc = value => String(value ?? "").replace(/[&<>"']/g, ch => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));
  async function api(path, options={}) {
    const response = await fetch(path, {credentials:"same-origin", ...options,
      headers:{"Content-Type":"application/json", ...(options.headers||{})}});
    let data={}; try { data=await response.json(); } catch {}
    if (!response.ok) throw new Error(data.detail || data.message || ("HTTP "+response.status));
    return data;
  }
  function notice(message, error=false) {
    $("factoryNotice").textContent=message;
    $("factoryNotice").className=error?"factory-error":"factory-meta";
  }
  async function loadFormats() {
    const catalog=await api("/api/production-catalog");
    state.formats=Array.isArray(catalog.formats)?catalog.formats:[];
    const select=$("factoryFormat"); select.replaceChildren();
    for(const format of state.formats){
      const option=document.createElement("option"); option.value=format.id;
      option.textContent=format.name+" · "+format.id; select.append(option);
    }
    if(!state.formats.length) throw new Error("Production catalog mein koi format nahi mila.");
    notice("Formats ready. Pehle plan banayein; phir internal run start kar sakte hain.");
  }
  function renderPlan(plan) {
    const root=$("factoryPlanOutput"); root.replaceChildren();
    const heading=document.createElement("h3"); heading.textContent=(plan.pipeline_stage_count||plan.stages?.length||0)+"-stage factory plan"; root.append(heading);
    for(const stage of plan.stages||[]){
      const card=document.createElement("article"); card.className="factory-stage";
      const title=document.createElement("b"); title.textContent=stage.sequence+". "+stage.name; card.append(title);
      const status=document.createElement("span"); status.className="factory-pill"; status.textContent=stage.readiness; card.append(status);
      const detail=document.createElement("p"); detail.className="factory-meta";
      detail.textContent=(stage.provider_candidates||[]).map(x=>x.name+" ("+x.selection+")").join(" · ") || "No external provider required";
      card.append(detail); root.append(card);
    }
    const warning=document.createElement("p"); warning.className="factory-meta";
    warning.textContent=plan.notice+" Owner review required before publishing.";
    root.append(warning);
  }
  async function buildPlan() {
    const topic=$("factoryTopic").value.trim(), format_id=$("factoryFormat").value;
    if(!topic||!format_id){notice("Topic aur format dono bharna zaroori hai.",true);return;}
    $("factoryPlan").disabled=true; $("factoryStart").disabled=true; notice("Factory plan build ho raha hai…");
    try{state.plan=await api("/api/production-factory/plan",{method:"POST",body:JSON.stringify({topic,format_id})});renderPlan(state.plan);$("factoryStart").disabled=false;notice("Plan ready. Start button internal worker queue karega; publishing nahi hogi.");}
    catch(error){notice(error.message,true);}finally{$("factoryPlan").disabled=false;}
  }
  async function startRun() {
    if(!state.plan){notice("Pehle factory plan banayein.",true);return;}
    const topic=$("factoryTopic").value.trim(), format_id=$("factoryFormat").value;
    $("factoryStart").disabled=true;notice("Persistent production worker queue ho raha hai…");
    try{const result=await api("/api/production-factory/runs",{method:"POST",body:JSON.stringify({topic,format_id})});
      notice("Run queued: "+result.run_id+" · Status: "+result.status);
      await loadRuns();
    }catch(error){notice(error.message,true);}finally{$("factoryStart").disabled=false;}
  }
  async function loadHealth() {
    const root=$("factoryHealth");root.textContent="Checking…";
    try{const data=await api("/api/production-factory/health");root.replaceChildren();
      const brain=document.createElement("p");brain.textContent="Master AI: "+data.master_brain.selected+" · Local model: "+(data.master_brain.local.model_available?"available":"not available")+" · Service: "+(data.master_brain.local.service_running?"running":"stopped");root.append(brain);
      for(const [name,item] of Object.entries(data.engines)){
        const row=document.createElement("p");row.className="factory-meta";
        const localReady=Boolean(item.local_available);
        const readiness=name==="image"
          ? (item.comfyui_available?"LOCAL AI READY":(localReady?"PROCEDURAL FALLBACK ONLY":"NOT READY"))
          : (localReady?"LOCAL READY":"NOT READY");
        row.textContent=name+": "+readiness+" · "+(item.engine||"No local engine")+
          (item.available && !localReady?" · optional remote provider configured, not used for free local rendering":"");
        row.dataset.localReady=String(localReady);root.append(row);
      }
      const renderNote=document.createElement("p");renderNote.className="factory-meta";
      renderNote.textContent="Final MP4 generation uses local engines only. Remote provider configuration does not count as local readiness; paid fallback is disabled.";
      root.append(renderNote);
      const worker=document.createElement("p");worker.textContent="Background worker: "+(data.background_worker?.running?"running":"not running")+" · Queue pickup: "+(data.background_worker?.auto_pickup_status||"unknown")+" · Paused jobs need Owner review";root.append(worker);
      const policy=document.createElement("p");policy.textContent="Paid auto-activation: OFF · Publishing: OFF";root.append(policy);
      const note=document.createElement("p");note.className="factory-meta";note.textContent=data.notice;root.append(note);
    }catch(error){root.textContent=error.message;root.className="factory-error";}
  }
  async function loadRuns() {
    const root=$("factoryRuns");root.textContent="Loading…";
    try{const data=await api("/api/production-factory/runs?limit=20");state.runs=data.runs||[];root.replaceChildren();
      const summary=document.createElement("p");summary.className="factory-meta";
      summary.textContent="Active: "+data.summary.active+" · Needs attention: "+data.summary.needs_attention+" · Returned: "+data.summary.returned;root.append(summary);
      if(!state.runs.length){const empty=document.createElement("p");empty.textContent="Abhi koi production run nahi hai.";root.append(empty);return;}
      for(const run of state.runs){const card=document.createElement("article");card.className="factory-run";
        const title=document.createElement("b");title.textContent=run.topic+" · "+run.status;card.append(title);
        const detail=document.createElement("p");detail.className="factory-meta";detail.textContent=run.format_id+" · "+run.run_id+" · Attempts: "+run.attempt_count+" · Steps: "+run.step_count;card.append(detail);
        const open=document.createElement("button");open.type="button";open.className="secondary";open.textContent="View run details";
        open.addEventListener("click",()=>viewRun(run.run_id));card.append(open);
        if(run.status==="completed" && run.has_render && run.video_url){
          const rendered=document.createElement("a");rendered.href=run.video_url;rendered.target="_blank";rendered.rel="noopener";rendered.textContent="Open verified MP4";card.append(rendered);
        }else if(run.status==="completed"){
          const render=document.createElement("button");render.type="button";render.className="primary";render.textContent="Generate final MP4";
          render.addEventListener("click",()=>produceMedia(run.run_id));card.append(render);
        }
        if(!["completed","failed","cancelled"].includes(run.status)){
          const cancel=document.createElement("button");cancel.type="button";cancel.className="secondary";cancel.textContent="Cancel run";
          cancel.addEventListener("click",()=>cancelRun(run.run_id));card.append(cancel);
        }
        root.append(card);}
    }catch(error){root.textContent=error.message;root.className="factory-error";}
  }
  async function cancelRun(id) {
    if(!window.confirm("Is production run ko cancel karein? Completed partial outputs preserve rahenge.")) return;
    notice("Cancellation request bhej rahe hain…");
    try{
      const result=await api("/api/production/runs/"+encodeURIComponent(id)+"/cancel",{method:"POST"});
      notice(result.detail||("Run status: "+result.status));
      await loadRuns();
    }catch(error){notice(error.message,true);}
  }
  async function produceMedia(id) {
    if(!window.confirm("Approved production package se local images, Hindi voice, original background music aur verified MP4 generate karein? Ismein sirf configured free local engines use honge; YouTube par publish nahi hoga.")) return;
    notice("Local media generation shuru… ComfyUI, Hindi Piper voice aur FFmpeg available hone chahiye.");
    const buttons=[...$("factoryRuns").querySelectorAll("button")];
    const button=buttons.find(item=>item.textContent==="Generate final MP4" && item.parentElement?.textContent.includes(id));
    if(button){button.disabled=true;button.textContent="Generating…";}
    try{
      const result=await api("/api/production/runs/"+encodeURIComponent(id)+"/produce-media",{
        method:"POST",
        body:JSON.stringify({burn_subtitles:false,sound_effects_enabled:true,quality:"high",fps:30})
      });
      notice(result.detail||"Verified MP4 ready. Publishing remains disabled.");
      await loadRuns();
      if(result.render?.url || result.render?.video_id){
        const link=document.createElement("a");link.href=result.render.url||("/api/videos/"+encodeURIComponent(result.render.video_id));
        link.textContent="Open rendered video";link.target="_blank";link.rel="noopener";
        $("factoryNotice").append(document.createTextNode(" "),link);
      }
      if(result.delivery_package_url && result.delivery_package?.verified === true){
        const packageLink=document.createElement("a");packageLink.href=result.delivery_package_url;
        packageLink.textContent="Download verified production ZIP";packageLink.rel="noopener";
        $("factoryNotice").append(document.createTextNode(" · "),packageLink);
      }
    }catch(error){notice(error.message,true);if(button){button.disabled=false;button.textContent="Generate final MP4";}}
  }
  async function viewRun(id) {
    try{
      const [run, timeline]=await Promise.all([
        api("/api/production/runs/"+encodeURIComponent(id)),
        api("/api/production/runs/"+encodeURIComponent(id)+"/events")
      ]);
      const card=[...$("factoryRuns").querySelectorAll(".factory-run")].find(node=>node.textContent.includes(id));
      if(!card) return;
      let panel=card.querySelector(".factory-run-details");
      if(panel){panel.remove();return;}
      panel=document.createElement("section");panel.className="factory-run-details factory-stage";
      const heading=document.createElement("h3");heading.textContent="Run execution details · "+run.status;panel.append(heading);
      const current=document.createElement("p");current.className="factory-meta";current.textContent="Current role: "+(run.current_role||"—")+" · Attempts: "+(run.attempt_count||0);panel.append(current);
      const pipelineTitle=document.createElement("b");pipelineTitle.textContent="21-stage pipeline ledger";panel.append(pipelineTitle);
      const pipelineNote=document.createElement("p");pipelineNote.className="factory-meta";
      pipelineNote.textContent="Mapped specialist/checker roles advance applicable stages through quality. The authenticated Owner's confirmed Generate final MP4 action records Owner Review approval and advances verified render/package stages; publishing, analytics and learning still need separate executors.";
      panel.append(pipelineNote);
      const renderedResult=run.result?.render||{};
      const packageInfo=renderedResult.delivery_package;
      if(packageInfo?.verified===true){
        const packageTitle=document.createElement("b");packageTitle.textContent="Verified production delivery";panel.append(packageTitle);
        const packageNote=document.createElement("p");packageNote.className="factory-meta";
        packageNote.textContent=packageInfo.filename+" · "+packageInfo.file_count+" files · "+packageInfo.size_bytes+" bytes · SHA-256 "+packageInfo.sha256;
        panel.append(packageNote);
        const packageLink=document.createElement("a");packageLink.href="/api/production/runs/"+encodeURIComponent(id)+"/package";
        packageLink.textContent="Download Owner-only production ZIP";packageLink.rel="noopener";panel.append(packageLink);
        const packageLimits=document.createElement("p");packageLimits.className="factory-meta";
        packageLimits.textContent="Hindi captions included: "+(packageInfo.captions_included?"yes":"no")+
          " · Editable timeline project: "+(packageInfo.editable_project_included?"included":"not exported")+
          " · Rights certificates: "+(packageInfo.rights_certificates_included?"included":"not supplied");
        panel.append(packageLimits);
      }
      const dispatch=run.result?.pipeline_dispatch||{};
      const deferredRoles=Array.isArray(dispatch.deferred_worker_roles)?dispatch.deferred_worker_roles:[];
      const deferredTitle=document.createElement("b");deferredTitle.textContent="Deferred side-effect roles";panel.append(deferredTitle);
      const deferredNote=document.createElement("p");deferredNote.className="factory-meta";
      deferredNote.textContent=deferredRoles.length
        ? deferredRoles.join(" · ")+" — role prompts may produce text-only plans/checklists; no actual render, package, upload, scheduling or analytics action is performed."
        : "No deferred specialist roles recorded for this run.";
      panel.append(deferredNote);
      const deferredStages=Array.isArray(dispatch.deferred_stage_ids)?dispatch.deferred_stage_ids:[];
      const deferredStageNote=document.createElement("p");deferredStageNote.className="factory-meta";
      deferredStageNote.textContent="Deferred stages: "+(deferredStages.join(" · ")||"none reported");
      panel.append(deferredStageNote);
      for(const stage of run.pipeline_stages||[]){
        const row=document.createElement("p");row.className="factory-meta";
        row.textContent=stage.sequence+" · "+stage.stage_id+" · "+stage.department+" · "+stage.status+
          (stage.approval==="owner_required"?" · Owner approval required":"");
        panel.append(row);
      }
      const stepsTitle=document.createElement("b");stepsTitle.textContent="Specialist and checker steps";panel.append(stepsTitle);
      for(const step of run.steps||[]){
        const row=document.createElement("p");row.className="factory-meta";
        row.textContent=(step.sequence??"")+" · "+step.role+" · "+step.step_type+" · "+step.status+" · Attempts: "+(step.attempts||0);
        panel.append(row);
      }
      const eventsTitle=document.createElement("b");eventsTitle.textContent="Run event timeline";panel.append(eventsTitle);
      const events=timeline.events||[];
      if(!events.length){const empty=document.createElement("p");empty.textContent="No lifecycle events recorded yet.";panel.append(empty);}
      for(const event of events){
        const row=document.createElement("p");row.className="factory-meta";
        row.textContent=event.created_at+" · "+event.event_type+" · "+(event.from_status||"start")+" → "+event.to_status;
        panel.append(row);
      }
      card.append(panel);
    }catch(error){notice(error.message,true);}
  }
  $("factoryPlan").addEventListener("click",buildPlan);
  $("factoryStart").addEventListener("click",startRun);
  $("factoryRefreshHealth").addEventListener("click",loadHealth);
  $("factoryRefreshRuns").addEventListener("click",loadRuns);
  $("factoryLogout").addEventListener("click",async()=>{try{await fetch("/api/auth/logout",{method:"POST",credentials:"same-origin"});}finally{location.replace("/login");}});
  loadFormats().catch(error=>notice(error.message,true));
  loadHealth();loadRuns();
  window.setInterval(loadRuns,20000);
})();