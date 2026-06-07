#!/usr/bin/env python3
"""Robco Industries (R) Companion Termlink - debug web client.

A small web-based debug client for the Fallout 1 CE companion server.
Speaks the same newline-delimited JSON protocol as a real companion client
but exposes send and receive in a browser UI with a Fallout-flavored CRT
look, so you do not have to keep typing into netcat.

Supports the current step-2 / T0 protocol surface:
  - auth (constant-time compared by the server, with the configured
    companion_password from fallout.cfg)
  - hello
  - get_snapshot
  - cmd (T6: id, name, args)
  - any other raw JSON line for protocol experiments

T0 protocol awareness (visible in the log and the toolbar):
  - `world.schemaVersion` is displayed inline (T0 bumped it to 3).
  - `update` messages show the `kind` tag (e.g. `player.vitals`,
    `player.local_location`, `player.world_location`) so you can
    tell at a glance which aspect of the player the update is about.
  - The log toolbar has a "kind" filter so you can scope the log to
    one kind (or one `world.schemaVersion`).
  - `snapshot` and `update` no longer carry `entity` or `data` (T0
    replaced them with `kind` and `payload`). The log still pretty-
    prints whatever the server emits, so the new shape just shows up
    as a different JSON object.

If a password is provided, connect() sends auth then hello automatically.
If no password is provided, connect() sends hello directly (step-1 mode).
The full traffic log is preserved so you can copy lines for bug reports.

Dependencies: Python 3.7+ stdlib only.

Run:
    python3 tools/companion-debug-web/companion_debug_web.py
    python3 tools/companion-debug-web/companion_debug_web.py --web-port 8080

Open http://127.0.0.1:8080/ in a browser.
"""

import argparse
import json
import socket
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DEFAULT_GAME_HOST = "127.0.0.1"
DEFAULT_GAME_PORT = 28080
DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8080
POLL_HINT_MS = 250
MAX_MESSAGES = 2000
RECV_CHUNK = 4096
SOCKET_CONNECT_TIMEOUT = 5.0


class MessageBuffer:
    def __init__(self):
        self._lock = threading.Lock()
        self._messages = []
        self._seq = 0

    def append(self, direction, text, meta=None):
        with self._lock:
            self._seq += 1
            entry = {
                "seq": self._seq,
                "dir": direction,
                "text": text,
                "ts": time.time(),
            }
            if meta:
                entry["meta"] = meta
            self._messages.append(entry)
            if len(self._messages) > MAX_MESSAGES:
                del self._messages[: len(self._messages) - MAX_MESSAGES]

    def since(self, seq):
        with self._lock:
            return [m for m in self._messages if m["seq"] > seq], self._seq

    def all(self):
        with self._lock:
            return list(self._messages)

    def clear(self):
        with self._lock:
            self._messages = []
            self._seq = 0


