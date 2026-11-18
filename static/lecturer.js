// Lecturer dashboard: QR + live attendance, polls, questions, AI summary, homework review, reports.
let sid = null;
let session = null;
let es = null;
let qrTimer = null;
let lastUrl = null;
let studentBase = "";      // the address phones use to reach this server
let geoAccuracy = null;    // how well this laptop knows its own position (metres)
let polls = [];
const comments = new Map();

// ---- login / sessions ---------------------------------------------------
async function boot() {
  applyI18n();
  const me = await api("GET", "/api/me");
  show("#loginCard", !me.lecturer);
  if (!me.lecturer) return;
  $("#headerSub").textContent = t(me.llm ? "l.ai.on" : "l.ai.off");
  await loadSessions();
}

$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { await api("POST", "/api/login", { pin: $("#pin").value }); boot(); }
  catch (err) { showMsg($("#loginMsg"), errText(err), "err"); }
});

async function loadSessions(selectId) {
  const list = await api("GET", "/api/sessions");
  const pick = $("#sessionPicker");
  put(pick, h("option", { value: "" }, t("l.new")),
    list.map((s) => h("option", { value: s.id }, `${s.title}${s.is_active ? t("l.live") : ""}`)));
  show("#sessionPicker", list.length > 0);
  const chosen = selectId ?? list.find((s) => s.is_active)?.id ?? "";
  pick.value = chosen;
  openSession(list.find((s) => s.id === chosen));
}
$("#sessionPicker").addEventListener("change", () => loadSessions($("#sessionPicker").value));

$("#startForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const s = await api("POST", "/api/sessions", { title: $("#title").value });
    $("#title").value = "";
    loadSessions(s.id);
  } catch (err) { showMsg($("#startMsg"), errText(err), "err"); }
});

$("#endBtn").addEventListener("click", async () => {
  if (!confirm(t("l.end.confirm"))) return;
  await api("POST", `/api/sessions/${sid}/end`);
  loadSessions(sid);
});

async function openSession(s) {
  es?.close(); clearInterval(qrTimer);
  comments.clear(); polls = []; lastUrl = null;
  session = s || null;
  sid = session?.id || null;
  show("#home", !sid);
  show("#dash", !!sid);
  show("#endBtn", !!session?.is_active);
  if (!sid) return loadCourse();

  show("#qrCard", session.is_active);
  $("#xlsxLink").href = `/api/sessions/${sid}/report.xlsx?lang=${LANG}`;
  $("#csvLink").href = `/api/sessions/${sid}/attendance.csv?lang=${LANG}`;
  $("#hwTask").value = session.homework_task;
  $("#trText").value = "";
  for (const id of ["#sumMsg", "#hwMsg", "#attMsg", "#pollMsg", "#geoMsg"]) showMsg($(id), "");
  show("#hwOut", false);
  HeadCount.reset();
  renderSummary();
  renderGeo();
  (await api("GET", `/api/sessions/${sid}/comments`)).forEach((c) => comments.set(c.id, c));
  polls = await api("GET", `/api/sessions/${sid}/polls`);
  renderComments(); renderPolls(); refreshAttendance(); loadHomework();
  if (session.is_active) { refreshQr(); qrTimer = setInterval(refreshQr, 1000); }

  es = live(sid, {
    attendance: refreshAttendance,   // the event carries no names; the list is fetched with the lecturer cookie
    comment: (c) => { comments.set(c.id, c); renderComments(); },
    poll: (p) => { polls = polls.filter((x) => x.id !== p.id).concat(p); renderPolls(); },
    homework: loadHomework,
  });
}

