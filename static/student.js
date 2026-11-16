// Student phone app. Flow: scan the QR (or type the code) -> check in -> poll / questions / homework.
const params = new URLSearchParams(location.search);
let sessionId = params.get("s");
let token = params.get("t");
let session = null;
let currentPoll = null;
let profile = store("cp_profile") || {};
const votes = store("cp_votes2") || {};         // "session:poll" -> option index
const voteKey = (poll) => `${sessionId}:${poll.id}`;  // poll numbers restart if the database is reset
const comments = new Map();

if (token) history.replaceState(null, "", `/?s=${sessionId}`); // a reload must not reuse the token

// ---- tabs ---------------------------------------------------------------
document.querySelectorAll("[data-tab]").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll("[data-pane]").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== b.dataset.tab));
  }));

// ---- check-in -----------------------------------------------------------
function showCheckin() {
  show("#checkinCard");
  show("#codeRow", !token);
  $("#code").required = !token;
}

// The phone's position, or null when the browser can't or won't give it.
// Browsers share location only on secure pages (https, or localhost while developing).
function getLocation() {
  if (!window.isSecureContext || !navigator.geolocation) return Promise.resolve(null);
  return new Promise((resolve) => navigator.geolocation.getCurrentPosition(
    (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude, accuracy: p.coords.accuracy }),
    () => resolve(null),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }));
}

async function checkIn(studentId, name, proof) {
  const msg = $("#checkinMsg");
  const btn = $("#checkinBtn");
  btn.disabled = true;
  try {
    const body = { session_id: sessionId, token: proof, student_id: studentId, name };
    if (session.geo_mode !== "off") {
      showCheckin();
      showMsg(msg, t("s.geo.asking"), "warn");
      const pos = await getLocation();
      if (pos) Object.assign(body, pos);
      else if (session.geo_mode === "block") {
        return showMsg(msg, t(window.isSecureContext ? "s.geo.denied" : "s.geo.insecure"), "err");
      }
    }
    const rec = await api("POST", "/api/checkin", body);
    profile = { student_id: studentId, name };
    store("cp_profile", profile);
    store(`cp_in_${sessionId}`, true);
    show("#checkinCard", false);
    showMsg($("#banner"), t(rec.status === "late" ? "s.checkedLate" : "s.checked", { time: fmtTime(rec.checked_in_at) }), "ok");
    enterClass();
  } catch (e) {
    if (e.code === "ALREADY_CHECKED_IN" || e.code === "DEVICE_USED") {
      // Already counted (e.g. from another browser on this phone): no second record, but let them take part.
      show("#checkinCard", false);
      showMsg($("#banner"), errText(e), "warn");
      return enterClass();
    }
    if (e.code === "TOKEN_EXPIRED") { token = null; $("#code").value = ""; }  // offer the typed code instead
    showCheckin();
    showMsg(msg, errText(e), "err");
  } finally {
    btn.disabled = false;
  }
}

$("#checkinForm").addEventListener("submit", (e) => {
  e.preventDefault();
  checkIn($("#sid").value.trim(), $("#sname").value.trim(), token || $("#code").value);
});

// ---- polls --------------------------------------------------------------
function renderPoll(poll) {
  currentPoll = poll;
  if (!poll) {
    $("#pollQuestion").textContent = t("s.poll.none");
    return put($("#pollOptions"), h("p", { class: "muted" }, t("s.poll.wait")));
  }
  $("#pollQuestion").textContent = poll.question + (poll.is_open ? "" : t("s.poll.closed"));
  put($("#pollOptions"), pollBars(poll, { onVote: vote, myVote: votes[voteKey(poll)] }));
}

async function vote(i) {
  try {
    const p = await api("POST", `/api/polls/${currentPoll.id}/vote`, { option: i });
    votes[voteKey(p)] = i; store("cp_votes2", votes); renderPoll(p);
  } catch (e) {
    if (e.code === "ALREADY_VOTED") { votes[voteKey(currentPoll)] ??= -1; store("cp_votes2", votes); renderPoll(currentPoll); }
    showMsg($("#banner"), errText(e), "err");
  }
}

// ---- comments (with an offline outbox) -----------------------------------
function renderComments() {
  const list = [...comments.values()].sort((a, b) => b.created_at - a.created_at);
  put($("#comments"), list.map((c) =>
    h("div", { class: "comment" + (c.answered ? " answered" : "") },
      h("div", { class: "body", dir: "auto" }, c.text,
        h("div", { class: "meta" }, `${authorName(c)} · ${fmtTime(c.created_at)}`, c.answered && ` · ${t("s.c.answered")}`)),
      h("button", { class: "small", onclick: () => upvote(c.id) }, `▲ ${c.upvotes}`))));
}

function onComment(c) {
  if (c.hidden) comments.delete(c.id); else comments.set(c.id, c);
  renderComments();
}

async function upvote(id) {
  try { onComment(await api("POST", `/api/comments/${id}/upvote`)); }
  catch (e) { showMsg($("#commentMsg"), errText(e), "warn"); }
}

const outbox = () => store("cp_outbox") || [];
async function flushOutbox() {
  const pending = outbox();
  if (!pending.length) return;
  const left = [];
  for (const item of pending) {
    try { await api("POST", `/api/sessions/${item.sid}/comments`, item.body); }
    catch (e) { if (!e.status || e.status === 429) left.push(item); } // keep what may still succeed later
  }
  store("cp_outbox", left);
  if (!left.length) showMsg($("#commentMsg"), t("s.c.flushed"), "ok");
}

