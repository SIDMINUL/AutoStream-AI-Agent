# AutoStream AI Sales Agent

A LangGraph-based AI sales agent for AutoStream, with intent classification, knowledge-base grounding, sequential lead collection, and a deployable FastAPI API.

## Tech Stack

- Python 3.9+
- LangGraph / LangChain
- Groq Llama 3.1 8B
- FastAPI + Uvicorn
- Local JSON knowledge base

## Run locally

```bash
python -m venv venv
# Windows: venv\Scripts\activate
# macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
```

Set your secret locally in `.env`:

```env
GROQ_API_KEY=your_groq_api_key_here
```

Run the CLI:

```bash
python main.py
```

Run the API:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000
```

API endpoints:

- `GET /health`
- `POST /chat`
- `GET /docs`

## Render deployment

This repository includes `render.yaml`. Create a new Web Service from the repository in Render and provide `GROQ_API_KEY` as a secret environment variable. Render will install dependencies and start `api:app` automatically.

## WhatsApp deployment

A WhatsApp Business Cloud API webhook can be added as a separate FastAPI service. For production, use persistent session storage such as Redis, verify Meta webhook signatures, and keep all tokens in environment variables.

## Security

Never commit API keys, access tokens, or other credentials. If a credential was ever committed to this repository, revoke/rotate it immediately and replace it with an environment-variable placeholder.
