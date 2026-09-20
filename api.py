import os
import uuid
import asyncio
import shutil
import tempfile
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import initial_state, process_turn
from db import (
    analytics, create_project, get_project, get_session, init_db, list_leads,
    list_projects, save_session, update_lead_status, update_project,
)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "autostream-videos")
HF_KEY = os.getenv("HF_KEY")
HF_API_KEY_ID = os.getenv("HF_API_KEY_ID")
HF_API_KEY_SECRET = os.getenv("HF_API_KEY_SECRET")
HF_API_KEY = os.getenv("HF_API_KEY")
HF_API_SECRET = os.getenv("HF_API_SECRET")
supabase_client = None

if SUPABASE_URL and SUPABASE_KEY:
    from supabase import create_client
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="AutoStream AI Video Generator API", version="5.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class LeadStatusUpdate(BaseModel):
    status: str


class ProjectCreate(BaseModel):
    name: str = Field(default="AI Video", min_length=1, max_length=120)
    prompt: str = Field(..., min_length=3, max_length=5000)
    duration: int = Field(default=5, ge=4, le=30)
    aspect_ratio: str = Field(default="16:9", pattern=r"^(16:9|9:16|1:1|4:3|3:4|21:9)$")
    style: str = Field(default="Cinematic", max_length=60)


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/admin")
def admin():
    return FileResponse("static/admin.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "autostream-ai-video-generator", "version": "5.0.0"}


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
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"status": "updated", "lead_id": lead_id, "new_status": request.status}


@app.get("/api/analytics")
def get_analytics():
    return analytics()


@app.post("/api/projects")
def projects_create(request: ProjectCreate):
    session_id = uuid.uuid4().hex
    return create_project(
        session_id,
        request.name.strip(),
        "AI Video",
        request.style.strip(),
        request.prompt.strip(),
        request.duration,
        request.aspect_ratio,
    )


@app.get("/api/projects")
def projects_list():
    return list_projects()


@app.get("/api/projects/{project_id}")
def projects_get(project_id: int):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def _hf_credentials():
    if HF_KEY:
        return HF_KEY
    if HF_API_KEY_ID and HF_API_KEY_SECRET:
        return f"{HF_API_KEY_ID}:{HF_API_KEY_SECRET}"
    if HF_API_KEY and HF_API_SECRET:
        return f"{HF_API_KEY}:{HF_API_SECRET}"
    raise RuntimeError(
        "Higgsfield credentials are not configured. Add HF_API_KEY_ID + HF_API_KEY_SECRET."
    )


def _signed_image_url(storage_path: str) -> str:
    if not supabase_client:
        raise RuntimeError("Supabase storage is required for image-to-video generation.")
    result = supabase_client.storage.from_(STORAGE_BUCKET).create_signed_url(storage_path, 3600)
    if isinstance(result, dict):
        return result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
    return getattr(result, "signed_url", None) or getattr(result, "signedURL", None)


@app.post("/api/projects/{project_id}/image")
async def projects_image(project_id: int, file: UploadFile = File(...)):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not file.filename:
        raise HTTPException(status_code=400, detail="An image is required")
    if file.size and file.size > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Reference image must be 10 MB or smaller.")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Use JPG, PNG, or WEBP.")
    destination = UPLOAD_DIR / f"{project_id}_{uuid.uuid4().hex}{suffix}"
    with destination.open("wb") as output:
        while chunk := await file.read(1024 * 1024):
            output.write(chunk)

    if not supabase_client:
        return update_project(
            project_id,
            source_filename=file.filename,
            source_path=str(destination),
            source_size=destination.stat().st_size,
        )

    storage_path = f"projects/{project_id}/input{suffix}"
    try:
        with destination.open("rb") as handle:
            supabase_client.storage.from_(STORAGE_BUCKET).upload(
                storage_path, handle, {"content-type": file.content_type or "image/jpeg", "upsert": "true"}
            )
        destination.unlink(missing_ok=True)
        return update_project(
            project_id,
            source_filename=file.filename,
            source_path=storage_path,
            source_size=0,
        )
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(exc)[:180]}")


