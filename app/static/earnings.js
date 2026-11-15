const el=id=>document.getElementById(id), money=(n,c)=>new Intl.NumberFormat("en-IN",{style:"currency",currency:c,maximumFractionDigits:2}).format(n||0);
const today=new Date();el("record_date").value=today.toISOString().slice(0,10);el("targetMonth").value=today.toISOString().slice(0,7);
let editingRecordId=null;let recordOffset=0;const recordPageSize=50;let recordTotal=0;
async function request(url,opts={}){const r=await fetch(url,{credentials:"same-origin",...opts,headers:{"Content-Type":"application/json",...(opts.headers||{})}});const d=await r.json().catch(()=>({}));if(!r.ok)throw Error(d.detail||"Request failed");return d}
function renderDailyAnalytics(rows){
 const daily=Array.isArray(rows)?rows:[];
 if(!daily.length){el("youtubeAnalyticsDailyChart").textContent="इस तारीख़ सीमा में दैनिक आँकड़े उपलब्ध नहीं हैं।";return;}
 const maxViews=Math.max(1,...daily.map(x=>Number(x.views)||0));
 const maxWatch=Math.max(1,...daily.map(x=>Number(x.watch_minutes)||0));
 const bars=daily.map(x=>{
  const date=escapeHtml(String(x.date||""));
  const views=Math.max(0,Number(x.views)||0),watch=Math.max(0,Number(x.watch_minutes)||0);
  const vw=Math.min(100,views/maxViews*100),ww=Math.min(100,watch/maxWatch*100);
  return '<div class="card" style="padding:10px;margin:8px 0"><div style="display:flex;justify-content:space-between;gap:8px"><b>'+date+'</b><span>'+views.toLocaleString("en-IN")+' views</span></div><div style="height:7px;background:#263650;border-radius:8px;margin:7px 0 10px;overflow:hidden"><div style="height:100%;width:'+vw.toFixed(2)+'%;background:#38bdf8;border-radius:8px"></div></div><div style="display:flex;justify-content:space-between;gap:8px"><span class="muted">Watch time</span><span>'+watch.toLocaleString("en-IN")+' मिनट</span></div><div style="height:7px;background:#263650;border-radius:8px;margin:7px 0;overflow:hidden"><div style="height:100%;width:'+ww.toFixed(2)+'%;background:#8b7cff;border-radius:8px"></div></div></div>';
 }).join("");
 el("youtubeAnalyticsDailyChart").innerHTML='<h3>दैनिक प्रदर्शन · Views और Watch Time</h3><p class="notice">हर बार की लंबाई उसी metric के date range के अधिकतम दिन के अनुपात में है।</p>'+bars;
}
async function renderYouTubeAnalytics(data){
 const t=data.totals||{}, r=data.revenue||{};
 const cards=[["Views",Number(t.views||0).toLocaleString("en-IN")],["Watch time",Number(t.estimatedMinutesWatched||0).toLocaleString("en-IN")+" मिनट"],["Subscribers gained",Number(t.subscribersGained||0).toLocaleString("en-IN")],["Subscribers lost",Number(t.subscribersLost||0).toLocaleString("en-IN")],["Net subscribers",(Number(t.subscribersGained||0)-Number(t.subscribersLost||0)).toLocaleString("en-IN")],["औसत view duration",Math.round(Number(t.averageViewDuration||0))+" सेकंड"]];
 el("youtubeAnalyticsMetrics").innerHTML=cards.map(([k,v])=>'<article class="card"><div class="muted">'+escapeHtml(k)+'</div><div class="metric">'+escapeHtml(v)+'</div></article>').join("");
 renderDailyAnalytics(data.daily);
 el("youtubeAnalyticsRevenue").textContent=r.available?"YouTube अनुमानित कमाई: "+money(r.estimated_revenue||0,r.currency||"INR")+" · यह अनुमान है, प्राप्त भुगतान नहीं। "+(r.note||""):("YouTube कमाई उपलब्ध नहीं: "+(r.note||"Monetization permission आवश्यक है।"));
 const comparison=el("youtubeAnalyticsRevenueComparison");
 if(r.available){
  try{
   const ledger=await request("/api/earnings/records?kind=income&limit=500");
   const received=(ledger.records||[]).filter(x=>x.source==="youtube_ads"&&x.status==="received"&&x.currency==="INR"&&x.record_date>=data.start_date&&x.record_date<=data.end_date).reduce((sum,x)=>sum+Number(x.amount||0),0);
   const estimated=Number(r.estimated_revenue||0);
   comparison.innerHTML='<h3>अनुमान बनाम दर्ज प्राप्त भुगतान</h3><div class="grid"><article class="card"><div class="muted">YouTube अनुमान (INR)</div><div class="metric">'+money(estimated,"INR")+'</div></article><article class="card"><div class="muted">Ledger में दर्ज प्राप्त YouTube Ads रकम (INR)</div><div class="metric">'+money(received,"INR")+'</div></article><article class="card"><div class="muted">अंतर · अनुमान − दर्ज रकम</div><div class="metric">'+money(estimated-received,"INR")+'</div></article></div><p class="notice">प्राप्त रकम केवल आपके द्वारा Ledger में दर्ज YouTube Ads रिकॉर्ड से ली गई है। यह बैंक/AdSense से स्वतः सत्यापित भुगतान नहीं है; रिकॉर्ड date range और INR तक सीमित हैं।</p>';
  }catch(err){comparison.textContent="प्राप्त भुगतान की तुलना के लिए Ledger डेटा उपलब्ध नहीं: "+err.message;}
 }else{comparison.textContent="Revenue API अनुमान उपलब्ध होने पर ही Ledger तुलना दिखाई जाएगी।";}
 const videos=data.top_videos||[];
 el("youtubeAnalyticsVideos").innerHTML=videos.length?'<h3>Top videos</h3>'+videos.map(v=>'<div class="record"><a href="'+escapeHtml(v.url)+'" target="_blank" rel="noopener noreferrer">'+escapeHtml(v.video_id)+'</a><span>'+Number(v.views||0).toLocaleString("en-IN")+' views</span></div>').join(""):"";
}
async function loadYouTubeAnalytics(){
 const button=el("youtubeAnalyticsLoad"),status=el("youtubeAnalyticsStatus");
 button.disabled=true;status.textContent="YouTube Analytics डेटा प्राप्त हो रहा है…";
 try{
  const params=new URLSearchParams();
  if(el("youtubeStartDate").value)params.set("start_date",el("youtubeStartDate").value);
  if(el("youtubeEndDate").value)params.set("end_date",el("youtubeEndDate").value);
  const data=await request("/api/admin/youtube/analytics"+(params.size?"?"+params.toString():""));
  await renderYouTubeAnalytics(data);
  status.textContent=(data.channel||"Connected channel")+" · "+data.start_date+" से "+data.end_date+" · "+(data.note||"Official YouTube data");
 }catch(err){status.textContent=err.message+" · YouTube channel connection और Analytics permission जाँचें।";}
 finally{button.disabled=false;}
}
async function refresh(){const month=el("targetMonth").value||today.toISOString().slice(0,7);const query=new URLSearchParams({month,limit:String(recordPageSize),offset:String(recordOffset)});for(const [key,id] of [["kind","recordKindFilter"],["status","recordStatusFilter"],["source","recordSourceFilter"],["start_date","recordStartDate"],["end_date","recordEndDate"]]){const value=el(id).value;if(value)query.set(key,value);}const [s,r]=await Promise.all([request("/api/earnings/summary?month="+encodeURIComponent(month)),request("/api/earnings/records?"+query.toString())]);const cards=[["Confirmed income",s.confirmed_income],["Received",s.received_income],["Estimated",s.estimated_income],["Pending",s.pending_income],["Expenses",s.expenses],["Net confirmed",s.net_confirmed]];el("metrics").innerHTML=cards.map(([label,values])=>'<article class="card"><div class="muted">'+label+'</div><div class="metric">'+(Object.keys(values||{}).length?Object.entries(values).map(([c,v])=>money(v,c)).join("<br>"):"—")+'</div></article>').join("");if(s.target){el("targetNotice").textContent="Target "+money(s.target.target_amount,s.target.currency)+" · Progress "+s.target_progress_percent+"%";}else{el("targetNotice").textContent="इस महीने के लिए अभी कोई लक्ष्य सेट नहीं है।";}recordTotal=Number(r.total||0);el("recordPageInfo").textContent=recordTotal?(recordOffset+1)+"–"+(recordOffset+(r.records||[]).length)+" / "+recordTotal+" रिकॉर्ड":"कोई रिकॉर्ड नहीं";el("recordPrevPage").disabled=recordOffset<=0;el("recordNextPage").disabled=!r.has_more;renderRecords(r.records||[]);}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function renderRecords(rows){el("recordList").innerHTML=rows.length?rows.map(x=>'<div class="record"><div><b>'+escapeHtml(x.title)+'</b><div class="muted">'+escapeHtml(x.record_date)+' · '+escapeHtml(x.source)+' · '+escapeHtml(x.status)+'</div></div><div class="record-actions"><b class="'+(x.kind==="income"?"positive":"")+'">'+(x.kind==="expense"?"−":"+")+money(x.amount,x.currency)+'</b><button type="button" class="secondary" data-edit-id="'+Number(x.id)+'">Edit</button><button type="button" class="secondary" data-delete-id="'+Number(x.id)+'">Delete</button></div></div>').join(""):'अभी कोई रिकॉर्ड नहीं है।';}
function resetRecordForm(){editingRecordId=null;el("recordForm").reset();el("record_date").value=today.toISOString().slice(0,10);el("recordSubmit").textContent="रिकॉर्ड सेव करें";el("cancelEdit").hidden=true;el("formNotice").textContent="";}
el("recordForm").addEventListener("submit",async e=>{e.preventDefault();const payload={kind:el("kind").value,source:el("source").value,title:el("title").value,amount:Number(el("amount").value),currency:el("currency").value,status:el("status").value,record_date:el("record_date").value,reference:el("reference").value,notes:el("notes").value};try{await request(editingRecordId?"/api/earnings/records/"+editingRecordId:"/api/earnings/records",{method:editingRecordId?"PATCH":"POST",body:JSON.stringify(payload)});el("formNotice").textContent=editingRecordId?"Record updated.":"Record saved.";resetRecordForm();recordOffset=0;await refresh();}catch(err){el("formNotice").textContent=err.message;}});
el("cancelEdit").addEventListener("click",resetRecordForm);
el("recordList").addEventListener("click",async e=>{const edit=e.target.closest("[data-edit-id]");const del=e.target.closest("[data-delete-id]");if(edit){try{const id=Number(edit.dataset.editId);const data=await request("/api/earnings/records/"+id);const row=data.record;if(!row)throw Error("Record not found. Refresh and try again.");editingRecordId=id;for(const key of ["kind","source","title","amount","currency","status","record_date","reference","notes"])el(key).value=row[key]??"";el("recordSubmit").textContent="बदलाव सेव करें";el("cancelEdit").hidden=false;el("formNotice").textContent="Record editing mode.";el("recordForm").scrollIntoView({behavior:"smooth",block:"start"});}catch(err){el("formNotice").textContent=err.message;}}else if(del){const id=Number(del.dataset.deleteId);if(!Number.isSafeInteger(id)||id<=0)return;if(!confirm("इस रिकॉर्ड को स्थायी रूप से हटाएँ?"))return;try{await request("/api/earnings/records/"+id,{method:"DELETE"});if(editingRecordId===id)resetRecordForm();el("formNotice").textContent="Record deleted.";recordOffset=0;await refresh();}catch(err){el("formNotice").textContent=err.message;}}});
el("targetForm").addEventListener("submit",async e=>{e.preventDefault();try{await request("/api/earnings/target",{method:"PUT",body:JSON.stringify({month:el("targetMonth").value,target_amount:Number(el("targetAmount").value),currency:el("targetCurrency").value})});el("targetNotice").textContent="Monthly target saved.";await refresh();}catch(err){el("targetNotice").textContent=err.message;}});
for(const id of ["recordKindFilter","recordStatusFilter","recordSourceFilter","recordStartDate","recordEndDate","targetMonth"])el(id).addEventListener("change",()=>{recordOffset=0;refresh().catch(e=>el("recordList").textContent=e.message);});el("recordPrevPage").addEventListener("click",()=>{recordOffset=Math.max(0,recordOffset-recordPageSize);refresh().catch(e=>el("recordList").textContent=e.message);});el("recordNextPage").addEventListener("click",()=>{if(recordOffset+recordPageSize<recordTotal){recordOffset+=recordPageSize;refresh().catch(e=>el("recordList").textContent=e.message);}});el("youtubeAnalyticsLoad").addEventListener("click",loadYouTubeAnalytics);refresh().catch(e=>{el("recordList").textContent=e.message;});