class CompanionClient:
    def __init__(self, buffer_):
        self._buf = buffer_
        self._lock = threading.Lock()
        self._sock = None
        self._thread = None
        self._connected = False

    def is_connected(self):
        with self._lock:
            return self._connected

    def connect(self, host, port, password, send_hello):
        with self._lock:
            if self._connected:
                return False, "already connected"
            try:
                sock = socket.create_connection((host, port), timeout=SOCKET_CONNECT_TIMEOUT)
            except OSError as e:
                return False, f"connect failed: {e}"
            sock.settimeout(None)
            self._sock = sock
            self._connected = True
            self._thread = threading.Thread(target=self._read_loop, name="companion-recv", daemon=True)
            self._thread.start()

        if password:
            ok, err = self._send_unlocked({"type": "auth", "password": password})
            if not ok:
                self.disconnect()
                return False, f"auth send failed: {err}"
        if send_hello:
            ok, err = self._send_unlocked({"type": "hello"})
            if not ok:
                self.disconnect()
                return False, f"hello send failed: {err}"
        return True, "ok"

    def disconnect(self):
        with self._lock:
            sock = self._sock
            self._sock = None
            self._connected = False
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def send_dict(self, payload):
        return self._send_unlocked(payload)

    def send_raw(self, line):
        if not line:
            return False, "empty line"
        if not line.endswith("\n"):
            line += "\n"
        return self._send_unlocked_raw(line)

    def _send_unlocked(self, payload):
        try:
            encoded = json.dumps(payload, separators=(",", ":"))
        except (TypeError, ValueError) as e:
            return False, f"encode failed: {e}"
        return self._send_unlocked_raw(encoded + "\n", preview=encoded)

    def _send_unlocked_raw(self, line, preview=None):
        with self._lock:
            sock = self._sock
            if sock is None:
                return False, "not connected"
            try:
                sock.sendall(line.encode("utf-8"))
            except OSError as e:
                self._connected = False
                self._sock = None
                try:
                    sock.close()
                except OSError:
                    pass
                return False, f"send failed: {e}"
        self._buf.append("out", preview if preview is not None else line.rstrip("\n"))
        return True, "ok"

    def _read_loop(self):
        sock = self._sock
        leftover = b""
        try:
            while True:
                try:
                    chunk = sock.recv(RECV_CHUNK)
                except OSError as e:
                    self._buf.append("system", f"recv error: {e}")
                    break
                if not chunk:
                    break
                leftover += chunk
                while b"\n" in leftover:
                    raw, _, leftover = leftover.partition(b"\n")
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = repr(raw)
                    self._buf.append("in", text)
        finally:
            with self._lock:
                was_connected = self._connected
                self._connected = False
                self._sock = None
            if was_connected:
                self._buf.append("system", "disconnected")
            try:
                sock.close()
            except OSError:
                pass


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Robco Industries (R) - Companion Termlink</title>
<style>
:root {
  --bg: #050505;
  --term-bg: #0a1208;
  --term-fg: #19ff66;
  --term-dim: #0c5a23;
  --term-faint: #073812;
  --amber: #ffb000;
  --amber-dim: #6a4a00;
  --red: #ff4040;
  --blue: #6ad0ff;
  --magenta: #ff66cc;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--term-fg);
  font-family: "Courier New", "Consolas", "Liberation Mono", monospace;
  font-size: 14px;
  line-height: 1.4;
  min-height: 100vh;
}
a { color: var(--amber); }
.terminal {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px 22px 60px;
  border-left: 2px solid var(--term-dim);
  border-right: 2px solid var(--term-dim);
  min-height: 100vh;
  background: var(--term-bg);
  box-shadow: inset 0 0 220px rgba(0, 0, 0, 0.6);
}
.term-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--term-dim);
  padding: 0 4px 12px;
  margin-bottom: 18px;
  color: var(--amber);
  text-transform: uppercase;
  letter-spacing: 2px;
  font-weight: bold;
  text-shadow: 0 0 6px rgba(255, 176, 0, 0.4);
}
.brand-sub {
  display: block;
  font-size: 10px;
  color: var(--term-dim);
  letter-spacing: 3px;
  margin-top: 4px;
  font-weight: normal;
  text-shadow: none;
}
.status-pill {
  padding: 4px 12px;
  border: 1px solid currentColor;
  font-size: 12px;
  letter-spacing: 1.5px;
}
.status-pill.connected { color: var(--term-fg); text-shadow: 0 0 6px var(--term-fg); }
.status-pill.disconnected { color: var(--red); text-shadow: 0 0 6px var(--red); }
.panel {
  border: 1px solid var(--term-dim);
  margin-bottom: 16px;
  background: rgba(0, 0, 0, 0.35);
}
.panel h2 {
  margin: 0;
  padding: 6px 12px;
  background: linear-gradient(90deg, var(--term-faint), transparent);
  color: var(--amber);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 2px;
  border-bottom: 1px solid var(--term-dim);
}
.panel-body { padding: 14px; }
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1 1 160px;
  min-width: 140px;
}
.field.wide { flex: 2 1 320px; }
.field.grow { flex: 0 0 auto; }
.field label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--term-dim);
}
input, select, textarea, button {
  font-family: inherit;
  font-size: 14px;
  background: #000;
  color: var(--term-fg);
  border: 1px solid var(--term-dim);
  padding: 5px 8px;
  border-radius: 0;
}
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--term-fg);
  box-shadow: 0 0 6px rgba(25, 255, 102, 0.5);
}
input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--term-fg);
  margin: 0;
}
button {
  cursor: pointer;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--amber);
  border-color: var(--amber-dim);
  background: #0a0a0a;
  padding: 6px 14px;
  transition: background 0.1s, color 0.1s, box-shadow 0.1s;
}
button:hover:not(:disabled) {
  background: var(--term-faint);
  color: var(--amber);
  box-shadow: 0 0 6px rgba(255, 176, 0, 0.4);
}
button.primary {
  color: var(--term-fg);
  border-color: var(--term-dim);
}
button.primary:hover:not(:disabled) {
  box-shadow: 0 0 8px rgba(25, 255, 102, 0.6);
}
button:disabled { opacity: 0.35; cursor: not-allowed; }
textarea {
  width: 100%;
  min-height: 64px;
  resize: vertical;
}
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--term-dim);
  font-size: 12px;
  color: var(--term-dim);
  text-transform: uppercase;
  letter-spacing: 1px;
}
.toolbar label { display: flex; align-items: center; gap: 6px; }
.toolbar .spacer { flex: 1; }
.log {
  height: 460px;
  overflow-y: auto;
  padding: 8px 12px;
  font-size: 13px;
  scrollbar-color: var(--term-dim) #000;
  scrollbar-width: thin;
}
.log::-webkit-scrollbar { width: 8px; }
.log::-webkit-scrollbar-track { background: #000; }
.log::-webkit-scrollbar-thumb { background: var(--term-dim); }
.msg {
  display: grid;
  grid-template-columns: 78px 22px 1fr;
  gap: 8px;
  padding: 2px 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-ts { color: var(--term-faint); }
.msg-dir { text-align: center; font-weight: bold; }
.msg-in .msg-dir { color: var(--blue); }
.msg-out .msg-dir { color: var(--amber); }
.msg-system .msg-dir { color: var(--red); }
.msg-system .msg-body { color: var(--red); font-style: italic; }
.msg-body { color: var(--term-fg); }
.msg-type {
  color: var(--magenta);
  margin-right: 6px;
  text-transform: lowercase;
}
.msg-meta { color: var(--term-dim); margin-right: 6px; }
.empty {
  color: var(--term-faint);
  font-style: italic;
  text-align: center;
  padding: 20px;
}
.caret {
  display: inline-block;
  width: 8px;
  height: 14px;
  background: var(--term-fg);
  vertical-align: text-bottom;
  margin-left: 2px;
  animation: blink 1s steps(1) infinite;
}
@keyframes blink { 50% { opacity: 0; } }
.scanlines {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 1000;
  background: repeating-linear-gradient(
    0deg,
    rgba(0, 0, 0, 0.18) 0px,
    rgba(0, 0, 0, 0.18) 1px,
    transparent 1px,
    transparent 3px
  );
  mix-blend-mode: multiply;
}
.help {
  color: var(--term-dim);
  font-size: 11px;
  margin-top: 8px;
  text-transform: uppercase;
  letter-spacing: 1px;
}
.kbd {
  display: inline-block;
  border: 1px solid var(--term-dim);
  padding: 1px 5px;
  border-radius: 2px;
  color: var(--amber);
  font-size: 11px;
  margin: 0 2px;
}
.divider {
  border: none;
  border-top: 1px dashed var(--term-faint);
  margin: 14px 0;
}
</style>
</head>
<body>
<div class="scanlines"></div>
<div class="terminal">
  <header class="term-header">
    <div>
      Robco Industries (R) - Companion Termlink
      <span class="brand-sub">// Vault-Tec Authorized Debug Interface v0.1</span>
    </div>
    <span class="status-pill disconnected" id="status">DISCONNECTED</span>
  </header>

  <section class="panel">
    <h2>// Connection</h2>
    <div class="panel-body">
      <form id="connect-form" class="row">
        <div class="field"><label>Host</label><input name="host" value="127.0.0.1" required></div>
        <div class="field"><label>Port</label><input name="port" value="28080" type="number" min="1" max="65535" required></div>
        <div class="field wide"><label>Password (step-2; leave blank for step-1)</label><input name="password" type="password" autocomplete="off" placeholder="companion_password from fallout.cfg"></div>
        <div class="field grow">
          <label><input type="checkbox" name="send_hello" checked> Auto-send <code>hello</code> after connect</label>
        </div>
        <div class="field grow">
          <button type="submit" class="primary" id="connect-btn">Connect</button>
          <button type="button" id="disconnect-btn" disabled style="margin-top:6px">Disconnect</button>
        </div>
      </form>
      <div class="help">
        Connect opens a TCP socket to the game. If a password is set, it sends
        <code>auth</code> first, then (if checked) <code>hello</code>. Without a password
        it sends <code>hello</code> directly (step-1 server). <span class="kbd">Esc</span> to disconnect.
      </div>
    </div>
  </section>

  <section class="panel">
    <h2>// Transmit</h2>
    <div class="panel-body">
      <form id="send-form" class="row">
        <div class="field"><label>Type</label>
          <select name="type" id="send-type">
            <option value="hello">hello</option>
            <option value="get_snapshot">get_snapshot</option>
            <option value="auth">auth</option>
            <option value="cmd">cmd</option>
            <option value="raw">raw (any JSON)</option>
          </select>
        </div>
        <div id="send-fields" class="field wide"></div>
        <div class="field grow">
          <button type="submit" class="primary" id="send-btn" disabled>Transmit</button>
        </div>
      </form>
    </div>
  </section>

    <section class="panel">
    <h2>// Traffic Log</h2>
    <div class="toolbar">
      <label><input type="checkbox" id="autoscroll" checked> Auto-scroll</label>
      <label><input type="checkbox" id="show-types" checked> Color types</label>
      <label>Filter
        <select id="filter-mode">
          <option value="off">off</option>
          <option value="kind">by kind</option>
          <option value="schema">by world.schemaVersion</option>
        </select>
        <input id="filter-value" placeholder="player.vitals / 3" size="16" disabled>
      </label>
      <span class="spacer"></span>
      <span id="log-count">0 lines</span>
      <button type="button" id="clear-btn">Clear</button>
    </div>
    <div class="log" id="log">
      <div class="empty">// no traffic yet - press Connect</div>
    </div>
  </section>

  <div class="help" style="text-align:right; margin-top:18px;">
    Companion Termlink <span class="caret"></span>
  </div>
</div>

<script>
const TYPE_COLORS = {
  world: "#6ad0ff",
  snapshot: "#19ff66",
  update: "#19ff66",
  player_unavailable: "#ff4040",
  hello: "#ffb000",
  get_snapshot: "#ffb000",
  auth: "#ffb000",
  cmd: "#ffb000",
  cmd_ack: "#19ff66",
  announce: "#ff66cc",
  foo: "#ff66cc"
};

const META_COLORS = {
  // `kind` values for `update` and the keys of `snapshot.payload`.
  "player.vitals": "#19ff66",
  "player.local_location": "#6ad0ff",
  "player.world_location": "#ff66cc",
  // `schemaVersion` for `world` (T0: 3).
  "schema:3": "#6ad0ff",
  "schema:2": "#6a4a00",
  "schema:1": "#6a4a00"
};

// Pull the `kind` tag out of an `update` message, or the
// `schemaVersion` tag out of a `world` message. Returns null when the
// message has neither.
function metaTag(parsed) {
  if (!parsed || typeof parsed !== "object") return null;
  if (parsed.type === "update" && typeof parsed.kind === "string") {
    return parsed.kind;
  }
  if (parsed.type === "world" && typeof parsed.schemaVersion !== "undefined") {
    return "schema:" + parsed.schemaVersion;
  }
  return null;
}

function messageMatchesFilter(msg) {
  const mode = elFilterMode.value;
  if (mode === "off") return true;
  const needle = (elFilterValue.value || "").trim();
  if (!needle) return true;
  const parsed = safeJson(msg.text);
  if (!parsed) return false;
  const tag = metaTag(parsed);
  if (mode === "kind") {
    // `kind` filter: match on the `update.kind` value, or pass through
    // `world` messages that match a `schema:N` query, or any message
    // whose `payload` keys contain the needle (useful for filtering to
    // `snapshot` payload kinds).
    if (tag && tag === needle) return true;
    if (typeof parsed.kind === "string" && parsed.kind === needle) return true;
    if (parsed.payload && typeof parsed.payload === "object") {
      if (Object.prototype.hasOwnProperty.call(parsed.payload, needle)) {
        return true;
      }
    }
    return false;
  }
  if (mode === "schema") {
    return tag === "schema:" + needle;
  }
  return true;
}

const elLog = document.getElementById("log");
const elStatus = document.getElementById("status");
const elConnectBtn = document.getElementById("connect-btn");
const elDisconnectBtn = document.getElementById("disconnect-btn");
const elSendBtn = document.getElementById("send-btn");
const elConnectForm = document.getElementById("connect-form");
const elSendForm = document.getElementById("send-form");
const elSendType = document.getElementById("send-type");
const elSendFields = document.getElementById("send-fields");
const elAutoscroll = document.getElementById("autoscroll");
const elShowTypes = document.getElementById("show-types");
const elClearBtn = document.getElementById("clear-btn");
const elLogCount = document.getElementById("log-count");
const elFilterMode = document.getElementById("filter-mode");
const elFilterValue = document.getElementById("filter-value");

let lastSeq = 0;
let connected = false;
let cachedPassword = "";

function tsFormat(epoch) {
  const d = new Date(epoch * 1000);
  const pad = (n) => String(n).padStart(2, "0");
  return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds()) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function safeJson(text) {
  if (!text) return null;
  try { return JSON.parse(text); } catch (e) { return null; }
}

function arrowFor(dir) {
  if (dir === "in") return "<--";
  if (dir === "out") return "-->";
  return "**";
}

function renderMessage(msg) {
  const div = document.createElement("div");
  div.className = "msg msg-" + msg.dir;
  const ts = document.createElement("span");
  ts.className = "msg-ts";
  ts.textContent = tsFormat(msg.ts);
  const dir = document.createElement("span");
  dir.className = "msg-dir";
  dir.textContent = arrowFor(msg.dir);
  const body = document.createElement("span");
  body.className = "msg-body";
  const parsed = safeJson(msg.text);
  if (parsed && typeof parsed === "object" && parsed.type) {
    const t = String(parsed.type);
    const color = TYPE_COLORS[t] || "#19ff66";
    const typeSpan = document.createElement("span");
    typeSpan.className = "msg-type";
    typeSpan.style.color = color;
    if (elShowTypes.checked) {
      typeSpan.textContent = "[" + t + "]";
    }
    body.appendChild(typeSpan);
    // T0: surface the `kind` tag (for `update`) and `schemaVersion`
    // (for `world`) inline so the user can see at a glance which
    // aspect of the player the message is about, or which schema
    // version the server is speaking.
    const tag = metaTag(parsed);
    if (tag && elShowTypes.checked && META_COLORS[tag]) {
      const metaSpan = document.createElement("span");
      metaSpan.className = "msg-meta";
      metaSpan.style.color = META_COLORS[tag];
      metaSpan.textContent = "[" + tag + "]";
      body.appendChild(metaSpan);
    }
    body.appendChild(document.createTextNode(JSON.stringify(parsed)));
  } else {
    body.textContent = msg.text;
  }
  div.appendChild(ts);
  div.appendChild(dir);
  div.appendChild(body);
  return div;
}

function appendMessages(messages) {
  if (!messages.length) return;
  const empty = elLog.querySelector(".empty");
  if (empty) empty.remove();
  const frag = document.createDocumentFragment();
  for (const m of messages) {
    if (!messageMatchesFilter(m)) continue;
    frag.appendChild(renderMessage(m));
  }
  elLog.appendChild(frag);
  elLogCount.textContent = elLog.children.length + " lines";
  if (elAutoscroll.checked) {
    elLog.scrollTop = elLog.scrollHeight;
  }
}

function setConnected(c) {
  connected = c;
  elStatus.textContent = c ? "CONNECTED" : "DISCONNECTED";
  elStatus.classList.toggle("connected", c);
  elStatus.classList.toggle("disconnected", !c);
  elConnectBtn.disabled = c;
  elDisconnectBtn.disabled = !c;
  elSendBtn.disabled = !c;
}

async function postJson(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {})
  });
  return await resp.json();
}

