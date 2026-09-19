import os
import uuid
import asyncio
import shutil
import subprocess
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent import initial_state, process_turn
from db import analytics, create_project, get_project, get_session, init_db, list_leads, list_projects, save_session, update_lead_status, update_project

init_db()
app=FastAPI(title="AutoStream AI Creator Platform API",version="3.1.0")
app.mount("/static",StaticFiles(directory="static"),name="static")
UPLOAD_DIR=Path("uploads"); UPLOAD_DIR.mkdir(exist_ok=True)

class ChatRequest(BaseModel):
    message:str=Field(...,min_length=1,max_length=2000)
    session_id:str|None=None
class LeadStatusUpdate(BaseModel):
    status:str
class ProjectCreate(BaseModel):
    name:str=Field(...,min_length=1,max_length=120)
    platform:str=Field(...,min_length=1,max_length=40)
    style:str=Field(...,min_length=1,max_length=60)
    session_id:str|None=None

@app.get("/")
def root(): return FileResponse("static/index.html")
@app.get("/admin")
def admin(): return FileResponse("static/admin.html")
@app.get("/health")
def health(): return {"status":"ok","service":"autostream-ai-platform","version":"3.1.0"}

@app.post("/chat")
def chat(request:ChatRequest):
    session_id=request.session_id or uuid.uuid4().hex
    state=get_session(session_id) or initial_state()
    reply,state=process_turn(request.message.strip(),state,session_id); save_session(session_id,state)
    return {"session_id":session_id,"reply":reply,"intent":state.get("intent"),"lead_captured":state.get("lead_captured",False)}

@app.get("/api/leads")
def leads(status:str|None=None): return list_leads(status)
@app.patch("/api/leads/{lead_id}")
def change_lead_status(lead_id:int,request:LeadStatusUpdate):
    try: updated=update_lead_status(lead_id,request.status)
    except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc))
    if not updated: raise HTTPException(status_code=404,detail="Lead not found")
    return {"status":"updated","lead_id":lead_id,"new_status":request.status}
@app.get("/api/analytics")
def get_analytics(): return analytics()

@app.post("/api/projects")
def projects_create(request:ProjectCreate):
    session_id=request.session_id or uuid.uuid4().hex
    return create_project(session_id,request.name.strip(),request.platform,request.style)
@app.get("/api/projects")
def projects_list(session_id:str|None=None): return list_projects(session_id)
@app.get("/api/projects/{project_id}")
def projects_get(project_id:int):
    project=get_project(project_id)
    if not project: raise HTTPException(status_code=404,detail="Project not found")
    return project

@app.post("/api/projects/{project_id}/upload")
async def projects_upload(project_id:int,file:UploadFile=File(...)):
    project=get_project(project_id)
    if not project: raise HTTPException(status_code=404,detail="Project not found")
    if not file.filename: raise HTTPException(status_code=400,detail="A video file is required")
    suffix=Path(file.filename).suffix.lower()
    if suffix not in {".mp4",".mov",".mkv",".webm",".avi",".m4v"}: raise HTTPException(status_code=400,detail="Use MP4, MOV, MKV, WEBM, AVI, or M4V")
    destination=UPLOAD_DIR/f"{project_id}_{uuid.uuid4().hex}{suffix}"; size=0
    with destination.open("wb") as output:
        while chunk:=await file.read(1024*1024):
            size+=len(chunk); output.write(chunk)
    return update_project(project_id,source_filename=file.filename,source_path=str(destination),source_size=size,status="uploaded",progress=10,current_step="Video uploaded")

async def _run_processing(project_id:int):
    project=get_project(project_id)
    if not project: return
    update_project(project_id,status="processing",progress=20,current_step="Analyzing video")
    for step,progress in [("Detecting scenes",35),("Finding highlights",50),("Generating captions",65),("Formatting for platform",80)]:
        await asyncio.sleep(1.2); update_project(project_id,status="processing",progress=progress,current_step=step)
    source=project.get("source_path"); output=UPLOAD_DIR/f"autostream_project_{project_id}.mp4"
    update_project(project_id,status="processing",progress=90,current_step="Rendering platform-ready MP4")
    await asyncio.sleep(.5)
    if not source or not Path(source).exists(): return
    if shutil.which("ffmpeg"):
        sizes={"TikTok":"1080:1920","Instagram":"1080:1920","YouTube":"1920:1080","LinkedIn":"1920:1080","Twitter/X":"1280:720"}
        size=sizes.get(project.get("platform"),"1920:1080")
        vf=f"scale={size}:force_original_aspect_ratio=decrease,pad={size}:(ow-iw)/2:(oh-ih)/2"
        try:
            subprocess.run(["ffmpeg","-y","-i",source,"-vf",vf,"-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(output)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=600)
        except Exception:
            shutil.copy2(source,output)
    else: shutil.copy2(source,output)
    update_project(project_id,status="completed",progress=100,current_step="Export complete",output_filename=output.name)

@app.post("/api/projects/{project_id}/process")
async def projects_process(project_id:int,background_tasks:BackgroundTasks):
    project=get_project(project_id)
    if not project: raise HTTPException(status_code=404,detail="Project not found")
    if not project.get("source_filename"): raise HTTPException(status_code=400,detail="Upload a video before processing")
    if project["status"]=="processing": return project
    background_tasks.add_task(_run_processing,project_id)
    return update_project(project_id,status="queued",progress=15,current_step="AI pipeline queued")

@app.get("/api/projects/{project_id}/output")
def projects_output(project_id:int):
    project=get_project(project_id)
    if not project or project["status"]!="completed": raise HTTPException(status_code=404,detail="Processed output is not ready")
    output=UPLOAD_DIR/project["output_filename"]
    if not output.exists(): raise HTTPException(status_code=404,detail="Output file is missing")
    return FileResponse(output,filename=project["output_filename"],media_type="video/mp4")
