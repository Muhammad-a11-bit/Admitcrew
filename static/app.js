const API = "";
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const staffKey = () => sessionStorage.getItem("admitcrew_staff_key") || "";
let allPrograms = [], allLeads = [], toastTimer;
const countries = ["UK", "Canada", "Germany", "Australia"];

async function request(path, options={}) {
  const headers = new Headers(options.headers || {});
  if (staffKey()) headers.set("X-Staff-Key", staffKey());
  if (options.json !== undefined) { headers.set("Content-Type", "application/json"); options.body = JSON.stringify(options.json); delete options.json; }
  const response = await fetch(API + path, {...options, headers});
  const text = await response.text();
  let data; try { data = text ? JSON.parse(text) : {}; } catch { data = {detail:text}; }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}
function toast(message) { const el=$("#toast"); el.textContent=message; el.classList.add("show"); clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.classList.remove("show"),3000); }
function setFeedback(el, message, error=false) { if(!el)return; el.textContent=message||""; el.classList.toggle("error",!!error); }
function esc(v="") { return String(v).replace(/[&<>"']/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function statusClass(s="") { return String(s).toLowerCase().replace(/[^a-z_]/g,""); }
function niceDate(value) { if(!value)return "—"; const d=new Date(value); return Number.isNaN(d.getTime())?esc(value):d.toLocaleDateString(undefined,{day:"numeric",month:"short",year:"numeric"}); }
function shortWhen(value) { if(!value)return "No activity"; const d=new Date(value); if(Number.isNaN(d.getTime()))return "—"; const days=Math.floor((Date.now()-d.getTime())/86400000); return days===0?"Today":days===1?"1 day ago":`${days} days ago`; }
function showStudent() { $("#staffView").classList.add("hidden"); $("#studentView").classList.remove("hidden"); window.scrollTo({top:0,behavior:"smooth"}); }
function showStaff() { $("#studentView").classList.add("hidden"); $("#staffView").classList.remove("hidden"); window.scrollTo({top:0,behavior:"smooth"}); if(staffKey()) loadStaff(); }

async function loadPrograms() {
  const grid=$("#programGrid"); grid.innerHTML='<div class="loading">Loading programs…</div>';
  try { allPrograms=await request("/api/public/programs"); populateCountries(); renderProgramCards(); }
  catch(e) { grid.innerHTML=`<div class="empty-state">Could not load programs. Check that the AdmitCrew backend is running at this address.<br><small>${esc(e.message)}</small></div>`; }
}
function populateCountries() {
  const seen=[...new Set(allPrograms.map(p=>p.country).filter(Boolean))].sort();
  const filters=[$("#countryFilter"),$("#chatForm select[name=country]")];
  filters.forEach((select,i)=>{if(!select)return; const first=i===0?'<option value="">All destinations</option>':'<option value="">Choose a destination</option>'; select.innerHTML=first+seen.map(c=>`<option>${esc(c)}</option>`).join("");});
  $("#programCount").textContent=String(allPrograms.length).padStart(2,"0");
}
function renderProgramCards() {
  const q=$("#programSearch").value.trim().toLowerCase(), country=$("#countryFilter").value;
  const rows=allPrograms.filter(p=>(!country||p.country===country)&&(!q||`${p.university} ${p.program} ${p.country}`.toLowerCase().includes(q)));
  $("#programResults").textContent=`${rows.length} program${rows.length===1?"":"s"}`;
  $("#programGrid").innerHTML=rows.length?rows.map(p=>`<article class="program-card"><div class="program-card-top"><span class="country-tag">${esc(p.country)}</span>${(p.source_note||"").includes("Practice sample")?'<span class="practice-tag">Practice sample</span>':''}</div><h3>${esc(p.university)}</h3><div class="program-name">${esc(p.program)}</div><div class="program-facts"><div><span class="fact-label">ANNUAL FEE</span><span class="fact-value">${esc(p.annual_fee)}</span></div><div><span class="fact-label">DEADLINE</span><span class="fact-value">${esc(p.deadline)}</span></div><div><span class="fact-label">MIN. MARKS</span><span class="fact-value">${esc(p.min_marks)}</span></div><div><span class="fact-label">MIN. IELTS</span><span class="fact-value">${esc(p.min_ielts)}</span></div></div><div class="card-foot"><span>${(p.documents||[]).length} required documents</span><button data-program-details="${p.id}">View requirements ↗</button></div></article>`).join(""):'<div class="empty-state">No programs match that search. Try another destination or keyword.</div>';
}

$("#programSearch").addEventListener("input",renderProgramCards);
$("#countryFilter").addEventListener("change",renderProgramCards);
$("#programGrid").addEventListener("click",e=>{const b=e.target.closest("[data-program-details]");if(!b)return;const p=allPrograms.find(x=>x.id===Number(b.dataset.programDetails));if(!p)return;toast(`${p.program}: ${p.min_marks} marks, IELTS ${p.min_ielts}; documents: ${(p.documents||[]).join(", ")}.`);});

$("#chatForm").addEventListener("submit",async e=>{
  e.preventDefault(); const form=e.currentTarget, fd=new FormData(form), feedback=$("#chatFeedback");
  setFeedback(feedback,"Sending your question…");
  try {
    const currentToken=localStorage.getItem("admitcrew_student_token")||null;
    const lead=await request("/api/public/leads",{method:"POST",json:{name:fd.get("name"),phone:fd.get("phone"),country:fd.get("country")||null,marks:fd.get("marks")||null,ielts:null,access_token:currentToken}});
    const token=lead.access_token||currentToken;
    if(token)localStorage.setItem("admitcrew_student_token",token);
    await request("/api/public/chat",{method:"POST",json:{name:fd.get("name"),phone:fd.get("phone"),country:fd.get("country")||null,marks:fd.get("marks")||null,message:fd.get("message"),access_token:token}});
    form.reset(); setFeedback(feedback,"Your question is saved. A staff-reviewed answer will appear in your student inbox."); toast("Question received — thank you."); await loadStudentConversation();
  } catch(err) { setFeedback(feedback,err.message,true); }
});

async function loadStudentConversation(){
  const token=localStorage.getItem("admitcrew_student_token"); if(!token)return;
  try { const data=await request("/api/public/conversation",{headers:{Authorization:`Bearer ${token}`}}); const wrap=$("#studentInbox"); wrap.classList.remove("hidden"); const msgs=data.messages||[]; $("#studentMessages").innerHTML=msgs.length?msgs.map(m=>`<div class="bubble ${m.role==="assistant"?"outbound":""}">${esc(m.body)}<small>${m.role==="assistant"?"Office reply":"You"} · ${niceDate(m.created_at)}</small></div>`).join(""):'<div class="muted-copy">No replies yet. Check back after the office reviews your question.</div>'; }
  catch(_){ localStorage.removeItem("admitcrew_student_token"); }
}
loadStudentConversation(); setInterval(loadStudentConversation,25000);

async function loadStaff() {
  $("#staffLogin").classList.add("hidden"); $("#staffDashboard").classList.remove("hidden");
  try {
    const [stats, programs, leads, messages, docs, audit]=await Promise.all([
      request("/api/staff/dashboard"),request("/api/programs?include_unpublished=true"),request("/api/staff/leads"),request("/api/staff/messages"),request("/api/staff/documents"),request("/api/staff/audit?limit=12")
    ]);
    allPrograms=programs; allLeads=leads; renderKpis(stats); renderStaffPrograms(programs); renderLeads(leads); renderDocuments(docs); renderMessages(messages); renderAttention(leads,messages,docs); renderAudit(audit); populateDocumentLeads(leads);
  } catch(err) { sessionStorage.removeItem("admitcrew_staff_key"); $("#staffDashboard").classList.add("hidden"); $("#staffLogin").classList.remove("hidden"); setFeedback($("#loginFeedback"),`Could not load workspace: ${err.message}`,true); }
}
function renderKpis(s) {
  const data=[["STUDENTS",s.leads,""],["PUBLISHED PROGRAMS",s.published_programs,""],["QUESTIONS FOR AGENT",s.pending_chats,s.pending_chats?"warn":""],["DOCUMENT ISSUES",s.documents_to_review,s.documents_to_review?"warn":""],["WAITING FOR APPROVAL",s.messages_waiting_approval,s.messages_waiting_approval?"warn":""],["MESSAGES SENT",s.messages_sent,""]];
  $("#kpiGrid").innerHTML=data.map(x=>`<div class="kpi-card ${x[2]}"><span>${x[0]}</span><b>${x[1]}</b></div>`).join(""); $("#approvalBadge").textContent=s.messages_waiting_approval;
}
function renderStaffPrograms(rows) {
  $("#programRows").innerHTML=rows.map(p=>`<tr><td><strong>${esc(p.university)}</strong><span class="cell-sub">${esc(p.program)}</span></td><td>${esc(p.country)}</td><td>${esc(p.annual_fee)}</td><td>${esc(p.deadline)}</td><td><span class="status-pill ${p.is_published?"ok":""}">${p.is_published?"Published":"Draft"}</span></td><td><button class="table-action" data-edit-program="${p.id}">Edit</button> <button class="table-action" data-archive-program="${p.id}">${p.is_published?"Archive":"Publish"}</button></td></tr>`).join("");
}
function renderLeads(rows) {
  const q=$("#leadSearch").value.trim().toLowerCase(); const filtered=rows.filter(l=>`${l.name} ${l.phone} ${l.country||""}`.toLowerCase().includes(q));
  $("#leadRows").innerHTML=filtered.map(l=>`<tr><td><strong>${esc(l.name)}</strong></td><td>${esc(l.phone)}</td><td>${esc(l.country||"—")}</td><td>${esc(l.marks||"—")}</td><td>${esc(l.ielts||"—")}</td><td>${shortWhen(l.last_reply_at)}</td><td><button class="table-action" data-view-lead="${l.id}">View history</button></td></tr>`).join("")||'<tr><td colspan="7">No students found.</td></tr>';
}
function renderDocuments(rows) {
  $("#documentRows").innerHTML=rows.length?rows.map(d=>`<div class="doc-row"><div class="doc-icon">▤</div><div class="doc-copy"><b>${esc(d.document_type)} · ${esc(d.student_name)}</b><p>${esc(d.filename||"")} ${d.name_on_document?`· Name: ${esc(d.name_on_document)}`:""} ${d.expiry_date?`· Expiry: ${esc(d.expiry_date)}`:""}</p><span class="status-pill ${statusClass(d.status)}">${esc(d.status)}${d.reason?`: ${esc(d.reason)}`:""}</span></div></div>`).join(""):'<div class="empty-state">No documents have been reviewed.</div>';
}
function renderMessages(rows) {
  const pending=rows.filter(m=>m.status==="pending_approval");
  $("#messageRows").innerHTML=pending.length?pending.map(m=>`<article class="message-card"><div class="message-card-head"><div><b>${esc(m.student_name)} · ${esc(m.kind.replaceAll("_"," "))}</b><span class="cell-sub">${esc(m.channel)} · Created ${niceDate(m.created_at)}</span></div><span class="status-pill pending_approval">Pending approval</span></div><p>${esc(m.body)}</p><button class="button button-dark" data-approve-message="${m.id}">Approve for n8n delivery ↗</button></article>`).join(""):'<div class="empty-state">Nothing is waiting for approval.</div>';
}
function renderAttention(leads,messages,docs) {
  const quiet=leads.filter(l=>l.last_reply_at&&((Date.now()-new Date(l.last_reply_at).getTime())/86400000)>=3).length;
  const pending=messages.filter(m=>m.status==="pending_approval").length;
  const items=[]; if(pending)items.push([`${pending} message${pending===1?"":"s"} waiting for your approval`,"Review drafts","messagesPanel"]); if(docs.some(d=>["problem","needs_review"].includes(d.status)))items.push([`${docs.filter(d=>["problem","needs_review"].includes(d.status)).length} document review result(s) need attention`,"Check documents","documentsPanel"]); if(quiet)items.push([`${quiet} student(s) have been quiet for 3+ days`,"Prepare reminders","overview"]); if(!items.length)items.push(["Everything is up to date","View student list","leadsPanel"]);
  $("#attentionList").innerHTML=items.map(i=>`<div class="attention-row"><a href="#" data-go-panel="${i[2]}">${esc(i[0])}</a><span>${esc(i[1])} ↗</span></div>`).join("");
}
function renderAudit(rows) {
  $("#auditList").innerHTML=rows.length?`<table><thead><tr><th>When</th><th>Who</th><th>Action</th><th>Record</th></tr></thead><tbody>${rows.map(a=>`<tr><td>${niceDate(a.created_at)}</td><td>${esc(a.actor)}</td><td>${esc(a.action.replaceAll("_"," "))}</td><td>${esc(a.entity)} #${esc(a.entity_id)}</td></tr>`).join("")}</tbody></table>`:'<div class="empty-state">Activity will appear here.</div>';
}
function populateDocumentLeads(leads) { $("#documentLead").innerHTML='<option value="">Choose student</option>'+leads.map(l=>`<option value="${l.id}">${esc(l.name)} · ${esc(l.phone)}</option>`).join(""); }
function openPanel(name) { $$(".staff-panel").forEach(p=>p.classList.toggle("hidden",p.id!==name)); $$(".staff-tabs button").forEach(b=>b.classList.toggle("active",b.dataset.panel===name)); }

$("#staffOpen").addEventListener("click",showStaff);
$("#staffExit").addEventListener("click",showStudent);
$("#staffLoginForm").addEventListener("submit",async e=>{e.preventDefault();const key=new FormData(e.currentTarget).get("staffKey");sessionStorage.setItem("admitcrew_staff_key",key);setFeedback($("#loginFeedback"),"Checking access…");try{await request("/api/staff/dashboard");setFeedback($("#loginFeedback"),"");loadStaff();}catch(err){sessionStorage.removeItem("admitcrew_staff_key");setFeedback($("#loginFeedback"),err.message,true);}});
$("#refreshStaff").addEventListener("click",loadStaff);
$(".staff-tabs").addEventListener("click",e=>{const b=e.target.closest("[data-panel]");if(b)openPanel(b.dataset.panel);});
$("#attentionList").addEventListener("click",e=>{const a=e.target.closest("[data-go-panel]");if(a){e.preventDefault();openPanel(a.dataset.goPanel);}});
$("#leadSearch").addEventListener("input",()=>renderLeads(allLeads));
$("#leadRows").addEventListener("click",async e=>{const b=e.target.closest("[data-view-lead]");if(!b)return;try{const detail=await request(`/api/staff/leads/${b.dataset.viewLead}`);const area=$("#leadDetail");area.classList.remove("hidden");const l=detail.lead;area.innerHTML=`<h4>${esc(l.name)} · ${esc(l.phone)}</h4><div class="muted-copy">${esc(l.country||"No destination")} · Marks ${esc(l.marks||"—")} · IELTS ${esc(l.ielts||"—")}</div><h5>Chat history</h5><div class="conversation">${detail.chats.map(m=>`<div class="bubble ${m.direction.includes("outbound")?"outbound":""}">${esc(m.body)}<small>${esc(m.direction)} · ${esc(m.status)} · ${niceDate(m.created_at)}</small></div>`).join("")||'<div class="empty-state">No chats yet.</div>'}</div><div class="muted-copy" style="margin-top:12px">${detail.documents.length} document record(s) · ${detail.messages.length} message draft(s)</div>`;area.scrollIntoView({behavior:"smooth",block:"nearest"});}catch(err){toast(err.message);}});

$("#addProgramBtn").addEventListener("click",()=>openProgram());
function openProgram(program=null) {
  const f=$("#programForm"); f.reset(); f.elements.id.value=program?.id||""; $("#programModalTitle").textContent=program?"Edit program":"Add a program";
  if(program){for(const k of ["university","country","program","annual_fee","deadline","min_marks","min_ielts","source_note"]) f.elements[k].value=program[k]||""; f.elements.documents.value=(program.documents||[]).join(", "); f.elements.is_published.checked=!!program.is_published;}
  setFeedback($("#programFeedback"),""); $("#programDialog").showModal();
}
$("#programRows").addEventListener("click",async e=>{const edit=e.target.closest("[data-edit-program]"),arc=e.target.closest("[data-archive-program]");try{if(edit){const p=allPrograms.find(x=>x.id===Number(edit.dataset.editProgram));openProgram(p);}else if(arc){const p=allPrograms.find(x=>x.id===Number(arc.dataset.archiveProgram));if(p.is_published)await request(`/api/staff/programs/${p.id}`,{method:"PATCH",json:{is_published:false}});else await request(`/api/staff/programs/${p.id}`,{method:"PATCH",json:{is_published:true}});toast(p.is_published?"Program archived.":"Program published.");loadStaff();}}catch(err){toast(err.message);}});
$("#programForm").addEventListener("submit",async e=>{e.preventDefault();const f=e.currentTarget,d=Object.fromEntries(new FormData(f));const id=d.id;d.documents=d.documents.split(",").map(s=>s.trim()).filter(Boolean);d.is_published=f.elements.is_published.checked;delete d.id;setFeedback($("#programFeedback"),"Saving…");try{await request(id?`/api/staff/programs/${id}`:"/api/staff/programs",{method:id?"PATCH":"POST",json:d});$("#programDialog").close();toast("Program saved.");loadStaff();loadPrograms();}catch(err){setFeedback($("#programFeedback"),err.message,true);}});
$$("[data-close]").forEach(b=>b.addEventListener("click",()=>$("#"+b.dataset.close).close()));
$("#csvImport").addEventListener("change",async e=>{const file=e.target.files[0];if(!file)return;const fd=new FormData();fd.append("file",file);try{const result=await request("/api/staff/programs/import-csv",{method:"POST",body:fd});toast(`${result.imported} program(s) imported.`);loadStaff();loadPrograms();}catch(err){toast(err.message);}finally{e.target.value="";}});

$("#documentForm").addEventListener("submit",async e=>{e.preventDefault();const f=e.currentTarget, fd=new FormData(f), leadId=fd.get("lead_id"), type=fd.get("document_type"), score=fd.get("score");if(!leadId){setFeedback($("#documentFeedback"),"Choose a student.",true);return;}const useOcr=fd.get("use_ocr")==="on";const review={document_type:type,name_on_document:fd.get("name_on_document")||null,expiry_date:fd.get("expiry_date")||null,marks:type==="Transcript"?(score||null):null,ielts_score:type==="IELTS result"?(score||null):null};fd.delete("lead_id");fd.delete("score");fd.delete("use_ocr");if(!useOcr)fd.set("review",JSON.stringify(review));setFeedback($("#documentFeedback"),"Uploading fake test document…");try{await request(`/api/staff/documents/${leadId}`,{method:"POST",body:fd});setFeedback($("#documentFeedback"),useOcr?"Uploaded. The n8n OCR agent will review it on its next run.":"Uploaded and reviewed. See the result on the right.");f.reset();loadStaff();}catch(err){setFeedback($("#documentFeedback"),err.message,true);}});

$("#runReminder").addEventListener("click",async()=>{setFeedback($("#reminderFeedback"),"Preparing draft reminders…");try{const result=await request(`/api/staff/reminders/run?days_quiet=${$("#quietDays").value}`,{method:"POST",json:{}});setFeedback($("#reminderFeedback"),`${result.drafted} reminder draft(s) are waiting for approval. Nothing has been sent.`);loadStaff();}catch(err){setFeedback($("#reminderFeedback"),err.message,true);}});
$("#messageRows").addEventListener("click",async e=>{const b=e.target.closest("[data-approve-message]");if(!b)return;try{await request(`/api/staff/messages/${b.dataset.approveMessage}/approve`,{method:"POST",json:{}});toast("Approved. n8n may now deliver this message.");loadStaff();}catch(err){toast(err.message);}});

$("#year").textContent=new Date().getFullYear();
loadPrograms();
