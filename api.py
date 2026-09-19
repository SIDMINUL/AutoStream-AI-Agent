import os
import uuid
import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from agent import initial_state, process_turn
from db import analytics, create_project, get_project, get_session, init_db, list_leads, list_projects, save_session, update_lead_status, update_project
from video_pipeline import process_video

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "autostream-videos")
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    from supabase import create_client
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

def _storage_upload(local_path: str, object_path: str, content_type: str):
    if not supabase_client:
        return None
    with open(local_path, "rb") as handle:
        data = handle.read()
    supabase_client.storage.from_(STORAGE_BUCKET).upload(
        object_path, data, {"content-type": content_type, "upsert": "true"}
    )
    return object_path

def _storage_download(object_path: str):
    if not supabase_client:
        return None
    return supabase_client.storage.from_(STORAGE_BUCKET).download(object_path)


init_db()
app=FastAPI(title="AutoStream AI Creator Platform API",version="4.0.0")
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

@app.get("/")
def root(): return FileResponse("static/index.html")
@app.get("/admin")
def admin(): return FileResponse("static/admin.html")
@app.get("/health")
def health(): return {"status":"ok","service":"autostream-ai-platform","version":"4.0.0"}

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
    storage_path = None
    if supabase_client:
        storage_path = _storage_upload(str(destination), f"projects/{project_id}/source{suffix}", file.content_type or "video/mp4")
        destination.unlink(missing_ok=True)
    return update_project(project_id,source_filename=file.filename,source_path=storage_path or str(destination),source_size=size,status="uploaded",progress=10,current_step="Video uploaded")

async def _run_processing(project_id:int):
    project=get_project(project_id)
    if not project: return
    source=project.get("source_path")
    output=UPLOAD_DIR/f"autostream_project_{project_id}.mp4"
    if supabase_client and source:
        try:
            local_source = UPLOAD_DIR/f"processing_{project_id}_{uuid.uuid4().hex}.mp4"
            local_source.write_bytes(_storage_download(source))
            source = str(local_source)
        except Exception:
            update_project(project_id,status="failed",progress=0,current_step="Source video could not be downloaded from storage")
            return
    if not source or not Path(source).exists():
        update_project(project_id,status="failed",progress=0,current_step="Source video is missing")
        return

    try:
        update_project(project_id,status="processing",progress=20,current_step="Analyzing video")
        await asyncio.sleep(.2)

        with tempfile.TemporaryDirectory(prefix=f"autostream_{project_id}_") as work_dir:
            update_project(project_id,progress=35,current_step="Transcribing speech with Whisper")
            await asyncio.to_thread(_ensure_ffmpeg)
            await asyncio.to_thread(
                process_video,
                source,
                str(output),
                project.get("platform") or "YouTube",
                work_dir,
            )
            update_project(project_id,progress=55,current_step="Selecting the best highlight")
            await asyncio.sleep(.2)
            update_project(project_id,progress=70,current_step="Generating timed captions")
            await asyncio.sleep(.2)
            update_project(project_id,progress=85,current_step="Formatting for platform")
            await asyncio.sleep(.2)
            update_project(project_id,progress=95,current_step="Rendering final MP4")

        if supabase_client:
            output_path = _storage_upload(str(output), f"projects/{project_id}/output.mp4", "video/mp4")
            output.unlink(missing_ok=True)
            update_project(project_id,status="completed",progress=100,current_step="AI export complete",output_filename=output_path)
        else:
            update_project(project_id,status="completed",progress=100,current_step="AI export complete",output_filename=output.name)
    except Exception as exc:
        update_project(project_id,status="failed",progress=0,current_step=f"Processing failed: {str(exc)[:180]}")

def _ensure_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("FFmpeg and ffprobe are required for AI video processing.")

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
    if supabase_client:
        try:
            data = _storage_download(project["output_filename"])
            return StreamingResponse(iter([data]), media_type="video/mp4", headers={"Content-Disposition": f'attachment; filename="autostream_project_{project_id}.mp4"'})
        except Exception:
            raise HTTPException(status_code=404,detail="Output file is missing from storage")
    output=UPLOAD_DIR/project["output_filename"]
    if not output.exists(): raise HTTPException(status_code=404,detail="Output file is missing")
    return FileResponse(output,filename=output.name,media_type="video/mp4")
