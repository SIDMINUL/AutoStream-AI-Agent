"""
AutoStream AI Sales Agent
=========================
A LangGraph-based conversational agent that:
  1. Classifies user intent (greeting / inquiry / high_intent)
  2. Answers questions via RAG over a local JSON knowledge base
  3. Collects lead info (name, email, platform) on high-intent signals
  4. Calls mock_lead_capture() only after all three fields are confirmed
"""

import json
import os
import re
from typing import Optional

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

load_dotenv()

# ── Knowledge Base ────────────────────────────────────────────────────────────

_KB_PATH = os.path.join(os.path.dirname(__file__), "knowledge_base.json")

with open(_KB_PATH) as _f:
    KNOWLEDGE_BASE: dict = json.load(_f)

KB_TEXT: str = json.dumps(KNOWLEDGE_BASE, indent=2)

# ── Mock Lead Capture Tool ────────────────────────────────────────────────────

def mock_lead_capture(name: str, email: str, platform: str) -> str:
    """
    Mock API function that simulates saving a lead to a CRM.
    In production this would POST to a real CRM endpoint.
    """
    msg = f"Lead captured successfully: {name}, {email}, {platform}"
    print(f"\n{'='*55}")
    print(f"  🎯  TOOL CALLED: mock_lead_capture()")
    print(f"      name     = {name}")
    print(f"      email    = {email}")
    print(f"      platform = {platform}")
    print(f"{'='*55}\n")
    return msg


# ── Agent State ───────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    """Persistent state retained across every conversation turn."""
    messages: list[dict]        # {"role": "user"|"assistant", "content": str}
    intent: str                 # "greeting" | "inquiry" | "high_intent"
    collecting_lead: bool       # True once high-intent detected
    lead_name: Optional[str]
    lead_email: Optional[str]
    lead_platform: Optional[str]
    lead_captured: bool


# ── LLM ──────────────────────────────────────────────────────────────────────

LLM = ChatGroq(
    model="llama-3.1-8b-instant",
    max_tokens=512,
    temperature=0.3,
)

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are Nova, AutoStream's friendly and knowledgeable AI sales assistant.
AutoStream provides automated video editing tools for content creators.

KNOWLEDGE BASE (use ONLY this information to answer product questions):
{KB_TEXT}

