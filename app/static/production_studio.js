/* SINTU Production Studio: format browser, presets and local project drafts.
   Drafts stay in this browser until a server-side project sync is configured. */
(() => {
 const root=document.getElementById("productionStudio");
 if(!root)return;
 const state={catalog:null,format:"youtube-shorts",preset:"mystery-short",drafts:[]};
 const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const storeKey="sintu.production.drafts.v1";
 function readDrafts(){try{state.drafts=JSON.parse(localStorage.getItem(storeKey)||"[]");if(!Array.isArray(state.drafts))state.drafts=[];}catch{state.drafts=[];}}
 function saveDrafts(){localStorage.setItem(storeKey,JSON.stringify(state.drafts.slice(0,100)));renderDrafts();}
 function selectedFormat(){return state.catalog.formats.find(x=>x.id===state.format)||state.catalog.formats[0];}
 function renderFormats(){
  const q=(document.getElementById("formatSearch")?.value||"").toLowerCase();
  const cat=document.getElementById("formatCategory")?.value||"";
  const items=state.catalog.formats.filter(x=>(!cat||x.category===cat)&&(!q||(x.name+" "+x.description).toLowerCase().includes(q)));
  document.getElementById("formatCards").innerHTML=items.map(x=>'<button type="button" class="format-card '+(x.id===state.format?"selected":"")+'" data-format="'+esc(x.id)+'"><b>'+esc(x.name)+'</b><span>'+esc(x.category)+' · '+esc(x.aspect_ratio)+'</span><small>'+esc(x.description)+'</small><em>'+esc(x.stage.replaceAll("_"," "))+'</em></button>').join("")||'<p class="muted">Koi format nahi mila.</p>';
  document.getElementById("formatDetail").textContent=selectedFormat().name+" · "+selectedFormat().recommended_resolution+" · "+selectedFormat().duration;
 }
 function renderPipeline(){document.getElementById("pipelineCards").innerHTML=state.catalog.pipeline.map((x,i)=>'<div class="pipeline-step"><b>'+String(i+1).padStart(2,"0")+' · '+esc(x.name)+'</b><span>'+esc(x.description)+'</span></div>').join("");}
 function renderDrafts(){const el=document.getElementById("localDrafts");if(!el)return;el.innerHTML=state.drafts.length?state.drafts.map((d,i)=>'<article class="local-draft"><b>'+esc(d.name)+'</b><small>'+esc(d.formatName)+' · '+new Date(d.updatedAt).toLocaleString()+'</small><p>'+esc(d.topic)+'</p><div class="actions"><button type="button" class="secondary" data-open="'+i+'">Open</button><button type="button" class="secondary" data-delete="'+i+'">Delete</button></div></article>').join(""):'<p class="muted">Abhi koi local draft nahi hai.</p>';}
 function applyPreset(id){const p=state.catalog.presets.find(x=>x.id===id);if(!p)return;state.preset=id;state.format=p.format;document.getElementById("projectName").value=p.name;document.getElementById("projectTopic").value=p.prompt;document.getElementById("projectLanguage").value=p.language;document.getElementById("projectDuration").value=p.duration_seconds;renderFormats();document.getElementById("presetSelect").value=id;}
 function init(){
  document.getElementById("formatCards").addEventListener("click",e=>{const b=e.target.closest("[data-format]");if(b){state.format=b.dataset.format;renderFormats();}});
  document.getElementById("formatSearch").addEventListener("input",renderFormats);
  document.getElementById("formatCategory").addEventListener("change",renderFormats);
  document.getElementById("presetSelect").addEventListener("change",e=>applyPreset(e.target.value));
  document.getElementById("saveProjectDraft").addEventListener("click",()=>{const topic=document.getElementById("projectTopic").value.trim();if(!topic){alert("Pehle topic ya brief likhein.");return;}const d={id:crypto.randomUUID(),name:document.getElementById("projectName").value.trim()||"Untitled Project",topic,format:state.format,formatName:selectedFormat().name,language:document.getElementById("projectLanguage").value.trim()||"Hindi",duration:Number(document.getElementById("projectDuration").value)||60,updatedAt:new Date().toISOString(),status:"Brief ready"};state.drafts.unshift(d);saveDrafts();document.getElementById("draftNotice").textContent="Project brief is browser mein save ho gaya. AI APIs baad mein connect ki ja sakti hain.";});
  document.getElementById("exportProjectBrief").addEventListener("click",()=>{const d={name:document.getElementById("projectName").value,topic:document.getElementById("projectTopic").value,format:selectedFormat(),language:document.getElementById("projectLanguage").value,duration:Number(document.getElementById("projectDuration").value),pipeline:state.catalog.pipeline};const blob=new Blob([JSON.stringify(d,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="sintu-project-brief.json";a.click();URL.revokeObjectURL(a.href);});
  document.getElementById("localDrafts").addEventListener("click",e=>{const o=e.target.closest("[data-open]"),del=e.target.closest("[data-delete]");if(o){const d=state.drafts[Number(o.dataset.open)];if(d){document.getElementById("projectName").value=d.name;document.getElementById("projectTopic").value=d.topic;document.getElementById("projectLanguage").value=d.language;document.getElementById("projectDuration").value=d.duration;state.format=d.format;renderFormats();}}if(del){state.drafts.splice(Number(del.dataset.delete),1);saveDrafts();}});
  readDrafts();renderDrafts();renderPipeline();renderFormats();
 }
 fetch("/api/production-catalog").then(r=>{if(!r.ok)throw new Error("catalog unavailable");return r.json();}).then(data=>{state.catalog=data;init();}).catch(()=>{root.querySelector("#catalogNotice").textContent="Production catalog load nahi ho paya. Page refresh karein.";});
})();
