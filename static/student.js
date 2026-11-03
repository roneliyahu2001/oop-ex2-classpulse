// Student phone app. Flow: scan QR -> auto check-in -> poll / comments / homework.
const params = new URLSearchParams(location.search);
const sessionId = params.get("s") || store("cp_session");
const token = params.get("t");
const profile = store("cp_profile") || {};
const votes = store("cp_votes") || {};          // pollId -> option index
let currentPoll = null;

if (params.get("s")) store("cp_session", params.get("s"));
if (token) history.replaceState(null, "", `/?s=${sessionId}`); // a reload must not reuse the token

// ---- tabs ---------------------------------------------------------------
document.querySelectorAll("[data-tab]").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("[data-tab]").forEach((x) => x.classList.toggle("active", x === b));
    document.querySelectorAll("[data-pane]").forEach((p) => p.classList.toggle("hidden", p.dataset.pane !== b.dataset.tab));
  }));

// ---- check-in -----------------------------------------------------------
async function checkIn(studentId, name) {
  const msg = $("#checkinMsg");
  try {
    const rec = await api("POST", "/api/checkin", { session_id: sessionId, token, student_id: studentId, name });
    store("cp_profile", { student_id: studentId, name });
    store(`cp_in_${sessionId}`, true);
    $("#checkinCard").classList.add("hidden");
    showMsg($("#banner"), `Checked in at ${fmtTime(rec.checked_in_at)} ✓`, "ok");
    enterClass();
  } catch (e) {
    $("#checkinCard").classList.remove("hidden");
    showMsg(msg, e.message, "err");
    if (e.code === "ALREADY_CHECKED_IN" || e.code === "DEVICE_USED") enterClass();
  }
}

$("#checkinForm").addEventListener("submit", (e) => {
  e.preventDefault();
  checkIn($("#sid").value.trim(), $("#sname").value.trim());
});

// ---- polls --------------------------------------------------------------
function renderPoll(poll) {
  currentPoll = poll;
  if (!poll) {
    $("#pollQuestion").textContent = "No active poll";
    $("#pollOptions").replaceChildren(h("p", { class: "muted" }, "When the lecturer opens a poll, it appears here."));
    return;
  }
  $("#pollQuestion").textContent = poll.question + (poll.is_open ? "" : " (closed)");
  $("#pollOptions").replaceChildren(...pollBars(poll, { onVote: vote, myVote: votes[poll.id] }));
}

async function vote(i) {
  try {
    const p = await api("POST", `/api/polls/${currentPoll.id}/vote`, { option: i });
    votes[p.id] = i; store("cp_votes", votes); renderPoll(p);
  } catch (e) {
    if (e.code === "ALREADY_VOTED") { votes[currentPoll.id] = votes[currentPoll.id] ?? -1; store("cp_votes", votes); }
    showMsg($("#banner"), e.message, "err");
  }
}

// ---- comments (with offline outbox) -------------------------------------
const comments = new Map();
function renderComments() {
  const list = [...comments.values()].sort((a, b) => b.created_at - a.created_at);
  $("#comments").replaceChildren(...list.map((c) =>
    h("div", { class: "comment" },
      h("div", { class: "body" }, c.text, h("div", { class: "meta" }, `${c.author} · ${fmtTime(c.created_at)}`)),
      h("button", { onclick: () => upvote(c.id), title: "Upvote" }, `▲ ${c.upvotes}`))));
}

async function upvote(id) {
  try { const c = await api("POST", `/api/comments/${id}/upvote`); comments.set(c.id, c); renderComments(); }
  catch (e) { showMsg($("#commentMsg"), e.message, "warn"); }
}

function outbox() { return store("cp_outbox") || []; }
async function flushOutbox() {
  const pending = outbox();
  const left = [];
  for (const item of pending) {
    try { await api("POST", `/api/sessions/${item.sid}/comments`, item.body); }
    catch (e) { if (!e.status) left.push(item); } // keep only network failures
  }
  store("cp_outbox", left);
  if (pending.length && !left.length) showMsg($("#commentMsg"), "Offline comments were sent ✓", "ok");
}

