const $ = (id) => document.getElementById(id);
let latestTaskId = null;
async function request(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
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
$("download").addEventListener("click", async () => {
  if (!latestTaskId) return;
  window.location.href = "/api/export/" + latestTaskId;
});
$("prompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) generate();
});
document.querySelectorAll("[data-workflow]").forEach(button => button.addEventListener("click", () => {
  $("workflow").value = button.dataset.workflow;
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