def _generate_with_higgsfield(project: dict, image_url: str | None):
    import higgsfield_client

    # Support the current Higgsfield Key ID / Key Secret environment names.
    # The SDK reads HF_API_KEY and HF_API_SECRET, so map the current names
    # immediately before invoking it.
    if HF_API_KEY_ID and HF_API_KEY_SECRET:
        os.environ["HF_API_KEY"] = HF_API_KEY_ID
        os.environ["HF_API_SECRET"] = HF_API_KEY_SECRET
    elif HF_KEY:
        os.environ["HF_KEY"] = HF_KEY
    elif HF_API_KEY and HF_API_SECRET:
        os.environ["HF_API_KEY"] = HF_API_KEY
        os.environ["HF_API_SECRET"] = HF_API_SECRET

    model = "bytedance/seedance-2.5/image-to-video" if image_url else "bytedance/seedance-2.5/text-to-video"
    arguments = {
        "prompt": project["prompt"],
        "duration": int(project["duration"]),
        "resolution": "720p",
        "aspect_ratio": project["aspect_ratio"],
        "output_format": "mp4",
        "generate_audio": True,
    }
    if image_url:
        arguments["image_url"] = image_url

    print(f"[generation] submitting {model}", flush=True)
    result = higgsfield_client.subscribe(model, arguments=arguments)
    video = result.get("video") if isinstance(result, dict) else None
    if isinstance(video, dict):
        url = video.get("url")
    else:
        url = video
    if not url:
        raise RuntimeError(f"Higgsfield returned no video result: {str(result)[:500]}")
    return url


async def _download_video(url: str, destination: Path):
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0), follow_redirects=True) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    output.write(chunk)


async def _run_generation(project_id: int):
    project = get_project(project_id)
    if not project:
        return

    try:
        update_project(project_id, status="processing", progress=10, current_step="Preparing generation")
        image_url = None
        if project.get("source_path"):
            image_url = _signed_image_url(project["source_path"])
            if not image_url:
                raise RuntimeError("Could not create a temporary image URL.")

        update_project(project_id, progress=20, current_step="Sending prompt to AI video model")
        image_mode = "image-to-video" if image_url else "text-to-video"
        update_project(project_id, progress=30, current_step=f"Generating {image_mode}")
        video_url = await asyncio.to_thread(_generate_with_higgsfield, project, image_url)

        update_project(project_id, progress=85, current_step="Saving generated video")
        local_output = UPLOAD_DIR / f"generated_{project_id}_{uuid.uuid4().hex}.mp4"
        await _download_video(video_url, local_output)

        if supabase_client:
            output_path = f"projects/{project_id}/output.mp4"
            with local_output.open("rb") as handle:
                supabase_client.storage.from_(STORAGE_BUCKET).upload(
                    output_path, handle, {"content-type": "video/mp4", "upsert": "true"}
                )
            local_output.unlink(missing_ok=True)
            update_project(
                project_id,
                status="completed",
                progress=100,
                current_step="Video generated successfully",
                output_filename=output_path,
            )
        else:
            update_project(
                project_id,
                status="completed",
                progress=100,
                current_step="Video generated successfully",
                output_filename=local_output.name,
            )
    except Exception as exc:
        print(f"[generation] failed: {exc}", flush=True)
        update_project(
            project_id,
            status="failed",
            progress=0,
            current_step=f"Generation failed: {str(exc)[:220]}",
        )


@app.post("/api/projects/{project_id}/generate")
async def projects_generate(project_id: int, background_tasks: BackgroundTasks):
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.get("prompt"):
        raise HTTPException(status_code=400, detail="Enter a video prompt first.")
    if project.get("status") == "processing":
        return project
    try:
        _hf_credentials()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    background_tasks.add_task(_run_generation, project_id)
    return update_project(project_id, status="queued", progress=5, current_step="Generation queued")


@app.get("/api/projects/{project_id}/output")
def projects_output(project_id: int):
    project = get_project(project_id)
    if not project or project["status"] != "completed":
        raise HTTPException(status_code=404, detail="Generated video is not ready")
    if supabase_client:
        try:
            signed = supabase_client.storage.from_(STORAGE_BUCKET).create_signed_url(project["output_filename"], 3600)
            if isinstance(signed, dict):
                url = signed.get("signedURL") or signed.get("signedUrl") or signed.get("signed_url")
            else:
                url = getattr(signed, "signed_url", None) or getattr(signed, "signedURL", None)
            if not url:
                raise RuntimeError("No signed URL returned")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=url, status_code=307)
        except Exception:
            raise HTTPException(status_code=404, detail="Generated video is missing from storage")
    output = UPLOAD_DIR / project["output_filename"]
    if not output.exists():
        raise HTTPException(status_code=404, detail="Generated video is missing")
    return FileResponse(output, filename=output.name, media_type="video/mp4")
