import os
import uuid
import asyncio
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import initial_state, process_turn
from db import (
    analytics, create_project, get_project, get_session, init_db, list_leads,
    list_projects, save_session, update_lead_status, update_project,
)

init_db()

app = FastAPI(
    title="AutoStream AI Creator Platform API",
    description="AI video automation platform with creator projects, Nova sales chat, lead management, and analytics.",
    version="3.0.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class LeadStatusUpdate(BaseModel):
    status: str


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    platform: str = Field(..., min_length=1, max_length=40)
    style: str = Field(..., min_length=1, max_length=60)
    session_id: str | None = None


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/admin")
def admin():
    return FileResponse("static/admin.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "autostream-ai-platform", "version": "3.0.0"}


@app.post("/chat")
def chat(request: ChatRequest):
    session_id = request.session_id or uuid.uuid4().hex
    state = get_session(session_id) or initial_state()
    reply, state = process_turn(request.message.strip(), state, session_id)
    save_session(session_id, state)
    return {
        "session_id": session_id,
        "reply": reply,
        "intent": state.get("intent"),
        "lead_captured": state.get("lead_captured", False),
    }


@app.get("/api/leads")
def leads(status: str | None = None):
    return list_leads(status)


@app.patch("/api/leads/{lead_id}")
def change_lead_status(lead_id: int, request: LeadStatusUpdate):
    try:
        updated = update_lead_status(lead_id, request.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"status": "updated", "lead_id": lead_id, "new_status": request.status}


@app.get("/api/analytics")
def get_analytics():
    return analytics()


@app.post("/api/projects")
def projects_create(request: ProjectCreate):
    session_id = request.session_id or uuid.uuid4().hex
    return create_project(session_id, request.name.strip(), request.platform, request.style)


@app.get("/api/projects")
def projects_list(session_id: str | None = None):
    return list_projects(session_id)


@app.get("/api/projects/{project_id}")
def projects_get(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@app.post("/api/projects/{project_id}/upload")
async def projects_upload(project_id: int, file: UploadFile = File(...)):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not file.filename:
        raise HTTPException(status_code=400, detail="A video file is required")
    suffix = Path(file.filename).suffix.lower()
    allowed = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail="Use MP4, MOV, MKV, WEBM, AVI, or M4V")
    safe_name = f"{project_id}_{uuid.uuid4().hex}{suffix}"
    destination = UPLOAD_DIR / safe_name
    size = 0
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            output.write(chunk)
    updated = update_project(
        project_id,
        source_filename=file.filename,
        source_size=size,
        status="uploaded",
        progress=10,
        current_step="Video uploaded",
    )
    return updated


async def _run_processing(project_id: int):
    steps = [
        ("Analyzing video", 25),
        ("Detecting scenes", 40),
        ("Finding highlights", 55),
        ("Generating captions", 70),
        ("Formatting for platform", 85),
        ("Exporting final video", 100),
    ]
    update_project(project_id, status="processing", progress=15, current_step="Starting AI pipeline")
    for step, progress in steps:
        await asyncio.sleep(1.2)
        update_project(project_id, status="processing" if progress < 100 else "completed",
                       progress=progress, current_step=step,
                       output_filename=f"autostream_project_{project_id}.mp4" if progress == 100 else None)


@app.post("/api/projects/{project_id}/process")
async def projects_process(project_id: int, background_tasks: BackgroundTasks):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.get("source_filename"):
        raise HTTPException(status_code=400, detail="Upload a video before processing")
    if project["status"] == "processing":
        return project
    background_tasks.add_task(_run_processing, project_id)
    return update_project(project_id, status="queued", progress=15, current_step="AI pipeline queued")


@app.get("/api/projects/{project_id}/output")
def projects_output(project_id: int):
    project = get_project(project_id)
    if not project or project["status"] != "completed":
        raise HTTPException(status_code=404, detail="Processed output is not ready")
    return {
        "project_id": project_id,
        "filename": project["output_filename"],
        "message": "Demo pipeline completed. Connect an FFmpeg/video model worker to generate the binary export.",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