// ---- QR and typed code ----------------------------------------------------
async function refreshQr() {
  try {
    const q = await api("GET", `/api/sessions/${sid}/qr`);
    $("#countBar").style.width = `${(q.expires_in / q.period) * 100}%`;
    if (q.url === lastUrl) return;
    lastUrl = q.url;
    const firstTime = !studentBase;
    studentBase = q.base;
    const qr = qrcode(0, "M"); qr.addData(q.url); qr.make();
    $("#qr").innerHTML = qr.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
    $("#noCamText").textContent = t("l.qr.nocam", { url: q.base.replace(/^https?:\/\//, "") });
    $("#qrCode").textContent = `${q.code.slice(0, 3)} ${q.code.slice(3)}`;
    if (firstTime) renderGeo();
  } catch (e) {
    if (e.status === 401) location.reload();  // the server restarted: back to the login screen
  }
}
function setFullscreen(on) {
  $("#qrCard").classList.toggle("fullscreen", on);
  $("#fsBtn").textContent = t(on ? "l.qr.exit" : "l.qr.full");
}
$("#fsBtn").addEventListener("click", () => setFullscreen(!$("#qrCard").classList.contains("fullscreen")));
addEventListener("keydown", (e) => e.key === "Escape" && setFullscreen(false));

// ---- location check -------------------------------------------------------
function laptopLocation() {
  return new Promise((resolve, reject) => {
    if (!window.isSecureContext || !navigator.geolocation) return reject(new Error("geo"));
    navigator.geolocation.getCurrentPosition((p) => resolve(p.coords), () => reject(new Error("geo")),
      { enableHighAccuracy: true, timeout: 15000 });
  });
}

function renderGeo() {
  $("#geoMode").value = session.geo_mode;
  if (session.geo_radius) $("#geoRadius").value = session.geo_radius;
  if (session.geo_mode === "off") return showMsg($("#geoMsg"), "");
  put($("#geoMsg"),
    h("div", { class: "msg ok" }, t("l.geo.on", { r: session.geo_radius, a: geoAccuracy ?? "?" })),
    studentBase && !studentBase.startsWith("https://") && h("div", { class: "msg warn" }, t("l.geo.https", { url: studentBase })));
}

async function applyGeo() {
  const mode = $("#geoMode").value;
  try {
    let body = { mode };
    if (mode !== "off") {
      const pos = await laptopLocation();
      geoAccuracy = Math.round(pos.accuracy);
      body = { mode, lat: pos.latitude, lon: pos.longitude, radius: Number($("#geoRadius").value) || 150 };
    }
    session = await api("POST", `/api/sessions/${sid}/geofence`, body);
    renderGeo();
  } catch (e) {
    $("#geoMode").value = session.geo_mode;
    showMsg($("#geoMsg"), e.message === "geo" ? t("l.geo.fail") : errText(e), "err");
  }
}
$("#geoMode").addEventListener("change", applyGeo);
$("#geoRadius").addEventListener("change", () => session.geo_mode !== "off" && applyGeo());

// ---- attendance ---------------------------------------------------------
async function refreshAttendance() {
  const rows = await api("GET", `/api/sessions/${sid}/attendance`);
  $("#presentCount").textContent = rows.length;
  HeadCount.render();
  const badge = (text, kind = "", title) => h("span", { class: `badge ${kind}`, title }, text);
  put($("#attBody"), rows.map((a, i) => h("tr", {},
    h("td", {}, i + 1),
    h("td", { dir: "ltr" }, a.student_id),
    h("td", {}, a.name, " ",
      a.status === "late" && badge(t("l.att.late"), "warn"),
      a.method === "manual" && badge(t("l.att.manual")),
      a.method === "code" && badge(t("l.att.code")),
      a.geo === "far" && badge(t("l.att.far", { m: a.distance_m }), "bad"),
      a.geo === "none" && badge(t("l.att.noloc"), "warn"),
      a.shared_ip && badge("⚠", "bad", t("l.att.sameip"))),
    h("td", {}, fmtTime(a.checked_in_at)),
    h("td", {}, h("button", { class: "small ghost", "aria-label": "remove", onclick: () => removeStudent(a) }, "✕")))));
}

async function removeStudent(a) {
  if (!confirm(t("l.att.remove", { name: a.name }))) return;
  try { await api("POST", `/api/sessions/${sid}/attendance/${a.student_id}/remove`); refreshAttendance(); }
  catch (e) { showMsg($("#attMsg"), errText(e), "err"); }
}

$("#addForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("POST", `/api/sessions/${sid}/attendance`, { student_id: $("#addId").value, name: $("#addName").value });
    $("#addId").value = $("#addName").value = "";
    showMsg($("#attMsg"), "");
    refreshAttendance();
  } catch (err) { showMsg($("#attMsg"), errText(err), "err"); }
});

// ---- polls --------------------------------------------------------------
document.querySelectorAll("[data-tpl]").forEach((b) => b.addEventListener("click", () => {
  const [q, ...opts] = t(b.dataset.tpl + ".data").split("|");
  $("#pollQ").value = q; $("#pollOpts").value = opts.join("\n");
}));

$("#pollForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("POST", `/api/sessions/${sid}/polls`, { question: $("#pollQ").value, options: $("#pollOpts").value.split("\n") });
    showMsg($("#pollMsg"), "");
    polls = await api("GET", `/api/sessions/${sid}/polls`); renderPolls();
  } catch (err) { showMsg($("#pollMsg"), errText(err), "err"); }
});