$("#commentForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = { text: $("#commentText").value, author: $("#anon").checked ? "" : (profile.name || "") };
  try {
    await api("POST", `/api/sessions/${sessionId}/comments`, body);
    showMsg($("#commentMsg"), "Sent ✓", "ok");
    $("#commentText").value = "";
  } catch (err) {
    if (err.status) return showMsg($("#commentMsg"), err.message, "err");
    store("cp_outbox", [...outbox(), { sid: sessionId, body }]);
    showMsg($("#commentMsg"), "You're offline. Saved, will send automatically.", "warn");
    $("#commentText").value = "";
  }
});
addEventListener("online", flushOutbox);
setInterval(flushOutbox, 10000);

// ---- homework -----------------------------------------------------------
$("#hwSubmit").addEventListener("click", async () => {
  const p = store("cp_profile");
  if (!p) return showMsg($("#hwMsg"), "Check in first so we know your student ID.", "err");
  const btn = $("#hwSubmit"); btn.disabled = true;
  showMsg($("#hwMsg"), "Reviewing… (can take ~20 s with the LLM)", "warn");
  try {
    await api("POST", `/api/sessions/${sessionId}/homework`, { student_id: p.student_id, name: p.name, text: $("#hwText").value });
    const r = await api("POST", `/api/sessions/${sessionId}/homework/${p.student_id}/review`, { task: $("#hwTask").value });
    const c = r.comparison;
    showMsg($("#hwMsg"), "");
    put($("#hwResult"),
      h("div", {},
        h("span", { class: "stat" }, `${c.words} words (class avg ${c.class_avg_words})`),
        h("span", { class: "stat" }, `Class size ${c.class_size}`),
        h("span", { class: "stat" }, `Max overlap ${Math.round(c.max_similarity * 100)}%`)),
      c.possible_copy ? h("div", { class: "msg err" }, "High overlap with another submission.") : null,
      h("pre", { class: "out" }, r.review));
  } catch (e) { showMsg($("#hwMsg"), e.message, "err"); }
  btn.disabled = false;
});

// ---- boot ---------------------------------------------------------------
let entered = false;
async function enterClass() {
  if (entered) return; entered = true;
  $("#classView").classList.remove("hidden");
  try {
    const { session, poll } = await api("GET", `/api/sessions/${sessionId}`);
    $("#sessionTitle").textContent = session.title;
    if (!session.is_active) showMsg($("#banner"), "This class has ended. You can still leave comments.", "warn");
    renderPoll(poll);
    (await api("GET", `/api/sessions/${sessionId}/comments`)).forEach((c) => comments.set(c.id, c));
    renderComments();
  } catch (e) { showMsg($("#banner"), e.message, "err"); }
  live(sessionId, {
    poll: (p) => { if (p.is_open || p.id === currentPoll?.id) renderPoll(p); },
    comment: (c) => { comments.set(c.id, c); renderComments(); },
    session: (s) => { if (!s.is_active) showMsg($("#banner"), "This class has ended. Thanks!", "warn"); },
  });
  flushOutbox();
}

const setNet = () => ($("#netStatus").textContent = navigator.onLine ? "" : "offline");
addEventListener("online", setNet); addEventListener("offline", setNet); setNet();

if (!sessionId) {
  $("#noSession").classList.remove("hidden");
} else if (token && !store(`cp_in_${sessionId}`)) {
  $("#sid").value = profile.student_id || "";
  $("#sname").value = profile.name || "";
  if (profile.student_id && profile.name) checkIn(profile.student_id, profile.name); // one-scan check-in
  else $("#checkinCard").classList.remove("hidden");
} else {
  enterClass();
}
