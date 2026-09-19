# AutoStream AI Sales Platform

> A full-stack AI creator and sales automation platform powered by **LangGraph, LangChain, Groq, Whisper, FastAPI, SQLite, FFmpeg, and a customer/admin web interface**.

AutoStream has evolved from a conversational AI demo into an end-to-end sales platform: customers interact with an AI sales agent, high-intent conversations are qualified into leads, leads are persisted, and an operations dashboard tracks the sales pipeline.

## ✨ Features

- 🎬 **AI video pipeline** — transcription, highlight selection, timed captions, platform formatting, and MP4 export\n- 🧠 **Intent classification** — greeting, inquiry, and high-intent conversations
- 📚 **Knowledge-base grounding** — product answers are constrained to the supplied AutoStream data
- 🔄 **LangGraph workflow** — explicit stateful routing between classification, response, and lead-collection nodes
- 🎯 **Lead qualification** — collects name, email, and creator platform one field at a time
- 🛠️ **Lead management** — qualified leads are persisted in SQLite and exposed through REST APIs
- 📊 **Sales dashboard** — pipeline, conversion, platform and lead analytics
- 🌐 **Customer web app** — landing page and AI sales experience in the same deployment
- 💬 **Groq AI** — GPT-OSS 20B for conversation/highlight selection and Whisper Large V3 Turbo for transcription
- 🌐 **FastAPI REST API** — deployable `/chat` and `/health` endpoints
- 🔗 **Session-aware API** — conversation state can be continued using a `session_id`
- 📖 **Swagger documentation** — interactive API docs at `/docs`
- ☁️ **Render-ready deployment** — includes `render.yaml` and a production health check

## 🏗️ Architecture

```text
                  User Message
                       │
                       ▼
                ┌──────────────┐
                │   FastAPI    │
                │   /chat      │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │ Session State│
                └──────┬───────┘
                       │
                       ▼
                ┌────────────────────┐
                │    LangGraph       │
                │                    │
                │ Intent Classifier  │
                └─────────┬──────────┘
                          │
             ┌────────────┼─────────────┐
             ▼            ▼             ▼
          Greeting     Inquiry      High Intent
             │            │             │
             │            ▼             ▼
             │      Knowledge Base   Lead Collection
             │            │             │
             └────────────┴──────┬──────┘
                                  ▼
                           ┌─────────────┐
                           │  Groq LLM   │
                           └──────┬──────┘
                                  ▼
                              Response
```

## 🧩 Conversation Flow

### 1. Intent Classification
The latest user message is classified into one of three intents:

- `greeting` — casual conversation
- `inquiry` — product, pricing, feature, or policy questions
- `high_intent` — clear interest in signing up, buying, starting a trial, or using AutoStream

### 2. Knowledge-Base Grounding
For normal questions, the agent injects the local `knowledge_base.json` into its system context and instructs the LLM to answer only from that information.

This helps reduce hallucinated product details and keeps responses aligned with the available business information.

### 3. Lead Collection
When strong buying intent is detected, Nova switches into lead-collection mode and asks for:

1. Full name
2. Email address
3. Creator platform

The API keeps the conversation state associated with a `session_id`, allowing the next request to continue the same lead-collection flow.

### 4. Lead Capture
After all required fields are available, the project calls `mock_lead_capture()` to demonstrate the CRM integration point.

> In a production system, this function should be replaced with a real CRM/database integration.

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| LangGraph | Stateful agent workflow and routing |
| LangChain | LLM integration and message handling |
| Groq | LLM inference |
| Llama 3.1 8B Instant | Conversational model |
| FastAPI | REST API |
| Uvicorn | ASGI server |
| Pydantic | Request validation |
| JSON | Local knowledge base |
| Render | Cloud deployment |

## 📁 Project Structure

```text
AutoStream-AI-Agent/
├── agent.py              # LangGraph agent and business logic
├── api.py                # FastAPI, web routes and REST endpoints\n├── video_pipeline.py     # Whisper + GPT-OSS + FFmpeg video pipeline
├── db.py                 # Persistent sessions, leads and analytics
├── main.py               # Interactive CLI application
├── knowledge_base.json   # Product/business knowledge
├── requirements.txt      # Python dependencies
├── render.yaml           # Render deployment configuration
├── static/               # Customer app and admin dashboard
│   ├── index.html
│   ├── app.js
│   ├── styles.css
│   ├── admin.html
│   ├── admin.js
│   └── admin.css
├── .gitignore
└── README.md
```

## 🚀 Run Locally

### 1. Clone

```bash
git clone https://github.com/SIDMINUL/AutoStream-AI-Agent.git
cd AutoStream-AI-Agent
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Groq

Create a `.env` file:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Never commit the real API key.

### 5. Run the CLI

```bash
python main.py
```

### 6. Run the API

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

Open the interactive API documentation at:

```text
http://localhost:8000/docs
```

## 🔌 API

### `GET /`

Customer-facing AutoStream platform.

### `GET /admin`

Sales operations dashboard.

### `GET /api/leads`

Returns captured leads, optionally filtered by status.

### `PATCH /api/leads/{lead_id}`

Updates a lead's pipeline status.

### `GET /api/analytics`

Returns lead, conversion and platform analytics.

### `GET /health`

Returns:

```json
{
  "status": "ok",
  "service": "autostream-ai-agent"
}
```

### `POST /chat`

Request:

```json
{
  "message": "What does AutoStream cost?"
}
```

Response:

```json
{
  "session_id": "generated-session-id",
  "reply": "...",
  "intent": "inquiry",
  "lead_captured": false
}
```

To continue an existing conversation, send the returned `session_id`:

```json
{
  "message": "I want to sign up",
  "session_id": "generated-session-id"
}
```

## ☁️ Deploy to Render

The repository contains `render.yaml` with:

- Python 3.13.5 runtime
- Uvicorn production server
- `/health` health check
- `GROQ_API_KEY` as a secret environment variable

After connecting the repository to Render, add your `GROQ_API_KEY` and deploy the web service.

## 🎬 AI Video Processing\n\nThe creator workflow now performs real processing when `GROQ_API_KEY` and FFmpeg are available:\n\n1. Extract mono audio with FFmpeg.\n2. Transcribe speech with Groq Whisper Large V3 Turbo and segment timestamps.\n3. Ask GPT-OSS 20B to select a compelling 20–60 second highlight.\n4. Generate timed SRT captions from the transcript.\n5. Render the selected clip to the chosen platform aspect ratio with burned-in captions.\n\nGroq direct uploads have file-size limits, so the pipeline compresses audio before transcription. Very long recordings may require additional chunking.\n\n## 🔐 Security Notes

- API keys belong in environment variables, never source code.
- `.env` and other local secret files are excluded through `.gitignore`.
- The current session store is in-memory and intended for a demo deployment.
- For production scale, replace the in-memory store with Redis or a database.
- Replace the mock lead-capture function with a secured CRM integration before collecting real customer data.

## ⚠️ Limitations

- The knowledge base is a local JSON file rather than a production vector database.
- The lead capture function is a mock and does not persist leads to a real CRM.
- In-memory sessions are lost when the service restarts or scales to multiple instances.
- LLM output quality depends on the configured Groq model and prompt.

## Why This Project Matters

AutoStream demonstrates practical **AI agent engineering and full-stack product development**, not just LLM prompting. It combines state management, deterministic routing, grounded generation, lead qualification, persistent data, REST APIs, customer UI, sales operations, analytics, and cloud deployment.

## 👨‍💻 Author

**Abdul Momin Siddiqui**  
GitHub: **SIDMINUL**

---

⭐ If you find the project useful, consider giving the repository a star.