$("#commentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { text: $("#commentText").value, author: $("#anon").checked ? "" : (profile.name || "") };
  try {
    await api("POST", `/api/sessions/${sessionId}/comments`, body);
    showMsg($("#commentMsg"), t("s.c.sent"), "ok");
    $("#commentText").value = "";
  } catch (err) {
    if (err.status) return showMsg($("#commentMsg"), errText(err), "err");
    store("cp_outbox", [...outbox(), { sid: sessionId, body }]);
    showMsg($("#commentMsg"), t("s.c.queued"), "warn");
    $("#commentText").value = "";
  }
});
addEventListener("online", flushOutbox);
setInterval(flushOutbox, 10000);

// ---- homework -----------------------------------------------------------
$("#hwFile").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  if (f.size > 200000) return showMsg($("#hwMsg"), t("err.TOO_LARGE"), "err");
  $("#hwText").value = await f.text();
});

$("#hwSubmit").addEventListener("click", async () => {
  if (!profile.student_id) return showMsg($("#hwMsg"), t("s.hw.first"), "err");
  const btn = $("#hwSubmit"); btn.disabled = true;
  showMsg($("#hwMsg"), t("s.hw.working"), "warn");
  try {
    await api("POST", `/api/sessions/${sessionId}/homework`, { student_id: profile.student_id, name: profile.name, text: $("#hwText").value });
    const r = await api("POST", `/api/sessions/${sessionId}/homework/${profile.student_id}/review`, { lang: LANG });
    const c = r.comparison;
    showMsg($("#hwMsg"), "");
    put($("#hwResult"),
      h("div", {},
        h("span", { class: "stat" }, t("s.hw.words", { n: c.words, avg: c.class_avg_words })),
        h("span", { class: "stat" }, t("s.hw.size", { n: c.class_size })),
        h("span", { class: "stat" }, t("s.hw.overlap", { p: Math.round(c.max_similarity * 100) }))),
      c.possible_copy && h("div", { class: "msg err" }, t("s.hw.copy")),
      h("pre", { class: "out", dir: "auto" }, r.review));
  } catch (e) { showMsg($("#hwMsg"), errText(e), "err"); }
  btn.disabled = false;
});

// ---- the class view -------------------------------------------------------
function renderSession(s) {
  session = s;
  $("#sessionTitle").textContent = s.title;
  show("#hwTaskBox", !!s.homework_task);
  $("#hwTask").textContent = s.homework_task;
  show("#summaryTab", !!s.summary);
  $("#summaryText").textContent = s.summary;
  if (!s.summary && $("#summaryTab").classList.contains("active")) document.querySelector('[data-tab="poll"]').click();
  if (!s.is_active) showMsg($("#banner"), t("s.ended"), "warn");
}

let entered = false;
async function enterClass() {
  if (entered) return;
  entered = true;
  show("#classView");
  renderSession(session);
  renderPoll(currentPoll);
  try {
    (await api("GET", `/api/sessions/${sessionId}/comments`)).forEach(onComment);
    renderComments();
  } catch (e) { showMsg($("#banner"), errText(e), "err"); }
  live(sessionId, {
    poll: (p) => { if (p.is_open || p.id === currentPoll?.id) renderPoll(p); },
    comment: onComment,
    session: renderSession,
  });
  flushOutbox();
}

// Safety net for networks that hold back live streams (some proxies and tunnels do), and for
// phones that slept: re-read the class every 15 s and whenever the page becomes visible again.
async function refresh() {
  if (!entered || document.hidden) return;
  try {
    const r = await api("GET", `/api/sessions/${sessionId}`);
    renderSession(r.session);
    if (r.poll) {
      if (r.poll.id !== currentPoll?.id || r.poll.total_votes !== currentPoll.total_votes) renderPoll(r.poll);
    } else if (currentPoll?.is_open) {
      renderPoll({ ...currentPoll, is_open: false });
    }
    const list = await api("GET", `/api/sessions/${sessionId}/comments`);
    comments.clear();
    list.forEach(onComment);  // skips hidden ones, also in a browser that is logged in as the lecturer
    if (!list.length) renderComments();
  } catch { /* offline: the next round tries again */ }
}
setInterval(refresh, 15000);
document.addEventListener("visibilitychange", refresh);

// ---- boot ---------------------------------------------------------------
const setNet = () => ($("#netStatus").textContent = navigator.onLine ? "" : t("c.offline"));
addEventListener("online", setNet);
addEventListener("offline", setNet);

async function boot() {
  applyI18n();
  setNet();
  if (!sessionId) {
    // The student typed the address instead of scanning: join the class that is open now,
    // or go back to the last class they attended.
    try { sessionId = (await api("GET", "/api/active")).session?.id; } catch { /* offline */ }
    sessionId ||= store("cp_session");
  }
  if (!sessionId) return show("#noSession");
  try {
    ({ session, poll: currentPoll } = await api("GET", `/api/sessions/${sessionId}`));
  } catch (e) {
    if (e.status === 404) store("cp_session", null);
    return show("#noSession");
  }
  store("cp_session", sessionId);
  $("#sessionTitle").textContent = session.title;
  if (store(`cp_in_${sessionId}`) || !session.is_active) return enterClass();

  $("#sid").value = profile.student_id || "";
  $("#sname").value = profile.name || "";
  if (token && profile.student_id && profile.name) checkIn(profile.student_id, profile.name, token); // one scan
  else showCheckin();
}

boot();
