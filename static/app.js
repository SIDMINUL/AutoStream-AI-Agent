let sessionId=localStorage.getItem("autostream_session_id")||null;
let projectId=null;
let pollTimer=null;

const form=document.getElementById("chat-form");
const input=document.getElementById("message");
const messages=document.getElementById("messages");
const meta=document.getElementById("meta");
const promptInput=document.getElementById("video-prompt");
const imageInput=document.getElementById("image-file");
const imageLabel=document.getElementById("image-label");
const generateBtn=document.getElementById("generate-btn");
const projectStatus=document.getElementById("project-status");
const progressBar=document.getElementById("progress-bar");
const progressLabel=document.getElementById("progress-label");
const progressValue=document.getElementById("progress-value");
const generationStatus=document.getElementById("generation-status");
const output=document.getElementById("output");

function addMessage(text,role){
  const el=document.createElement("div");
  el.className="bubble "+role;
  el.textContent=text;
  messages.appendChild(el);
  messages.scrollTop=messages.scrollHeight;
}

form?.addEventListener("submit",async e=>{
  e.preventDefault();
  const message=input.value.trim();
  if(!message)return;
  addMessage(message,"user");
  input.value="";
  meta.textContent="Nova is thinking...";
  try{
    const res=await fetch("/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message,session_id:sessionId})});
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||"Request failed");
    sessionId=data.session_id;
    localStorage.setItem("autostream_session_id",sessionId);
    addMessage(data.reply,"bot");
    meta.textContent=data.lead_captured?"Lead captured":"Intent: "+(data.intent||"conversation");
  }catch(err){
    addMessage("Sorry, something went wrong. Please try again.","bot");
    meta.textContent="Connection error";
  }
});

imageInput?.addEventListener("change",()=>{
  imageLabel.textContent=imageInput.files.length?imageInput.files[0].name:" + Add reference image (optional)";
});

generateBtn?.addEventListener("click",async()=>{
  const prompt=promptInput.value.trim();
  if(!prompt){
    generationStatus.textContent="Enter a prompt first";
    return;
  }

  generateBtn.disabled=true;
  output.textContent="";
  setProgress(3,"Creating generation job");
  generationStatus.textContent="Preparing...";
  projectStatus.textContent="Creating project";

  try{
    const createRes=await fetch("/api/projects",{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        name:prompt.slice(0,70),
        prompt,
        duration:Number(document.getElementById("duration").value),
        aspect_ratio:document.getElementById("aspect-ratio").value,
        style:document.getElementById("video-style").value
      })
    });
    const project=await createRes.json();
    if(!createRes.ok)throw new Error(project.detail||"Could not create generation");

    projectId=project.id;

    if(imageInput.files.length){
      setProgress(8,"Uploading reference image");
      const fd=new FormData();
      fd.append("file",imageInput.files[0]);
      const imageRes=await fetch("/api/projects/"+projectId+"/image",{method:"POST",body:fd});
      const imageData=await imageRes.json();
      if(!imageRes.ok)throw new Error(imageData.detail||"Image upload failed");
    }

    const genRes=await fetch("/api/projects/"+projectId+"/generate",{method:"POST"});
    const genData=await genRes.json();
    if(!genRes.ok)throw new Error(genData.detail||"Generation could not start");

    setProgress(genData.progress,genData.current_step);
    generationStatus.textContent="Generating...";
    projectStatus.textContent="Generation in progress";
    clearInterval(pollTimer);
    pollTimer=setInterval(pollProject,2000);
    await pollProject();
    await loadProjects();
  }catch(err){
    generationStatus.textContent="Generation failed";
    output.textContent=err.message;
    setProgress(0,"Ready");
    generateBtn.disabled=false;
  }
});

async function pollProject(){
  if(!projectId)return;
  try{
    const res=await fetch("/api/projects/"+projectId);
    const data=await res.json();
    if(!res.ok)throw new Error(data.detail||"Could not read generation status");
    setProgress(data.progress,data.current_step);
    projectStatus.textContent="Project #"+projectId+" · "+data.status;

    if(data.status==="completed"){
      clearInterval(pollTimer);
      generationStatus.textContent="Video ready";
      output.innerHTML='<a class="primary" href="/api/projects/'+projectId+'/output" target="_blank">Download MP4</a>';
      await showPreview("/api/projects/"+projectId+"/output");
      generateBtn.disabled=false;
      await loadProjects();
    }else if(data.status==="failed"){
      clearInterval(pollTimer);
      generationStatus.textContent="Generation failed";
      output.textContent=data.current_step||"Generation failed";
      generateBtn.disabled=false;
      await loadProjects();
    }
  }catch(err){
    clearInterval(pollTimer);
    generationStatus.textContent="Connection error";
    output.textContent=err.message;
    generateBtn.disabled=false;
  }
}

async function showPreview(url){
  const preview=document.getElementById("video-preview");
  preview.innerHTML="";
  const video=document.createElement("video");
  video.controls=true;
  video.playsInline=true;
  video.src=url;
  video.style.width="100%";
  video.style.height="100%";
  video.style.objectFit="contain";
  preview.appendChild(video);
}

async function loadProjects(){
  const res=await fetch("/api/projects");
  if(!res.ok)return;
  const projects=await res.json();
  const list=document.getElementById("projects-list");
  if(!projects.length){
    list.innerHTML='<span class="muted">No generations yet.</span>';
    return;
  }
  list.innerHTML=projects.map(p=>`
    <button class="project-row" onclick="selectProject(${p.id})">
      <span><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.duration||5)}s · ${escapeHtml(p.aspect_ratio||"16:9")} · ${escapeHtml(p.style||"Cinematic")}</small></span>
      <em>${escapeHtml(p.status)} · ${p.progress||0}%</em>
    </button>`).join("");
}

async function selectProject(id){
  const res=await fetch("/api/projects/"+id);
  const p=await res.json();
  if(!res.ok)return;
  projectId=p.id;
  promptInput.value=p.prompt||"";
  document.getElementById("duration").value=p.duration||5;
  document.getElementById("aspect-ratio").value=p.aspect_ratio||"16:9";
  document.getElementById("video-style").value=p.style||"Cinematic";
  projectStatus.textContent="Project #"+p.id+" · "+p.status;
  setProgress(p.progress||0,p.current_step||"Ready");
  if(p.status==="completed"){
    generationStatus.textContent="Video ready";
    output.innerHTML='<a class="primary" href="/api/projects/'+p.id+'/output" target="_blank">Download MP4</a>';
    showPreview("/api/projects/"+p.id+"/output");
  }else if(p.status==="failed"){
    generationStatus.textContent="Generation failed";
    output.textContent=p.current_step||"Generation failed";
  }
}

function setProgress(value,label){
  progressBar.style.width=value+"%";
  progressValue.textContent=value+"%";
  progressLabel.textContent=label||"";
}

function escapeHtml(v){
  return String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]));
}

document.getElementById("refresh-projects")?.addEventListener("click",loadProjects);
loadProjects();
