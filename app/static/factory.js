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
    const heading=document.createElement("h3"); heading.textContent="11-stage factory plan"; root.append(heading);
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
      for(const [name,item] of Object.entries(data.engines)){const row=document.createElement("p");row.textContent=name+": "+(item.available?"available":"not available")+" · "+(item.engine||"No local engine");root.append(row);}
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
        if(run.status==="completed"){
          const render=document.createElement("button");render.type="button";render.className="primary";render.textContent="Generate final MP4";
          render.addEventListener("click",()=>produceMedia(run.run_id));card.append(render);
        }
        root.append(card);}
    }catch(error){root.textContent=error.message;root.className="factory-error";}
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
      if(result.render?.filename){
        const link=document.createElement("a");link.href="/api/videos/"+encodeURIComponent(result.render.filename);
        link.textContent="Open rendered video: "+result.render.filename;link.target="_blank";link.rel="noopener";
        $("factoryNotice").append(document.createTextNode(" "),link);
      }
    }catch(error){notice(error.message,true);if(button){button.disabled=false;button.textContent="Generate final MP4";}}
  }
  async function viewRun(id) {
    try{const run=await api("/api/production/runs/"+encodeURIComponent(id));const details=(run.steps||[]).map(x=>x.role+": "+x.status).join("\n");
      window.alert("Run "+id+"\nStatus: "+run.status+"\nCurrent role: "+(run.current_role||"—")+"\n\n"+details);}
    catch(error){notice(error.message,true);}
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