function renderPolls() {
  const latest = [...polls].sort((a, b) => b.created_at - a.created_at || b.id - a.id)[0];
  if (!latest) return put($("#pollLive"));
  put($("#pollLive"),
    h("h3", {}, latest.question, " ",
      h("span", { class: "muted" }, t("l.poll.votes", { n: latest.total_votes }) + (latest.is_open ? "" : ` · ${t("l.poll.closed")}`))),
    pollBars(latest),
    latest.is_open && h("button", { onclick: () => api("POST", `/api/polls/${latest.id}/close`).catch(() => {}) }, t("l.poll.close")));
}

// ---- comments -----------------------------------------------------------
async function moderate(c, change) {
  try { const u = await api("POST", `/api/comments/${c.id}/moderate`, change); comments.set(u.id, u); renderComments(); }
  catch (e) { alert(errText(e)); }
}

function renderComments() {
  const list = [...comments.values()].sort((a, b) =>
    a.hidden - b.hidden || a.answered - b.answered || b.upvotes - a.upvotes || b.created_at - a.created_at);
  const visible = list.filter((c) => !c.hidden).length;
  $("#commentCount").textContent = visible ? `(${visible})` : "";
  if (!list.length) return put($("#comments"), h("p", { class: "muted" }, t("l.c.none")));
  put($("#comments"), list.map((c) =>
    h("div", { class: "comment" + (c.answered ? " answered" : "") + (c.hidden ? " hiddenc" : "") },
      h("div", { class: "body", dir: "auto" }, c.text, h("div", { class: "meta" }, `${authorName(c)} · ${fmtTime(c.created_at)} · ▲ ${c.upvotes}`)),
      h("div", { class: "actions" },
        !c.hidden && h("button", { class: "small" + (c.answered ? " active" : ""), onclick: () => moderate(c, { answered: !c.answered }) }, `✓ ${t("l.c.answer")}`),
        h("button", { class: "small ghost", onclick: () => moderate(c, { hidden: !c.hidden }) }, t(c.hidden ? "l.c.show" : "l.c.hide"))))));
}

// ---- AI: summary --------------------------------------------------------
function renderSummary() {
  show("#sumBox", !!session.summary);
  $("#sumOut").value = session.summary;
  $("#shareBtn").textContent = t(session.summary_published ? "l.sum.unshare" : "l.sum.share");
  $("#shareBtn").className = session.summary_published ? "" : "primary";
}

$("#trFile").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (f) $("#trText").value = await f.text();
});

$("#sumBtn").addEventListener("click", async () => {
  const btn = $("#sumBtn"); btn.disabled = true;
  showMsg($("#sumMsg"), t("l.sum.working"), "warn");
  try {
    const r = await api("POST", "/api/summary", { transcript: $("#trText").value, session_id: sid, lang: LANG });
    session.summary = r.summary; session.summary_published = false;
    renderSummary();
    showMsg($("#sumMsg"), r.note ? t("l.sum.fallback") : t("l.sum.done", { method: r.method, words: r.words }), r.note ? "warn" : "ok");
  } catch (err) { showMsg($("#sumMsg"), errText(err), "err"); }
  btn.disabled = false;
});

