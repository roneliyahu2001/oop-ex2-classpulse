// Shared helpers for the student and lecturer pages. No framework on purpose (KISS).
const $ = (sel) => document.querySelector(sel);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}

// Like replaceChildren, but skips null/undefined/false (used for optional parts).
function put(el, ...kids) {
  el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
}

const show = (sel, on = true) => $(sel).classList.toggle("hidden", !on);

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

// ---- language -------------------------------------------------------------
const LANG = store("cp_lang") || ((navigator.language || "en").toLowerCase().startsWith("he") ? "he" : "en");

function t(key, vars = {}) {
  let s = I18N[LANG][key] ?? I18N.en[key] ?? key;
  for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}

// Server errors carry a stable code; a failed fetch (no status) means the network is down.
function errText(e) {
  if (!e.status) return t("err.network");
  return I18N[LANG]["err." + e.code] ? t("err." + e.code) : e.message;
}

function applyI18n() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === "he" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-ph]").forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  const btn = $("#langBtn");
  if (btn) {
    btn.textContent = LANG === "he" ? "English" : "עברית";
    btn.onclick = () => { store("cp_lang", LANG === "he" ? "en" : "he"); location.reload(); };
  }
}

function showMsg(el, text, kind = "ok") {
  el.replaceChildren(text ? h("div", { class: `msg ${kind}`, role: "status" }, text) : "");
}

// Server-Sent Events. EventSource reconnects by itself when the network drops.
function live(sessionId, handlers) {
  const es = new EventSource(`/api/sessions/${sessionId}/events`);
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (e) => fn(JSON.parse(e.data)));
  }
  return es;
}

function pollBars(poll, { onVote, myVote } = {}) {
  const total = poll.total_votes || 0;
  const locked = !onVote || myVote != null || !poll.is_open;
  return poll.options.map((opt, i) => {
    const pct = total ? Math.round((poll.votes[i] / total) * 100) : 0;
    return h("button", { class: "option", disabled: locked, onclick: () => onVote && onVote(i) },
      locked && h("div", { class: "fill", style: `width:${pct}%` }),
      h("span", { dir: "auto" }, (myVote === i ? "✓ " : "") + opt),
      locked && h("span", { class: "pct" }, `${pct}% (${poll.votes[i]})`));
  });
}

const authorName = (c) => (c.author === "Anonymous" ? t("c.anon") : c.author);
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString(LANG === "he" ? "he-IL" : "en-GB",
  { hour: "2-digit", minute: "2-digit" });
