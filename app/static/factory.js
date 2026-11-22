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