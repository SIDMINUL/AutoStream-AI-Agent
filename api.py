import os
from fastapi import FastAPI
from pydantic import BaseModel
from agent import initial_state, process_turn

app = FastAPI(title="AutoStream AI Agent API", version="1.0.0")

class ChatRequest(BaseModel):
    message: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/chat")
def chat(request: ChatRequest):
    state = initial_state()
    reply, _ = process_turn(request.message, state)
    return {"reply": reply}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
