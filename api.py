import os
import uuid

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent import initial_state, process_turn

app = FastAPI(
    title="AutoStream AI Sales Agent API",
    description="Session-aware AI sales assistant with intent classification, knowledge-base grounding, and lead collection.",
    version="1.1.0",
)

# Lightweight in-memory sessions for the demo deployment.
# A production CRM integration should use Redis or a database instead.
SESSIONS = {}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None


@app.get("/")
def root():
    return {
        "service": "AutoStream AI Sales Agent",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "autostream-ai-agent"}


@app.post("/chat")
def chat(request: ChatRequest):
    session_id = request.session_id or uuid.uuid4().hex
    state = SESSIONS.setdefault(session_id, initial_state())

    reply, state = process_turn(request.message.strip(), state)
    SESSIONS[session_id] = state

    return {
        "session_id": session_id,
        "reply": reply,
        "intent": state.get("intent"),
        "lead_captured": state.get("lead_captured", False),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