$("#shareBtn").addEventListener("click", async () => {
  try {
    session = await api("POST", `/api/sessions/${sid}/summary`, { summary: $("#sumOut").value, published: !session.summary_published });
    renderSummary();
    showMsg($("#sumMsg"), session.summary_published ? t("l.sum.shared") : "", "ok");
  } catch (err) { showMsg($("#sumMsg"), errText(err), "err"); }
});

// ---- AI: homework -------------------------------------------------------
$("#taskForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    session = await api("POST", `/api/sessions/${sid}/homework-task`, { task: $("#hwTask").value });
    showMsg($("#hwMsg"), t("l.hw.saved"), "ok");
  } catch (err) { showMsg($("#hwMsg"), errText(err), "err"); }
});

async function loadHomework() {
  if (!sid) return;
  const o = await api("GET", `/api/sessions/${sid}/homework`);
  if (!o.students.length) return put($("#hwOverview"), h("p", { class: "muted" }, t("l.hw.none")));
  const flagged = new Set(o.flagged_pairs.flatMap((p) => [p.a, p.b]));
  put($("#hwOverview"),
    o.flagged_pairs.length > 0 && h("div", { class: "msg err" }, t("l.hw.flag") +
      o.flagged_pairs.map((p) => `${p.a} ↔ ${p.b} (${Math.round(p.similarity * 100)}%)`).join(", ")),
    h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, t("l.hw.student")), h("th", {}, t("l.hw.words")), h("th", {}))),
      h("tbody", {}, o.students.map((s) => h("tr", {},
        h("td", {}, `${s.name} (${s.student_id})`, flagged.has(s.student_id) && " ⚠"),
        h("td", {}, s.words),
        h("td", { class: "actions" },
          h("button", { class: "small", onclick: () => reviewStudent(s.student_id) }, t("l.hw.review")),
          h("button", { class: "small ghost", onclick: () => deleteSubmission(s) }, t("l.hw.delete"))))))));
}
$("#hwRefresh").addEventListener("click", loadHomework);

async function reviewStudent(studentId) {
  showMsg($("#hwMsg"), t("l.hw.working", { id: studentId }), "warn");
  try {
    const r = await api("POST", `/api/sessions/${sid}/homework/${studentId}/review`, { lang: LANG });
    const c = r.comparison;
    showMsg($("#hwMsg"), t("l.hw.result", { id: studentId, words: c.words, avg: c.class_avg_words,
      other: c.most_similar_to ?? "-", p: Math.round(c.max_similarity * 100), method: r.method }), c.possible_copy ? "err" : "ok");
    $("#hwOut").textContent = r.review; show("#hwOut");
  } catch (err) { showMsg($("#hwMsg"), errText(err), "err"); }
}

async function deleteSubmission(s) {
  if (!confirm(t("l.hw.delete.confirm", { name: s.name }))) return;
  try { await api("POST", `/api/sessions/${sid}/homework/${s.student_id}/delete`); show("#hwOut", false); loadHomework(); }
  catch (err) { showMsg($("#hwMsg"), errText(err), "err"); }
}

// ---- all classes (course report) ------------------------------------------
async function loadCourse() {
  $("#courseXlsx").href = `/api/course/attendance.xlsx?lang=${LANG}`;
  const m = await api("GET", "/api/course/attendance");
  show("#courseXlsx", m.sessions.length > 0);
  if (!m.sessions.length) return put($("#course"), h("p", { class: "muted" }, t("l.course.none")));
  put($("#course"), h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, t("l.att.id")), h("th", {}, t("l.att.name")),
      m.sessions.map((s) => h("th", {},
        h("button", { class: "small ghost", title: t("l.course.open"), onclick: () => loadSessions(s.id) }, `${s.date.slice(5)} ${s.title}`),
        h("div", { class: "muted" }, s.count))),
      h("th", {}, t("l.course.present")), h("th", {}, "%"))),
    h("tbody", {}, m.students.map((st) => h("tr", {},
      h("td", { dir: "ltr" }, st.student_id), h("td", {}, st.name),
      st.marks.map((x) => h("td", { class: "center" }, x === "late" ? h("span", { class: "badge warn" }, t("l.att.late")) : x ? "✓" : "")),
      h("td", { class: "center" }, st.present), h("td", { class: "center" }, `${st.percent}%`))))));
}

boot();
