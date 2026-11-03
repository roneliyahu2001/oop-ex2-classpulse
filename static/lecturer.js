// Lecturer dashboard: QR + live attendance, polls, comments, AI summary and homework review.
let sid = null;
let es = null;
let qrTimer = null;
const attendance = new Map();
const comments = new Map();
let polls = [];

// ---- login / sessions ---------------------------------------------------
async function boot() {
  const me = await api("GET", "/api/me");
  if (!me.lecturer) return $("#loginCard").classList.remove("hidden");
  $("#loginCard").classList.add("hidden");
  $("#headerSub").textContent = me.llm ? "AI: Claude API" : "AI: offline mode";
  await loadSessions();
}

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("POST", "/api/login", { pin: $("#pin").value }); boot(); }
  catch (err) { showMsg($("#loginMsg"), err.message, "err"); }
});

async function loadSessions(selectId) {
  const list = await api("GET", "/api/sessions");
  const pick = $("#sessionPicker");
  pick.replaceChildren(h("option", { value: "" }, "+ New class"),
    ...list.map((s) => h("option", { value: s.id }, `${s.title}${s.is_active ? " (live)" : ""}`)));
  const chosen = selectId ?? list.find((s) => s.is_active)?.id ?? "";
  pick.value = chosen;
  openSession(chosen, list.find((s) => s.id === chosen));
}
$("#sessionPicker").addEventListener("change", () => loadSessions($("#sessionPicker").value));

$("#startForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const s = await api("POST", "/api/sessions", { title: $("#title").value });
  $("#title").value = "";
  loadSessions(s.id);
});

$("#endBtn").addEventListener("click", async () => {
  if (!confirm("End this class? Students will no longer be able to check in.")) return;
  await api("POST", `/api/sessions/${sid}/end`);
  loadSessions(sid);
});

async function openSession(id, session) {
  es?.close(); clearInterval(qrTimer);
  attendance.clear(); comments.clear(); polls = [];
  sid = id || null;
  $("#startCard").classList.toggle("hidden", !!sid);
  $("#dash").classList.toggle("hidden", !sid);
  $("#endBtn").classList.toggle("hidden", !session?.is_active);
  if (!sid) return;

  $("#qrCard").classList.toggle("hidden", !session.is_active);
  $("#csvLink").href = `/api/sessions/${sid}/attendance.csv`;
  (await api("GET", `/api/sessions/${sid}/attendance`)).forEach((a) => attendance.set(a.student_id, a));
  (await api("GET", `/api/sessions/${sid}/comments`)).forEach((c) => comments.set(c.id, c));
  polls = await api("GET", `/api/sessions/${sid}/polls`);
  renderAttendance(); renderComments(); renderPolls(); loadHomework();
  if (session.is_active) { refreshQr(); qrTimer = setInterval(refreshQr, 1000); }

  es = live(sid, {
    attendance: (a) => { attendance.set(a.student_id, a); renderAttendance(); },
    comment: (c) => { comments.set(c.id, c); renderComments(); },
    poll: (p) => { polls = polls.filter((x) => x.id !== p.id).concat(p); renderPolls(); },
  });
}

// ---- QR -----------------------------------------------------------------
let lastUrl = null;
async function refreshQr() {
  try {
    const { url, expires_in, period } = await api("GET", `/api/sessions/${sid}/qr`);
    $("#countBar").style.width = `${(expires_in / period) * 100}%`;
    if (url === lastUrl) return;
    lastUrl = url;
    const qr = qrcode(0, "M"); qr.addData(url); qr.make();
    $("#qr").innerHTML = qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
    $("#qrUrl").textContent = url.split("&t=")[0];
  } catch { /* transient; next tick retries */ }
}
$("#fsBtn").addEventListener("click", () => $("#qrCard").classList.toggle("fullscreen"));
addEventListener("keydown", (e) => e.key === "Escape" && $("#qrCard").classList.remove("fullscreen"));

// ---- attendance ---------------------------------------------------------
function renderAttendance() {
  const rows = [...attendance.values()].sort((a, b) => a.checked_in_at - b.checked_in_at);
  $("#presentCount").textContent = rows.length;
  $("#attBody").replaceChildren(...rows.map((a, i) =>
    h("tr", {}, h("td", {}, i + 1), h("td", {}, a.student_id), h("td", {}, a.name), h("td", {}, fmtTime(a.checked_in_at)))));
}

