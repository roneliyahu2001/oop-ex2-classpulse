// Head count from a class photo, for the lecturer's dashboard.
// People are detected in this browser (TensorFlow.js + COCO-SSD, vendored, works offline).
// The photo never leaves the computer; only the final number is sent to the server.
// This counts people. It does not recognise who they are.

const HeadCount = (() => {
  const MODEL_URL = "/static/vendor/tfjs/ssdlite/model.json";
  const MIN_SCORE = 0.35;
  const TILE_MAX = 900;          // a tile is scaled down to at most this many pixels per side
  let modelPromise = null;
  let photo = null;              // the loaded <img>
  let boxes = [];                // [{x, y, w, h, score, manual}] in photo pixels
  let canvas = null;

  const loadScript = (src) => new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = src; s.onload = ok; s.onerror = fail;
    document.head.append(s);
  });

  // The libraries (1.5 MB) and the model (18 MB) load only the first time a photo is counted.
  const load = () => (modelPromise ??= (async () => {
    if (!window.cocoSsd) {
      // TensorFlow.js stores a helper in this global. If the name doesn't exist yet it falls back to
      // eval, which the page's security policy blocks. Declaring it first keeps the policy strict.
      if (!("regeneratorRuntime" in window)) window.regeneratorRuntime = undefined;
      await loadScript("/static/vendor/tfjs/tf.min.js");
      await loadScript("/static/vendor/tfjs/coco-ssd.min.js");
    }
    return cocoSsd.load({ base: "lite_mobilenet_v2", modelUrl: MODEL_URL });
  })());

  // The whole photo, plus overlapping tiles so that small people at the back are found too.
  function tiles(W, H) {
    const out = [[0, 0, W, H]];
    const cols = W >= H ? 3 : 2, rows = W >= H ? 2 : 3, overlap = 0.25;
    const tw = W / (cols - (cols - 1) * overlap), th = H / (rows - (rows - 1) * overlap);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        out.push([Math.round(c * tw * (1 - overlap)), Math.round(r * th * (1 - overlap)), Math.round(tw), Math.round(th)]);
      }
    }
    return out;
  }

  const area = (b) => b.w * b.h;
  function overlap(a, b) {
    const w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x);
    const h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
    return w > 0 && h > 0 ? w * h : 0;
  }

  // One person is often found twice (in the full photo and in a tile, or cut at a tile edge).
  // Keep the more confident box when two boxes mostly cover each other.
  function merge(found) {
    const kept = [];
    for (const b of found.sort((p, q) => q.score - p.score)) {
      const dup = kept.some((k) => {
        const inter = overlap(k, b);
        return inter / (area(k) + area(b) - inter) > 0.4 || inter / Math.min(area(k), area(b)) > 0.7;
      });
      if (!dup) kept.push(b);
    }
    return kept;
  }

  async function detect(img, onProgress) {
    const model = await load();
    const W = img.naturalWidth, H = img.naturalHeight;
    const found = [];
    const parts = tiles(W, H);
    const work = document.createElement("canvas");
    for (let i = 0; i < parts.length; i++) {
      onProgress(i + 1, parts.length);
      const [x, y, w, h] = parts[i];
      const scale = Math.min(1, TILE_MAX / Math.max(w, h));
      work.width = Math.round(w * scale);
      work.height = Math.round(h * scale);
      work.getContext("2d").drawImage(img, x, y, w, h, 0, 0, work.width, work.height);
      const preds = await model.detect(work, 100, MIN_SCORE);
      const margin = 0.02 * Math.max(work.width, work.height);
      for (const p of preds) {
        if (p.class !== "person") continue;
        const [bx, by, bw, bh] = p.bbox;
        // A box that touches a tile edge inside the photo shows only part of a person. That person
        // is whole in a neighbouring tile (they overlap) or in the full photo, so skip the fragment.
        const cut = i > 0 && ((bx < margin && x > 0) || (by < margin && y > 0) ||
          (bx + bw > work.width - margin && x + w < W) || (by + bh > work.height - margin && y + h < H));
        if (cut) continue;
        found.push({ x: x + bx / scale, y: y + by / scale, w: bw / scale, h: bh / scale, score: p.score });
      }
      await new Promise((r) => setTimeout(r));  // let the page repaint the progress
    }
    return merge(found);
  }

  function draw() {
    const ctx = canvas.getContext("2d");
    ctx.drawImage(photo, 0, 0, canvas.width, canvas.height);
    const lw = Math.max(2, canvas.width / 400);
    ctx.lineWidth = lw;
    ctx.font = `bold ${Math.round(lw * 7)}px sans-serif`;
    boxes.forEach((b, i) => {
      ctx.strokeStyle = b.manual ? "#d9a441" : "#3fdc97";
      ctx.strokeRect(b.x, b.y, b.w, b.h);
      const label = String(i + 1);
      const tw = ctx.measureText(label).width + lw * 3;
      ctx.fillStyle = ctx.strokeStyle;
      ctx.fillRect(b.x, b.y, tw, lw * 9);
      ctx.fillStyle = "#0f3d2e";
      ctx.fillText(label, b.x + lw * 1.5, b.y + lw * 7);
    });
    render();
  }

  // Click a box to remove a false detection; click a person without a box to add one.
  function onClick(e) {
    const r = canvas.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * canvas.width;
    const py = ((e.clientY - r.top) / r.height) * canvas.height;
    const hits = boxes.filter((b) => px >= b.x && px <= b.x + b.w && py >= b.y && py <= b.y + b.h);
    if (hits.length) {
      const smallest = hits.sort((a, b) => area(a) - area(b))[0];
      boxes = boxes.filter((b) => b !== smallest);
    } else {
      const s = canvas.width * 0.05;
      boxes.push({ x: px - s / 2, y: py - s / 2, w: s, h: s, score: 1, manual: true });
    }
    draw();
  }

  function render() {
    const present = Number($("#presentCount").textContent) || 0;
    const counted = boxes.length;
    const saved = session.headcount;
    $("#hcCount").textContent = canvas ? t("l.hc.found", { n: counted }) : "";
    show("#hcActions", !!canvas);
    const gap = present - (canvas ? counted : saved ?? 0);
    const basis = canvas ? counted : saved;
    if (basis == null) return put($("#hcCompare"));
    // A few people either way is normal: a missed face, a student who stepped out.
    const verdict = gap > 2 ? t("l.hc.more", { n: gap }) : gap < -2 ? t("l.hc.fewer", { n: -gap }) : t("l.hc.match");
    put($("#hcCompare"),
      h("div", { class: `msg ${gap > 2 ? "warn" : "ok"}` },
        t("l.hc.compare", { present, counted: basis }) + " " + verdict),
      !canvas && saved != null && h("div", { class: "muted" }, t("l.hc.savedAt", { time: fmtTime(session.headcount_at) })));
  }

  async function onFile(file) {
    if (!file) return;
    const msg = $("#hcMsg");
    const img = new Image();
    const url = URL.createObjectURL(file);
    try {
      await new Promise((ok, fail) => { img.onload = ok; img.onerror = fail; img.src = url; });
    } catch {
      return showMsg(msg, t("l.hc.badImage"), "err");
    }
    photo = img;
    canvas = $("#hcCanvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    boxes = [];
    show("#hcCanvas");
    draw();
    try {
      showMsg(msg, t(modelPromise ? "l.hc.working" : "l.hc.loading"), "warn");
      boxes = await detect(img, (i, n) => showMsg(msg, t("l.hc.progress", { i, n }), "warn"));
      showMsg(msg, t("l.hc.done"), "ok");
    } catch (e) {
      modelPromise = null;
      showMsg(msg, t("l.hc.failed"), "err");
    }
    draw();
  }

  async function save() {
    try {
      session = await api("POST", `/api/sessions/${sid}/headcount`, { count: boxes.length });
      showMsg($("#hcMsg"), t("l.hc.saved", { n: session.headcount }), "ok");
      render();
    } catch (e) { showMsg($("#hcMsg"), errText(e), "err"); }
  }

  // Called by the dashboard when another class is opened.
  function reset() {
    photo = null; canvas = null; boxes = [];
    show("#hcCanvas", false);
    $("#hcFile").value = "";
    showMsg($("#hcMsg"), "");
    render();
  }

  $("#hcFile").addEventListener("change", (e) => onFile(e.target.files[0]));
  $("#hcCanvas").addEventListener("click", onClick);
  $("#hcSave").addEventListener("click", save);

  return { reset, render, detect };
})();
