const $ = (id) => document.getElementById(id);
async function request(path, options={}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  if (!response.ok) throw new Error((await response.json()).detail || "Request failed");
  return response.json();
}
async function refresh() {
  try {
    const [health,status,agents,tasks] = await Promise.all([
      request("/api/health"), request("/api/status"), request("/api/agents"), request("/api/tasks")
    ]);
    $("health").textContent = "API online";
    $("agentCount").textContent = agents.total;
    $("taskCount").textContent = status.tasks_saved;
    $("agents").innerHTML = agents.agents.map(a => 
      '<div class="agent"><span>'+a.id+'. '+escapeHtml(a.name)+'</span><small>'+a.status+'</small></div>'
    ).join("");
    $("tasks").innerHTML = tasks.tasks.length ? tasks.tasks.map(t =>
      '<div class="task">'+escapeHtml(t.prompt)+'<small>'+escapeHtml(t.workflow)+' · '+t.status+' · '+escapeHtml(t.created_at)+'</small></div>'
    ).join("") : "No tasks yet.";
  } catch (error) { $("health").textContent = "API unavailable"; }
}
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
$("submit").addEventListener("click", async () => {
  const prompt = $("prompt").value.trim();
  if (!prompt) { $("notice").textContent = "Pehle apna topic ya prompt likhein."; return; }
  $("submit").disabled = true;
  $("notice").textContent = "Saving…";
  try {
    const result = await request("/api/tasks", {method:"POST", body:JSON.stringify({prompt,workflow:$("workflow").value})});
    $("notice").textContent = "Task #"+result.id+" saved. AI generation abhi configure nahi hai.";
    $("prompt").value = "";
    await refresh();
  } catch (error) { $("notice").textContent = error.message; }
  finally { $("submit").disabled = false; }
});
$("prompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) $("submit").click();
});
refresh();