// ---- polls --------------------------------------------------------------
document.querySelectorAll("[data-tpl]").forEach((b) => b.addEventListener("click", () => {
  const [q, ...opts] = b.dataset.tpl.split("|");
  $("#pollQ").value = q; $("#pollOpts").value = opts.join("\n");
}));

$("#pollForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("POST", `/api/sessions/${sid}/polls`, { question: $("#pollQ").value, options: $("#pollOpts").value.split("\n") });
    showMsg($("#pollMsg"), "");
    polls = await api("GET", `/api/sessions/${sid}/polls`); renderPolls();
  } catch (err) { showMsg($("#pollMsg"), err.message, "err"); }
});

function renderPolls() {
  const latest = [...polls].sort((a, b) => b.created_at - a.created_at)[0];
  if (!latest) return $("#pollLive").replaceChildren();
  put($("#pollLive"),
    h("h3", {}, latest.question, " ", h("span", { class: "muted" }, `${latest.total_votes} votes${latest.is_open ? "" : " · closed"}`)),
    ...pollBars(latest),
    latest.is_open ? h("button", { onclick: () => api("POST", `/api/polls/${latest.id}/close`) }, "Close poll") : null);
}

// ---- comments -----------------------------------------------------------
function renderComments() {
  const list = [...comments.values()].sort((a, b) => b.upvotes - a.upvotes || b.created_at - a.created_at);
  $("#commentCount").textContent = list.length ? `(${list.length})` : "";
  if (!list.length) return $("#comments").replaceChildren(h("p", { class: "muted" }, "No comments yet."));
  $("#comments").replaceChildren(...list.map((c) =>
    h("div", { class: "comment" },
      h("div", { class: "body" }, c.text, h("div", { class: "meta" }, `${c.author} · ${fmtTime(c.created_at)}`)),
      h("span", { class: "stat" }, `▲ ${c.upvotes}`))));
}

// ---- AI: summary --------------------------------------------------------
$("#trFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (f) $("#trText").value = await f.text();
});
$("#sumBtn").addEventListener("click", async () => {
  const btn = $("#sumBtn"); btn.disabled = true;
  showMsg($("#sumMsg"), "Summarising…", "warn");
  try {
    const r = await api("POST", "/api/summary", { transcript: $("#trText").value });
    showMsg($("#sumMsg"), r.note || `Done (${r.method}, ${r.words} words)`, r.note ? "warn" : "ok");
    $("#sumOut").textContent = r.summary; $("#sumOut").classList.remove("hidden");
  } catch (err) { showMsg($("#sumMsg"), err.message, "err"); }
  btn.disabled = false;
});

// ---- AI: homework -------------------------------------------------------
async function loadHomework() {
  if (!sid) return;
  const o = await api("GET", `/api/sessions/${sid}/homework`);
  if (!o.students.length) return $("#hwOverview").replaceChildren(h("p", { class: "muted" }, "No submissions yet."));
  const flagged = new Set(o.flagged_pairs.flatMap((p) => [p.a, p.b]));
  put($("#hwOverview"),
    o.flagged_pairs.length ? h("div", { class: "msg err" }, "Possible copying: " +
      o.flagged_pairs.map((p) => `${p.a} ↔ ${p.b} (${Math.round(p.similarity * 100)}%)`).join(", ")) : null,
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Student"), h("th", {}, "Words"), h("th", {}, ""))),
      h("tbody", {}, o.students.map((s) => h("tr", {},
        h("td", {}, `${s.name} (${s.student_id})`, flagged.has(s.student_id) ? " ⚠" : ""),
        h("td", {}, s.words),
        h("td", {}, h("button", { onclick: () => reviewStudent(s.student_id) }, "Review")))))));
}
$("#hwRefresh").addEventListener("click", loadHomework);

async function reviewStudent(studentId) {
  showMsg($("#hwMsg"), `Reviewing ${studentId}…`, "warn");
  try {
    const r = await api("POST", `/api/sessions/${sid}/homework/${studentId}/review`, {});
    const c = r.comparison;
    showMsg($("#hwMsg"), `${studentId}: ${c.words} words, class avg ${c.class_avg_words}, ` +
      `closest match ${c.most_similar_to ?? "-"} (${Math.round(c.max_similarity * 100)}%) · ${r.method}`, c.possible_copy ? "err" : "ok");
    $("#hwOut").textContent = r.review; $("#hwOut").classList.remove("hidden");
  } catch (err) { showMsg($("#hwMsg"), err.message, "err"); }
}

boot();
