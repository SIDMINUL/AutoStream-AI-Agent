import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import initial_state, process_turn
from db import analytics, get_session, init_db, list_leads, save_session, update_lead_status

init_db()

app = FastAPI(
    title="AutoStream AI Sales Platform API",
    description="AI sales platform with customer chat, persistent sessions, lead management, and sales analytics.",
    version="2.0.0",
)

app.mount("/static", StaticFiles(directory="static"), name="static")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


class LeadStatusUpdate(BaseModel):
    status: str


@app.get("/")
def root():
    return FileResponse("static/index.html")


@app.get("/admin")
def admin():
    return FileResponse("static/admin.html")


@app.get("/health")
def health():
    return {"status": "ok", "service": "autostream-ai-platform"}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
