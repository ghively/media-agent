"""Browser chat page — talk to the agent at http://<host>:8088/chat.

Pure client-side page (no new backend endpoints): it keeps the conversation
in the browser and calls the existing OpenAI-compatible /v1/chat/completions
with full history each turn, which is exactly how that API is designed to
be used. If an API key is configured, the page asks once and stores it in
localStorage.
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse


def mount_chat_page(app: FastAPI) -> None:
    @app.get("/chat", response_class=HTMLResponse, include_in_schema=False)
    async def chat_page():
        return HTMLResponse(content=_CHAT_HTML)


_CHAT_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Media Agent Chat</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0d1117; color: #c9d1d9; display: flex; flex-direction: column;
    height: 100vh; height: 100dvh; }
  header { padding: 12px 16px; border-bottom: 1px solid #30363d; display: flex;
    justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.05rem; }
  header button { background: none; border: 1px solid #30363d; color: #8b949e;
    border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: .8rem; }
  #log { flex: 1; overflow-y: auto; padding: 16px; display: flex;
    flex-direction: column; gap: 10px; }
  .msg { max-width: 85%; padding: 10px 14px; border-radius: 12px;
    white-space: pre-wrap; line-height: 1.45; font-size: .95rem; }
  .user { align-self: flex-end; background: #1f6feb; color: #fff;
    border-bottom-right-radius: 4px; }
  .agent { align-self: flex-start; background: #161b22; border: 1px solid #30363d;
    border-bottom-left-radius: 4px; }
  .agent.thinking { color: #8b949e; font-style: italic; }
  form { display: flex; gap: 8px; padding: 12px 16px;
    border-top: 1px solid #30363d; }
  input { flex: 1; background: #161b22; border: 1px solid #30363d; color: #c9d1d9;
    border-radius: 8px; padding: 10px 14px; font-size: 1rem; outline: none; }
  input:focus { border-color: #58a6ff; }
  button[type=submit] { background: #238636; color: #fff; border: none;
    border-radius: 8px; padding: 0 18px; font-size: 1rem; cursor: pointer; }
  button[type=submit]:disabled { opacity: .5; cursor: default; }
</style>
</head>
<body>
<header>
  <h1>🎬 Media Agent</h1>
  <button id="reset" title="Start a fresh conversation">New chat</button>
</header>
<div id="log">
  <div class="msg agent">Hi! Ask me things like “what's new?”, “add the movie Heat”, or “what should I watch next?”</div>
</div>
<form id="form">
  <input id="input" placeholder="Message Media Agent…" autocomplete="off" autofocus>
  <button type="submit" id="send">Send</button>
</form>
<script>
(function() {
  const log = document.getElementById("log");
  const form = document.getElementById("form");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  let history = [];

  function apiKey() {
    return localStorage.getItem("media_agent_key") || "";
  }

  function bubble(cls, text) {
    const div = document.createElement("div");
    div.className = "msg " + cls;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
    return div;
  }

  document.getElementById("reset").onclick = () => {
    history = [];
    log.innerHTML = "";
    bubble("agent", "Fresh conversation. What can I do for you?");
    input.focus();
  };

  form.onsubmit = async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    bubble("user", text);
    history.push({role: "user", content: text});

    const pending = bubble("agent thinking", "Working on it…");
    send.disabled = true;
    try {
      const headers = {"Content-Type": "application/json"};
      if (apiKey()) headers["Authorization"] = "Bearer " + apiKey();
      const resp = await fetch("/v1/chat/completions", {
        method: "POST", headers,
        body: JSON.stringify({model: "media-agent", messages: history}),
      });
      if (resp.status === 401) {
        const key = prompt("This server requires an API key:");
        if (key) { localStorage.setItem("media_agent_key", key); pending.remove(); history.pop(); input.value = text; return; }
      }
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      const reply = data.choices[0].message.content;
      pending.classList.remove("thinking");
      pending.textContent = reply;
      history.push({role: "assistant", content: reply});
    } catch (err) {
      pending.classList.remove("thinking");
      pending.textContent = "❌ " + err.message;
    } finally {
      send.disabled = false;
      log.scrollTop = log.scrollHeight;
      input.focus();
    }
  };
})();
</script>
</body>
</html>"""