async function pollLoop() {
  while (true) {
    try {
      const r = await fetch("/messages?since=" + lastSeq);
      if (r.ok) {
        const data = await r.json();
        appendMessages(data.messages);
        if (data.messages.length) {
          lastSeq = data.messages[data.messages.length - 1].seq;
        }
      }
    } catch (e) { /* network blip, retry */ }
    try {
      const sr = await fetch("/status");
      if (sr.ok) {
        const s = await sr.json();
        setConnected(!!s.connected);
      }
    } catch (e) { /* ignore */ }
    await new Promise((r) => setTimeout(r, 250));
  }
}

function renderSendFields() {
  const t = elSendType.value;
  elSendFields.innerHTML = "";
  if (t === "hello" || t === "get_snapshot") {
    elSendFields.innerHTML = '<label>No extra fields. Sends <code>{"type":"' + t + '"}</code>.</label>';
  } else if (t === "auth") {
    elSendFields.innerHTML =
      '<label>Password</label>' +
      '<input name="password" type="password" autocomplete="off" value="' + escapeAttr(cachedPassword) + '" placeholder="companion_password">';
  } else if (t === "cmd") {
    elSendFields.innerHTML =
      '<div class="row" style="width:100%">' +
        '<div class="field"><label>Id</label><input name="id" value="1" type="number" step="1"></div>' +
        '<div class="field"><label>Name</label>' +
          '<select name="name" id="cmd-name">' +
            '<option value="ping">ping</option>' +
            '<option value="get_snapshot">get_snapshot</option>' +
            '<option value="__custom__">custom...</option>' +
          '</select>' +
        '</div>' +
        '<div class="field wide"><label>Args (JSON object, optional)</label><input name="args" value="{}" placeholder="{}"></div>' +
      '</div>' +
      '<div class="field" id="cmd-custom-wrap" style="display:none; margin-top:8px"><label>Custom name</label><input name="custom_name"></div>';
  } else if (t === "raw") {
    elSendFields.innerHTML =
      '<label>Raw JSON line (newline appended automatically)</label>' +
      '<textarea name="raw" placeholder="&#123;"type":"foo","x":1&#125;"></textarea>';
  }
  const sel = document.getElementById("cmd-name");
  if (sel) {
    sel.addEventListener("change", () => {
      const w = document.getElementById("cmd-custom-wrap");
      w.style.display = sel.value === "__custom__" ? "" : "none";
    });
  }
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

async function onConnectSubmit(e) {
  e.preventDefault();
  const fd = new FormData(elConnectForm);
  cachedPassword = fd.get("password") || "";
  elConnectBtn.disabled = true;
  const resp = await postJson("/connect", {
    host: fd.get("host"),
    port: parseInt(fd.get("port"), 10),
    password: cachedPassword,
    send_hello: !!fd.get("send_hello")
  });
  if (!resp.ok) {
    alert("Connect failed: " + (resp.error || "unknown"));
    elConnectBtn.disabled = false;
  }
}

async function onDisconnectClick() {
  await postJson("/disconnect", {});
}

async function onSendSubmit(e) {
  e.preventDefault();
  const t = elSendType.value;
  let body = {};
  if (t === "hello" || t === "get_snapshot") {
    body.payload = { type: t };
  } else if (t === "auth") {
    const fd = new FormData(elSendFields);
    body.payload = { type: "auth", password: fd.get("password") || "" };
  } else if (t === "cmd") {
    const fd = new FormData(elSendFields);
    let name = fd.get("name");
    if (name === "__custom__") name = fd.get("custom_name") || "";
    let args = {};
    const rawArgs = (fd.get("args") || "").trim();
    if (rawArgs && rawArgs !== "{}") {
      try { args = JSON.parse(rawArgs); }
      catch (err) {
        alert("Args is not valid JSON: " + err.message);
        return;
      }
    }
    body.payload = { type: "cmd", id: parseInt(fd.get("id"), 10) || 0, name: name, args: args };
  } else if (t === "raw") {
    const fd = new FormData(elSendFields);
    body.raw = fd.get("raw") || "";
  }
  const resp = await postJson("/send", body);
  if (!resp.ok) {
    alert("Send failed: " + (resp.error || "unknown"));
  }
}

async function onClearClick() {
  await postJson("/clear", {});
  elLog.innerHTML = '<div class="empty">// log cleared</div>';
  elLogCount.textContent = "0 lines";
  lastSeq = 0;
}

elConnectForm.addEventListener("submit", onConnectSubmit);
elDisconnectBtn.addEventListener("click", onDisconnectClick);
elSendForm.addEventListener("submit", onSendSubmit);
elSendType.addEventListener("change", renderSendFields);
elClearBtn.addEventListener("click", onClearClick);
elFilterMode.addEventListener("change", () => {
  elFilterValue.disabled = elFilterMode.value === "off";
  elFilterValue.value = "";
  onClearClick();
});
elFilterValue.addEventListener("input", async () => {
  // Re-render the log from scratch on every keystroke. The buffer
  // holds all messages; filtering just hides the ones that don't match.
  elLog.innerHTML = "";
  try {
    const r = await fetch("/messages/all");
    if (r.ok) {
      const data = await r.json();
      if (!data.messages.length) {
        elLog.innerHTML = '<div class="empty">// no traffic yet - press Connect</div>';
        elLogCount.textContent = "0 lines";
        return;
      }
      appendMessages(data.messages);
    }
  } catch (e) { /* network blip, ignore */ }
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && connected) onDisconnectClick();
});

