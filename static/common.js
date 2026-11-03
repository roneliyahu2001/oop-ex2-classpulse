// Shared helpers for the student and lecturer pages. No framework on purpose (KISS).
const $ = (sel) => document.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) el.append(c instanceof Node ? c : String(c));
  return el;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const err = new Error(data?.message || res.statusText);
    err.code = data?.error;
    err.status = res.status;
    throw err;
  }
  return data;
}

function store(key, value) {
  try {
    if (value === undefined) return JSON.parse(localStorage.getItem(key));
    localStorage.setItem(key, JSON.stringify(value));
  } catch { return null; }
}

// Like replaceChildren, but skips null/undefined (used for optional parts).
function put(el, ...kids) {
  el.replaceChildren(...kids.flat().filter((k) => k != null));
}

function showMsg(el, text, kind = "ok") {
  el.replaceChildren(text ? h("div", { class: `msg ${kind}` }, text) : "");
}

// Server-Sent Events with automatic reconnect (EventSource reconnects by itself).
function live(sessionId, handlers) {
  const es = new EventSource(`/api/sessions/${sessionId}/events`);
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  }
  return es;
}

function pollBars(poll, { onVote, myVote } = {}) {
  const total = poll.total_votes || 0;
  return poll.options.map((opt, i) => {
    const pct = total ? Math.round((poll.votes[i] / total) * 100) : 0;
    const showResults = !onVote || myVote != null || !poll.is_open;
    return h("button", {
      class: "option", disabled: !onVote || myVote != null || !poll.is_open ? true : false,
      onclick: () => onVote && onVote(i),
    },
      showResults ? h("div", { class: "fill", style: `width:${pct}%` }) : null,
      h("span", {}, (myVote === i ? "✓ " : "") + opt),
      showResults ? h("span", { class: "pct" }, `${pct}% (${poll.votes[i]})`) : null,
    );
  });
}

const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
