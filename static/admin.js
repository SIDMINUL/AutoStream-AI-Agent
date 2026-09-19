async function load(){
  const status=document.getElementById("filter").value;
  const query=status ? "?status="+encodeURIComponent(status) : "";
  const [a,l] = await Promise.all([fetch("/api/analytics"), fetch("/api/leads"+query)]);
  const analytics=await a.json(), leads=await l.json();
  document.getElementById("total").textContent=analytics.total_leads;
  document.getElementById("qualified").textContent=analytics.qualified_leads;
  document.getElementById("converted").textContent=analytics.converted_leads;
  document.getElementById("rate").textContent=analytics.conversion_rate+"%";
  renderBars("pipeline", analytics.pipeline);
  renderBars("platforms", analytics.platforms);
  document.getElementById("leads").innerHTML=leads.map(x=>`<tr>
    <td><b>${escapeHtml(x.name)}</b></td><td>${escapeHtml(x.email)}</td><td>${escapeHtml(x.platform)}</td>
    <td><span class="pill">${escapeHtml(x.intent)}</span></td><td><span class="pill">${escapeHtml(x.status)}</span></td>
    <td>${new Date(x.created_at).toLocaleString()}</td></tr>`).join("");
}
function renderBars(id, rows){
  const max=Math.max(...rows.map(x=>x.count),1);
  document.getElementById(id).innerHTML=rows.length ? rows.map(x=>`<div class="bar"><span style="width:90px">${escapeHtml(x.status||x.platform)}</span><i style="width:${Math.max(4,x.count/max*65)}%"></i><b>${x.count}</b></div>`).join("") : "<p style='color:#718096'>No data yet.</p>";
}
function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));}
load();
