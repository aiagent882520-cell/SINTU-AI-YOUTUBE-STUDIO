const $ = (id) => document.getElementById(id);
async function request(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Request failed");
  return data;
}
async function refresh() {
  try {
    const [status,agents,tasks,providers] = await Promise.all([
      request("/api/status"), request("/api/agents"), request("/api/tasks"), request("/api/providers")
    ]);
    $("health").textContent = "API online";
    $("agentCount").textContent = agents.total;
    $("taskCount").textContent = status.tasks_saved;
    const available = [];
    if (providers.openai.configured) available.push("OpenAI");
    if (providers.gemini.configured) available.push("Gemini");
    $("providerStatus").textContent = available.length
      ? "Configured: " + available.join(" + ") + " · selected: " + providers.selected
      : "No API key configured — server setup required";
    $("agents").innerHTML = agents.agents.map(a =>
      '<div class="agent"><span>'+a.id+'. '+escapeHtml(a.name)+'</span><small>'+a.status+'</small></div>'
    ).join("");
    $("tasks").innerHTML = tasks.tasks.length ? tasks.tasks.map(t =>
      '<div class="task"><b>#'+t.id+' · '+escapeHtml(t.workflow)+'</b> · '+escapeHtml(t.status)+
      '<small>'+escapeHtml(t.prompt)+'</small></div>'
    ).join("") : "No tasks yet.";
  } catch (error) { $("health").textContent = "API unavailable"; }
}
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
$("submit").addEventListener("click", async () => {
  const prompt = $("prompt").value.trim();
  if (!prompt) { $("notice").textContent = "Pehle apna topic ya prompt likhein."; return; }
  $("submit").disabled = true;
  $("result").hidden = true;
  $("notice").textContent = "AI se response manga ja raha hai…";
  try {
    const result = await request("/api/generate", {
      method:"POST",
      body:JSON.stringify({prompt,workflow:$("workflow").value})
    });
    $("notice").textContent = "Task #"+result.id+" · "+result.provider+" · "+result.model+" · Completed";
    $("result").textContent = result.output;
    $("result").hidden = false;
    $("prompt").value = "";
    await refresh();
  } catch (error) {
    $("notice").textContent = error.message;
    await refresh();
  } finally { $("submit").disabled = false; }
});
$("prompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) $("submit").click();
});
refresh();
