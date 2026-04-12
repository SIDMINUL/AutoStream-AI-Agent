# AutoStream AI Sales Agent 🎬

A production-grade **Social-to-Lead Agentic Workflow** built for ServiceHive's Inflx platform assessment.

The agent plays the role of **Nova**, an AI sales assistant for *AutoStream* — a SaaS product offering automated video editing tools for content creators.

---

## Features

| Capability | Implementation |
|---|---|
| **Intent Classification** | LLM-based 3-way classifier (greeting / inquiry / high_intent) |
| **RAG Knowledge Base** | Local `knowledge_base.json` injected into every system prompt |
| **Lead Collection** | Sequential field capture — name → email → platform |
| **Tool Execution** | `mock_lead_capture()` called only after all 3 fields confirmed |
| **State Management** | LangGraph `StateGraph` persists full conversation across turns |
| **WhatsApp Ready** | `whatsapp_webhook.py` — FastAPI server for WhatsApp Business API |

---

## Project Structure

```
autostream-agent/
├── agent.py               # Core LangGraph agent (nodes, routing, state)
├── main.py                # CLI entry point
├── whatsapp_webhook.py    # WhatsApp webhook server (FastAPI)
├── knowledge_base.json    # RAG knowledge base (pricing, features, policies)
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quickstart

### 1. Clone & install

```bash
git clone https://github.com/your-username/autostream-agent.git
cd autostream-agent
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get a free Groq API key