BEHAVIOUR RULES:
- Greet users warmly and professionally.
- Answer product/pricing/policy questions using ONLY the knowledge base above.
- Never invent features, prices, or policies not in the knowledge base.
- When a user expresses clear intent to sign up or try the product, show enthusiasm.
- Keep responses concise (2–4 sentences unless more detail is asked for).
"""


def _to_lc(state: AgentState) -> list:
    """Convert AgentState messages → LangChain message objects."""
    lc = [SystemMessage(content=SYSTEM_PROMPT)]
    for m in state["messages"]:
        if m["role"] == "user":
            lc.append(HumanMessage(content=m["content"]))
        else:
            lc.append(AIMessage(content=m["content"]))
    return lc


# ── Node: Classify Intent ─────────────────────────────────────────────────────

def classify_intent(state: AgentState) -> AgentState:
    """Classify the latest user message into one of three intents."""
    last_user = next(
        m["content"] for m in reversed(state["messages"]) if m["role"] == "user"
    )

    prompt = (
        "Classify the user message below into EXACTLY one intent:\n"
        "  - greeting   : casual hello/hi with no product question\n"
        "  - inquiry    : asking about features, pricing, plans, policies, or comparisons\n"
        "  - high_intent: clearly wants to sign up, buy, trial, or start using the product\n\n"
        f'Message: "{last_user}"\n\n'
        "Reply with ONLY one word (greeting, inquiry, or high_intent):"
    )

    resp = LLM.invoke([HumanMessage(content=prompt)])
    raw = resp.content.strip().lower()

    if "high_intent" in raw or "high intent" in raw:
        intent = "high_intent"
    elif "inquiry" in raw:
        intent = "inquiry"
    else:
        intent = "greeting"

    return {**state, "intent": intent}


# ── Node: Respond with RAG ────────────────────────────────────────────────────

def respond_rag(state: AgentState) -> AgentState:
    """
    Generate a knowledge-base-grounded response for greetings and inquiries.
    The full knowledge base is injected via the system prompt, so every
    response is RAG-powered without an external vector store.
    """
    response = LLM.invoke(_to_lc(state))
    new_messages = state["messages"] + [
        {"role": "assistant", "content": response.content}
    ]
    return {**state, "messages": new_messages}


# ── Node: Start Lead Collection ───────────────────────────────────────────────

def start_lead_collection(state: AgentState) -> AgentState:
    """
    User showed high intent. Acknowledge their interest and ask for their
    name (the first field). We collect one field at a time to feel natural.
    """
    lc_msgs = _to_lc(state)
    lc_msgs.insert(
        1,
        SystemMessage(
            content=(
                "The user has shown strong buying intent! "
                "Acknowledge their excitement warmly, then ask ONLY for their full name "
                "to get the sign-up process started. Do NOT ask for email or platform yet."
            )
        ),
    )
    response = LLM.invoke(lc_msgs)
    new_messages = state["messages"] + [
        {"role": "assistant", "content": response.content}
    ]
    return {**state, "messages": new_messages, "collecting_lead": True}


# ── Node: Collect Lead Info ───────────────────────────────────────────────────

def collect_lead_info(state: AgentState) -> AgentState:
    """
    Extract whatever lead fields the user just provided, then either ask
    for the next missing field or call mock_lead_capture() if all three
    are in hand.
    """
    last_user = next(
        m["content"] for m in reversed(state["messages"]) if m["role"] == "user"
    )

    name = state.get("lead_name")
    email = state.get("lead_email")
    platform = state.get("lead_platform")

    # ── Step 1: Extract newly provided info ───────────────────────────────────
    extract_prompt = (
        "From the user message below, extract any of these details if present:\n"
        "  - full name\n"
        "  - email address\n"
        "  - creator platform (YouTube, Instagram, TikTok, Twitter, LinkedIn, etc.)\n\n"
        f'User message: "{last_user}"\n\n'
        f"Already collected — name: {name or 'unknown'}, "
        f"email: {email or 'unknown'}, platform: {platform or 'unknown'}.\n\n"
        "Return ONLY a JSON object with keys name, email, platform. "
        "Use null for anything not newly found.\n"
        'Example: {"name": "Jane Smith", "email": null, "platform": "YouTube"}'
    )

    extract_resp = LLM.invoke([HumanMessage(content=extract_prompt)])

    try:
        raw = extract_resp.content.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            extracted: dict = json.loads(match.group())
            if not name and extracted.get("name"):
                name = extracted["name"].strip()
            if not email and extracted.get("email"):
                email = extracted["email"].strip()
            if not platform and extracted.get("platform"):
                platform = extracted["platform"].strip()
    except (json.JSONDecodeError, AttributeError):
        pass  # If extraction fails, just ask for the next field

    # ── Step 2: Decide what to do ─────────────────────────────────────────────
    missing = []
    if not name:
        missing.append("full name")
    if not email:
        missing.append("email address")
    if not platform:
        missing.append("creator platform (e.g., YouTube, Instagram, TikTok)")

    if not missing:
        # ── All collected: fire the tool ──────────────────────────────────────
        tool_result = mock_lead_capture(name, email, platform)

        confirmation_msgs = _to_lc(state)
        confirmation_msgs.insert(
            1,
            SystemMessage(
                content=(
                    f"All three lead details are confirmed:\n"
                    f"  Name     : {name}\n"
                    f"  Email    : {email}\n"
                    f"  Platform : {platform}\n\n"
                    "The lead has been saved to our CRM. "
                    "Generate a warm, personalised confirmation message: "
                    "thank them by name, confirm the plan they're interested in (Pro), "
                    "and let them know the team will reach out within 24 hours. "
                    "End with an emoji or two."
                )
            ),
        )
        response = LLM.invoke(confirmation_msgs)
        new_messages = state["messages"] + [
            {"role": "assistant", "content": response.content}
        ]
        return {
            **state,
            "messages": new_messages,
            "lead_name": name,
            "lead_email": email,
            "lead_platform": platform,
            "lead_captured": True,
        }

    else:
        # ── Ask for next missing field one at a time ───────────────────────────
        next_field = missing[0]
        ask_msgs = _to_lc(state)
        ask_msgs.insert(
            1,
            SystemMessage(
                content=(
                    f"Collected so far — name: {name or 'not yet'}, "
                    f"email: {email or 'not yet'}, platform: {platform or 'not yet'}.\n"
                    f"Ask ONLY for: {next_field}. "
                    "Keep it friendly, brief, and do NOT ask for anything else."
                )
            ),
        )
        response = LLM.invoke(ask_msgs)
        new_messages = state["messages"] + [
            {"role": "assistant", "content": response.content}
        ]
        return {
            **state,
            "messages": new_messages,
            "lead_name": name,
            "lead_email": email,
            "lead_platform": platform,
        }


# ── Routing Functions ─────────────────────────────────────────────────────────

def route_entry(state: AgentState) -> str:
    """
    Entry-point router called before any node runs.
    If we're already in lead-collection mode, skip classification entirely.
    """
    if state.get("lead_captured"):
        return END
    if state.get("collecting_lead"):
        return "collect_lead_info"
    return "classify_intent"


def route_after_classify(state: AgentState) -> str:
    """Route after intent classification."""
    if state["intent"] == "high_intent":
        return "start_lead_collection"
    return "respond_rag"


# ── Build the LangGraph ───────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(AgentState)

    # Register nodes
    g.add_node("classify_intent", classify_intent)
    g.add_node("respond_rag", respond_rag)
    g.add_node("start_lead_collection", start_lead_collection)
    g.add_node("collect_lead_info", collect_lead_info)

    # Entry-point: conditional on current state
    g.add_conditional_edges(
        START,
        route_entry,
        {
            "classify_intent": "classify_intent",
            "collect_lead_info": "collect_lead_info",
            END: END,
        },
    )

    # After classification, branch on intent
    g.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {
            "start_lead_collection": "start_lead_collection",
            "respond_rag": "respond_rag",
        },
    )

    # Terminal edges
    g.add_edge("respond_rag", END)
    g.add_edge("start_lead_collection", END)
    g.add_edge("collect_lead_info", END)

    return g.compile()


# ── Public helper: process one user turn ─────────────────────────────────────

AGENT = build_graph()


def process_turn(user_input: str, state: AgentState) -> tuple[str, AgentState]:
    """
    Add user_input to state, invoke the graph, and return
    (assistant_reply, updated_state).
    """
    state["messages"].append({"role": "user", "content": user_input})
    state = AGENT.invoke(state)

    assistant_reply = next(
        m["content"] for m in reversed(state["messages"]) if m["role"] == "assistant"
    )
    return assistant_reply, state


def initial_state() -> AgentState:
    """Return a fresh conversation state."""
    return AgentState(
        messages=[],
        intent="",
        collecting_lead=False,
        lead_name=None,
        lead_email=None,
        lead_platform=None,
        lead_captured=False,
    )