renderSendFields();
pollLoop();
</script>
</body>
</html>
"""


class DebugWebHandler(BaseHTTPRequestHandler):
    server_version = "CompanionTermlink/0.1"
    client = None
    buffer = None

    def log_message(self, fmt, *args):
        return

    def _send(self, status, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj, status=200):
        self._send(status, json.dumps(obj), "application/json; charset=utf-8")

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            return {"_error": str(e)}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
            return
        if path == "/messages":
            qs = parse_qs(urlparse(self.path).query)
            try:
                since = int(qs.get("since", ["0"])[0])
            except ValueError:
                since = 0
            new, next_seq = self.buffer.since(since)
            self._send_json({"messages": new, "next_seq": next_seq})
            return
        if path == "/messages/all":
            # Replay the entire log (used by the JS filter re-render).
            # Bounded by MAX_MESSAGES, so this is cheap.
            self._send_json({"messages": self.buffer.all()})
            return
        if path == "/status":
            self._send_json({"connected": self.client.is_connected()})
            return
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()
        if isinstance(body, dict) and "_error" in body:
            self._send_json({"ok": False, "error": "invalid json: " + body["_error"]}, 400)
            return
        if path == "/connect":
            host = body.get("host") or DEFAULT_GAME_HOST
            try:
                port = int(body.get("port") or DEFAULT_GAME_PORT)
            except (TypeError, ValueError):
                self._send_json({"ok": False, "error": "invalid port"})
                return
            password = body.get("password") or ""
            send_hello = bool(body.get("send_hello", True))
            ok, err = self.client.connect(host, port, password, send_hello)
            self._send_json({"ok": ok, "error": None if ok else err})
            return
        if path == "/disconnect":
            self.client.disconnect()
            self._send_json({"ok": True})
            return
        if path == "/send":
            if not self.client.is_connected():
                self._send_json({"ok": False, "error": "not connected"})
                return
            if "raw" in body and body["raw"] is not None:
                ok, err = self.client.send_raw(body["raw"])
            elif "payload" in body and body["payload"] is not None:
                ok, err = self.client.send_dict(body["payload"])
            else:
                self._send_json({"ok": False, "error": "missing payload or raw"})
                return
            self._send_json({"ok": ok, "error": None if ok else err})
            return
        if path == "/clear":
            self.buffer.clear()
            self._send_json({"ok": True})
            return
        self._send(404, "not found", "text/plain; charset=utf-8")


def make_handler():
    return DebugWebHandler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--web-host", default=DEFAULT_WEB_HOST, help="HTTP bind host (default 127.0.0.1)")
    parser.add_argument("--web-port", type=int, default=DEFAULT_WEB_PORT, help="HTTP bind port (default 8080)")
    args = parser.parse_args(argv)

    buffer_ = MessageBuffer()
    client = CompanionClient(buffer_)
    DebugWebHandler.client = client
    DebugWebHandler.buffer = buffer_

    httpd = ThreadingHTTPServer((args.web_host, args.web_port), make_handler())
    url = f"http://{args.web_host}:{args.web_port}/"
    print(f"[termlink] serving on {url}", flush=True)
    print(f"[termlink] point at game on {DEFAULT_GAME_HOST}:{DEFAULT_GAME_PORT}", flush=True)
    print("[termlink] Ctrl-C to quit", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[termlink] shutting down", flush=True)
    finally:
        client.disconnect()
        httpd.server_close()


if __name__ == "__main__":
    main()