Go to **[console.groq.com](https://console.groq.com)** → Sign up → API Keys → Create Key

### 3. Configure your API key

Open `.env` and add:
```
GROQ_API_KEY= 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
```

### 4. Run the CLI agent

```bash
python main.py
```

---

## Example Conversation

```
Nova: Hi there! 👋 I'm Nova, AutoStream's AI assistant. How can I help?

You:  Hi, tell me about your pricing.
Nova: AutoStream offers two plans:
      • Basic Plan – $29/month: 10 videos/month, 720p resolution
      • Pro Plan   – $79/month: Unlimited videos, 4K, AI captions, 24/7 support

You:  That sounds great. I want the Pro plan for my YouTube channel.
Nova: Amazing choice! 🎉 To get you set up, could I get your full name?

You:  Alex Johnson
Nova: Great Alex! What's your email address?

You:  alex@gmail.com
Nova: Perfect! And which creator platform are you on?

You:  YouTube
Nova: You're all set, Alex! 🎬 Our team will reach out to alex@gmail.com
      within 24 hours to activate your AutoStream Pro account!

═══════════════════════════════════════════════════════
  🎯  TOOL CALLED: mock_lead_capture()
      name     = Alex Johnson
      email    = alex@gmail.com
      platform = YouTube
═══════════════════════════════════════════════════════
```

---

## Architecture Explanation (~200 words)

### Why LangGraph?

LangGraph was chosen over AutoGen because it provides **explicit, inspectable state management** through a typed `StateGraph`. Each conversation turn is a deterministic graph traversal, making the agent's behaviour easy to trace, test, and debug — critical for a lead-capture pipeline where premature tool calls can corrupt CRM data.

### How State is Managed

Every agent turn shares a single `AgentState` TypedDict that persists across the entire conversation. It tracks:

- `messages` — full conversation history for multi-turn context
- `intent` — latest classified intent (greeting / inquiry / high_intent)
- `collecting_lead` — True once high-intent is detected
- `lead_name`, `lead_email`, `lead_platform` — fields collected one at a time
- `lead_captured` — True after `mock_lead_capture()` is called

The `route_entry` conditional edge inspects state **before any node runs**, so the graph skips intent classification on subsequent turns and jumps straight to `collect_lead_info`. This avoids state resets and unnecessary LLM calls.

Fields are extracted one per turn using a structured JSON extraction prompt. `mock_lead_capture()` is only invoked after all three values are confirmed non-null — never prematurely.

### LangGraph Flow

```
User Message
     │
     ▼
[route_entry] ── collecting_lead? ──Yes──► [collect_lead_info]
     │                                            │
     No                                  all fields collected?
     │                                       /          \
     ▼                                     Yes           No
[classify_intent]                           │             │
     │                             [mock_lead_capture] [ask next field]
     ├── greeting/inquiry ──► [respond_rag]
     │
     └── high_intent ──► [start_lead_collection]
```

---

## WhatsApp Deployment via Webhooks

### Overview

To deploy on WhatsApp, you integrate with the **WhatsApp Business Cloud API** by Meta. The agent runs as a web server and Meta pushes each incoming message to your HTTPS endpoint.

### Step-by-Step

**1. Install dependencies**
```bash
pip install fastapi uvicorn httpx
```

**2. Get ngrok** (exposes your local server to the internet)
```bash
# Download from ngrok.com, then:
ngrok http 8000
# Copy the https://xxxx.ngrok-free.app URL
```

**3. Create a Meta Developer App**
- Go to [developers.facebook.com](https://developers.facebook.com)
- Create App → Business → Add WhatsApp product
- Copy your **Phone Number ID** and **Access Token**

**4. Add to `.env`**
```
WHATSAPP_TOKEN=your_access_token
WHATSAPP_PHONE_ID=your_phone_number_id
WHATSAPP_VERIFY_TOKEN=autostream_verify_123
```

**5. Run the webhook server**
```bash
uvicorn whatsapp_webhook:app --port 8000
```

**6. Register webhook on Meta**
- WhatsApp → Configuration → Webhook → Edit
- Callback URL: `https://xxxx.ngrok-free.app/webhook`
- Verify Token: `autostream_verify_123`
- Subscribe to: `messages`

**7. How it works**
- WhatsApp user sends a message
- Meta POSTs JSON payload to `/webhook`
- Server extracts the user's phone number and text
- Text is passed to `process_turn()` with that user's session state
- Agent reply is POSTed back to Meta's Cloud API
- User receives Nova's response on WhatsApp

**Production hardening:**
- Use **Redis** for session storage (instead of in-memory dict)
- Verify webhook signature (`X-Hub-Signature-256`)
- Use a **permanent access token** (temp tokens expire in 24h)
- Deploy on **Railway / Render / AWS** instead of ngrok

The full webhook server code is in [`whatsapp_webhook.py`](./whatsapp_webhook.py).

---

## Knowledge Base

Stored in `knowledge_base.json`:

| Plan | Price | Videos | Resolution | Support |
|---|---|---|---|---|
| Basic | $29/month | 10/month | 720p | Business hours |
| Pro | $79/month | Unlimited | 4K + AI captions | 24/7 |

**Policies:**
- No refunds after 7 days
- 24/7 support on Pro plan only

---

## How Intent Detection Works

The agent sends the user's message to the LLM with this classification prompt:

```
Classify into EXACTLY one intent:
- greeting   : casual hello with no product question
- inquiry    : asking about features, pricing, plans, policies
- high_intent: clearly wants to sign up, buy, or start using the product

Message: "I want to try the Pro plan for my YouTube channel"
Reply with ONE word:
```

The LLM replies: `high_intent` → agent enters lead collection mode.

---

## Tech Stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.9+ | Required by assignment |
| Agent Framework | LangGraph | Explicit state, graph-based routing |
| LLM | Llama 3.1 8B via Groq | Free tier, fast inference |
| Knowledge Base | Local JSON | Simple, portable, no vector DB needed |
| Webhook Server | FastAPI + Uvicorn | Async, lightweight, production-ready |

---

## Evaluation Checklist

- [x] Intent detection (3-way LLM classifier)
- [x] RAG over local JSON knowledge base
- [x] Sequential lead collection (name → email → platform)
- [x] `mock_lead_capture()` called only when all fields confirmed
- [x] LangGraph state retained across 5–6 turns
- [x] Clean modular code with docstrings
- [x] WhatsApp webhook integration (FastAPI)
- [x] `requirements.txt` and `.env.example`
