let sessionId = localStorage.getItem("autostream_session_id") || null;
const form = document.getElementById("chat-form");
const input = document.getElementById("message");
const messages = document.getElementById("messages");
const meta = document.getElementById("meta");

function addMessage(text, role){
  const el = document.createElement("div");
  el.className = "bubble " + role;
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = input.value.trim();
  if(!message) return;
  addMessage(message, "user");
  input.value = "";
  meta.textContent = "Nova is thinking...";

  try {
    const res = await fetch("/chat", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({message, session_id:sessionId})
    });
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || "Request failed");
    sessionId = data.session_id;
    localStorage.setItem("autostream_session_id", sessionId);
    addMessage(data.reply, "bot");
    meta.textContent = data.lead_captured
      ? "Lead captured · Our team can follow up"
      : "Intent: " + (data.intent || "conversation");
  } catch(err) {
    addMessage("Sorry, something went wrong. Please try again.", "bot");
    meta.textContent = "Connection error";
  }
});
