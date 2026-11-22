// Hazard Maze live viewer. Fetches one maze + every agent's run from the local server,
// then replays all agents side by side in simulated time.

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const AGENTS = {
  oracle:      { label: "Oracle",            color: "--oracle", desc: "Full map · Dijkstra on time" },
  astar:       { label: "A*",                color: "--astar",  desc: "{v} view + GPS · fewest steps" },
  astar_aware: { label: "Obstacle-aware A*", color: "--aware",  desc: "{v} view + GPS · plans on time" },
  laya:        { label: "Laya",              color: "--laya",   desc: "{v} view + GPS · Laya picks moves" },
};
const $ = (id) => document.getElementById(id);

const state = {
  data: null, panels: [], simT: 0, playing: true, speed: 10, lastTs: null,
  grid: null, puddles: new Map(), muds: new Set(), arrows: new Map(),
};

// ------------------------------------------------------------------ loading
async function load(seed) {
  if (seed !== undefined) $("seed").value = seed;
  const q = new URLSearchParams({ seed: $("seed").value || 0, size: $("size").value, radius: $("radius").value });
  const tag = showLoading("Solving maze…");
  try {
    const res = await fetch(`/api/run?${q}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    state.data = data;
    build();
    restart();
  } catch (e) {
    $("mapinfo").textContent = "Could not load the maze: " + e.message;
  } finally { tag.remove(); }
}

function showLoading(text) {
  const el = document.createElement("div");
  el.className = "loading"; el.textContent = text;
  document.body.appendChild(el);
  return el;
}

// ------------------------------------------------------------------ build
function build() {
  const d = state.data, n = d.size;
  state.grid = d.walls.map((row) => [...row].map((ch) => ch === "#"));
  state.puddles = new Map(d.puddles.map(([r, c, v]) => [r * n + c, v]));
  state.muds = new Set(d.muds.map(([r, c]) => r * n + c));
  state.arrows = new Map(d.arrows.map(([r, c, dir]) => [r * n + c, dir]));
  document.querySelectorAll(".slowMoves").forEach((e) => (e.textContent = d.rules.slowMoves));

  const view = `${2 * d.radius + 1}×${2 * d.radius + 1}`;
  $("mapinfo").innerHTML = [
    ["Seed", d.seed], ["Map", `${n}×${n}`], ["Puddles", d.puddles.length], ["Mud", d.muds.length],
    ["Conveyors", d.arrows.length], ["Fewest steps", d.fewestSteps], ["Best time", d.best.toFixed(1) + " s"],
    ["Limit", d.limit.toFixed(0) + " s"],
  ].map(([k, v]) => `<span class="pill">${k} <b>${v}</b></span>`).join("");

  const host = $("panels");
  host.innerHTML = "";
  state.panels = d.agents.map((a) => makePanel(a, view, host));
  sizeCanvases();
  renderResults(true);
}

function makePanel(a, view, host) {
  const meta = AGENTS[a.name] || { label: a.name, color: "--accent", desc: view };
  const el = document.createElement("article");
  el.className = "panel";
  el.style.setProperty("--c", `var(${meta.color})`);
  el.innerHTML = `
    <div class="panel-head">
      <div><div class="name"><i class="dot"></i>${meta.label}</div>
      <div class="desc">${meta.desc.replace("{v}", view)}</div></div>
      <span class="chip">Ready</span>
    </div>
    <div class="stage"><canvas></canvas></div>
    <div class="panel-foot">
      <div class="timerow"><span class="t">0.0 s</span><span class="lim"></span></div>
      <div class="bar"><span></span><i class="best"></i></div>
      <div class="counts"></div>
    </div>`;
  host.appendChild(el);
  const trace = a.trace.map(([r, c, t, e, s]) => ({ r, c, t, e, s }));
  return {
    a, meta, el, trace, color: css(meta.color),
    canvas: el.querySelector("canvas"), chip: el.querySelector(".chip"),
    tEl: el.querySelector(".t"), limEl: el.querySelector(".lim"),
    barEl: el.querySelector(".bar > span"), bestEl: el.querySelector(".bar > .best"),
    countsEl: el.querySelector(".counts"),
    idx: -1, popups: [], seenIdx: a.fullMap ? null : revealSchedule(trace),
    base: null, fog: null, fogIdx: -1, cs: 8,
  };
}

// First trace index at which each cell enters the vision window (limited agents only).
function revealSchedule(trace) {
  const n = state.data.size, R = state.data.radius;
  const first = new Int32Array(n * n).fill(-1);
  trace.forEach((p, i) => {
    for (let dr = -R; dr <= R; dr++)
      for (let dc = -R; dc <= R; dc++) {
        const r = p.r + dr, c = p.c + dc;
        if (r < 0 || c < 0 || r >= n || c >= n) continue;
        const k = r * n + c;
        if (first[k] < 0) first[k] = i;
      }
  });
  return first;
}

function sizeCanvases() {
  const n = state.data.size;
  for (const p of state.panels) {
    const avail = p.el.querySelector(".stage").clientWidth - 0;
    const cs = Math.max(3, Math.floor(Math.min(avail, 760) / n));
    p.cs = cs;
    const dpr = window.devicePixelRatio || 1;
    const px = cs * n;
    p.canvas.width = px * dpr; p.canvas.height = px * dpr;
    p.canvas.style.width = px + "px"; p.canvas.style.height = px + "px";
    p.ctx = p.canvas.getContext("2d");
    p.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    p.base = drawBase(cs);
    p.fog = p.seenIdx ? makeFog(cs) : null;
    p.fogIdx = -1;
  }
}

// ------------------------------------------------------------------ static drawing
function drawBase(cs) {
  const n = state.data.size, dpr = window.devicePixelRatio || 1;
  const cv = document.createElement("canvas");
  cv.width = cs * n * dpr; cv.height = cs * n * dpr;
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const floor = css("--t-floor"), wall = css("--t-wall"), pud = css("--t-puddle"), mud = css("--t-mud"),
        arrow = css("--t-arrow");
  g.fillStyle = wall; g.fillRect(0, 0, cs * n, cs * n);
  for (let r = 0; r < n; r++)
    for (let c = 0; c < n; c++) {
      if (state.grid[r][c]) continue;
      const x = c * cs, y = r * cs, k = r * n + c;
      g.fillStyle = floor; g.fillRect(x, y, cs, cs);
      if (cs >= 6) { g.fillStyle = "rgba(255,255,255,0.025)"; g.fillRect(x, y, cs, 1); }
      if (state.puddles.has(k)) {
        const v = state.puddles.get(k);
        g.globalAlpha = 0.35 + 0.22 * v; g.fillStyle = pud; g.fillRect(x, y, cs, cs); g.globalAlpha = 1;
        if (cs >= 8) {           // little droplet
          g.fillStyle = "rgba(255,255,255,0.55)";
          g.beginPath(); g.arc(x + cs * 0.38, y + cs * 0.38, cs * 0.12, 0, 7); g.fill();
        }
      } else if (state.muds.has(k)) {
        g.fillStyle = mud; g.fillRect(x, y, cs, cs);
        if (cs >= 8) {
          g.fillStyle = "rgba(0,0,0,0.28)";
          for (const [fx, fy] of [[.3, .35], [.68, .3], [.5, .7]]) { g.beginPath(); g.arc(x + cs * fx, y + cs * fy, cs * 0.09, 0, 7); g.fill(); }
        }
      } else if (state.arrows.has(k)) {
        g.fillStyle = "#3a1d26"; g.fillRect(x, y, cs, cs);
        drawArrow(g, x, y, cs, state.arrows.get(k), arrow);
      }
    }
  const tile = (p, col, glyph) => {
    const [r, c] = p, x = c * cs, y = r * cs;
    g.fillStyle = col; g.fillRect(x, y, cs, cs);
    if (cs >= 10) {
      g.fillStyle = "#0b0e14"; g.font = `700 ${Math.floor(cs * 0.6)}px system-ui`;
      g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(glyph, x + cs / 2, y + cs / 2 + 1);
    }
  };
  tile(state.data.start, css("--t-start"), "S");
  tile(state.data.goal, css("--t-goal"), "★");
  return cv;
}

function drawArrow(g, x, y, cs, dir, col) {
  const m = cs / 2, s = Math.max(1.5, cs * 0.32);
  const cx = x + m, cy = y + m;
  const pts = {
    up: [[cx, cy - s], [cx - s, cy + s], [cx + s, cy + s]],
    down: [[cx, cy + s], [cx - s, cy - s], [cx + s, cy - s]],
    left: [[cx - s, cy], [cx + s, cy - s], [cx + s, cy + s]],
    right: [[cx + s, cy], [cx - s, cy - s], [cx - s, cy + s]],
  }[dir];
  g.fillStyle = col; g.beginPath(); g.moveTo(...pts[0]); g.lineTo(...pts[1]); g.lineTo(...pts[2]); g.closePath(); g.fill();
}

function makeFog(cs) {
  const n = state.data.size, dpr = window.devicePixelRatio || 1;
  const cv = document.createElement("canvas");
  cv.width = cs * n * dpr; cv.height = cs * n * dpr;
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.fillStyle = "rgba(6,8,13,0.6)"; g.fillRect(0, 0, cs * n, cs * n);
  return cv;
}

function updateFog(p, idx) {
  if (!p.fog) return;
  const n = state.data.size, cs = p.cs, g = p.fog.getContext("2d");
  if (idx < p.fogIdx) {     // went backwards (restart): repaint
    g.clearRect(0, 0, cs * n, cs * n);
    g.fillStyle = "rgba(6,8,13,0.6)"; g.fillRect(0, 0, cs * n, cs * n);
    p.fogIdx = -1;
  }
  if (idx === p.fogIdx) return;
  for (let k = 0; k < p.seenIdx.length; k++) {
    const s = p.seenIdx[k];
    if (s > p.fogIdx && s <= idx) g.clearRect((k % n) * cs, Math.floor(k / n) * cs, cs, cs);
  }
  p.fogIdx = idx;
}

// ------------------------------------------------------------------ animation
function indexAt(trace, t) {          // last index with trace[i].t <= t
  let lo = 0, hi = trace.length - 1;
  while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (trace[mid].t <= t) lo = mid; else hi = mid - 1; }
  return lo;
}

function frame(ts) {
  if (state.data) {
    if (state.lastTs !== null && state.playing) state.simT += ((ts - state.lastTs) / 1000) * state.speed;
    state.lastTs = ts;
    const end = Math.max(...state.panels.map((p) => p.trace[p.trace.length - 1].t));
    if (state.simT >= end && state.playing) { state.simT = end; setPlaying(false); renderResults(false); }
    $("clock").textContent = state.simT.toFixed(1) + " s";
    for (const p of state.panels) drawPanel(p, ts);
  }
  requestAnimationFrame(frame);
}

function drawPanel(p, now) {
  const d = state.data, n = d.size, cs = p.cs, g = p.ctx, tr = p.trace;
  const i = indexAt(tr, state.simT), last = tr.length - 1, done = i === last;

  // new steps since last frame -> popups
  if (i > p.idx) {
    for (let j = Math.max(1, p.idx + 1); j <= i; j++) {
      const base = tr[j - 1].s > 0 ? d.rules.slowMult : 1;      // move cost before the hazard's extra
      spawnPopup(p, tr[j], tr[j].t - tr[j - 1].t - base, now);
    }
  }
  p.idx = i;
  updateFog(p, i);

  // interpolated position
  let r = tr[i].r, c = tr[i].c;
  if (!done) {
    const a = tr[i], b = tr[i + 1], f = Math.min(1, (state.simT - a.t) / Math.max(1e-6, b.t - a.t));
    r = a.r + (b.r - a.r) * f; c = a.c + (b.c - a.c) * f;
  }

  g.clearRect(0, 0, cs * n, cs * n);
  g.drawImage(p.base, 0, 0, cs * n, cs * n);
  if (p.fog) g.drawImage(p.fog, 0, 0, cs * n, cs * n);

  // trail
  g.strokeStyle = p.color; g.globalAlpha = 0.75; g.lineWidth = Math.max(1.5, cs * 0.28);
  g.lineCap = "round"; g.lineJoin = "round";
  g.beginPath();
  g.moveTo(tr[0].c * cs + cs / 2, tr[0].r * cs + cs / 2);
  for (let j = 1; j <= i; j++) g.lineTo(tr[j].c * cs + cs / 2, tr[j].r * cs + cs / 2);
  g.lineTo(c * cs + cs / 2, r * cs + cs / 2);
  g.stroke(); g.globalAlpha = 1;

  // vision window
  if (!p.a.fullMap) {
    const R = d.radius;
    g.strokeStyle = p.color; g.lineWidth = 1.5; g.setLineDash([4, 3]);
    g.strokeRect((c - R) * cs, (r - R) * cs, (2 * R + 1) * cs, (2 * R + 1) * cs);
    g.setLineDash([]);
  }

  // agent
  const slowed = tr[i].s > 0 && !done;
  const x = c * cs + cs / 2, y = r * cs + cs / 2, rad = Math.max(3.5, cs * 0.55);
  g.shadowColor = p.color; g.shadowBlur = 14;
  g.fillStyle = p.color; g.beginPath(); g.arc(x, y, rad, 0, 7); g.fill();
  g.shadowBlur = 0;
  g.lineWidth = slowed ? 3 : 2; g.strokeStyle = slowed ? css("--t-mud") : "#0b0e14";
  g.beginPath(); g.arc(x, y, rad, 0, 7); g.stroke();

  // popups
  p.popups = p.popups.filter((q) => now - q.born < 1100);
  g.font = `700 ${Math.max(11, Math.min(15, cs * 1.1))}px system-ui`; g.textAlign = "center"; g.textBaseline = "bottom";
  for (const q of p.popups) {
    const age = (now - q.born) / 1100;
    g.globalAlpha = 1 - age;
    const px = q.c * cs + cs / 2, py = q.r * cs - age * 18;
    g.lineWidth = 3; g.strokeStyle = "rgba(8,10,15,0.9)"; g.strokeText(q.text, px, py);
    g.fillStyle = q.color; g.fillText(q.text, px, py);
  }
  g.globalAlpha = 1;

  // footer + chip
  const tNow = Math.min(state.simT, tr[last].t);
  p.tEl.textContent = tNow.toFixed(1) + " s";
  p.limEl.textContent = done ? `${(tr[last].t / d.best).toFixed(2)}× best` : `limit ${d.limit.toFixed(0)} s`;
  p.barEl.style.width = Math.min(100, (tNow / d.limit) * 100) + "%";
  p.bestEl.style.left = Math.min(100, (d.best / d.limit) * 100) + "%";
  let chip = ["Racing", "chip run"];
  if (done) chip = p.a.success ? ["Reached goal", "chip ok"] : ["Out of time", "chip fail"];
  else if (slowed) chip = [`Slowed · ${tr[i].s}`, "chip slow"];
  else if (state.simT === 0) chip = ["Ready", "chip"];
  p.chip.textContent = chip[0]; p.chip.className = chip[1];

  const ev = { puddle: 0, mud: 0, arrow: 0, bump: 0 };
  for (let j = 1; j <= i; j++) if (tr[j].e in ev) ev[tr[j].e]++;
  p.countsEl.innerHTML = `<span>steps <b>${i}</b></span><span>· slips <b>${ev.puddle}</b></span>` +
    `<span>· mud <b>${ev.mud}</b></span><span>· pushed <b>${ev.arrow}</b></span>`;
}

function spawnPopup(p, step, extra, now) {
  const map = {
    puddle: [`slip +${Math.round(extra)}s`, css("--t-puddle")],
    mud: ["slowed!", "#f0a868"],
    arrow: ["pushed!", css("--t-arrow")],
    bump: ["bump", "#aab"],
  };
  if (!map[step.e]) return;
  p.popups.push({ r: step.r, c: step.c, text: map[step.e][0], color: map[step.e][1], born: now });
}

// ------------------------------------------------------------------ results
function renderResults(pending) {
  const d = state.data;
  const rows = d.agents.map((a) => ({ name: a.name, time: a.time, ratio: a.time / d.best, ok: a.success }))
    .sort((x, y) => x.time - y.time);
  const max = Math.max(...rows.map((r) => r.ratio), 1.5);
  $("results").innerHTML = pending
    ? `<div class="empty">Results appear when the race finishes.</div>`
    : rows.map((r) => resultRow(r.name, r.ratio, max, `${r.time.toFixed(1)} s`, r.ok)).join("");
}

function resultRow(name, ratio, max, val, ok = true) {
  const meta = AGENTS[name] || { label: name, color: "--accent" };
  return `<div class="rrow" style="--c:var(${meta.color})">
    <div class="who"><i class="dot"></i>${meta.label}</div>
    <div class="track"><div class="fill" style="width:${(ratio / max) * 100}%"></div></div>
    <div class="val">${val}${ok ? "" : " ✗"}</div>
    <div class="ratio">${ratio.toFixed(2)}×</div></div>`;
}

async function bench() {
  const btn = $("bench"); btn.disabled = true; btn.textContent = "Running…";
  $("benchOut").innerHTML = `<div class="empty">Running ${$("benchN").value} mazes… this can take a little while on big maps.</div>`;
  const q = new URLSearchParams({ n: $("benchN").value, seed: $("seed").value || 0, size: $("size").value, radius: $("radius").value });
  try {
    const b = await (await fetch(`/api/bench?${q}`)).json();
    const max = Math.max(...b.rows.map((r) => r.ratio), 1.5);
    $("benchOut").innerHTML = b.rows.sort((x, y) => x.ratio - y.ratio)
      .map((r) => resultRow(r.name, r.ratio, max, `${Math.round(r.success * 100)}% ok`)).join("") +
      `<p class="hint">${b.n} mazes · ${b.size}×${b.size} · vision ${2 * b.radius + 1}×${2 * b.radius + 1} · seeds ${b.seedFrom}–${b.seedFrom + b.n - 1}</p>`;
  } catch (e) {
    $("benchOut").innerHTML = `<div class="empty">Benchmark failed: ${e.message}</div>`;
  } finally { btn.disabled = false; btn.textContent = "Run benchmark"; }
}

// ------------------------------------------------------------------ controls
function setPlaying(on) { state.playing = on; $("play").textContent = on ? "Pause" : "Play"; }
function restart() {
  state.simT = 0; state.lastTs = null;
  for (const p of state.panels) { p.idx = -1; p.popups = []; }
  renderResults(true); setPlaying(true);
}
function randomMaze() { load(Math.floor(Math.random() * 100000)); }

$("play").onclick = () => {
  const end = Math.max(...state.panels.map((p) => p.trace[p.trace.length - 1].t));
  if (!state.playing && state.simT >= end) return restart();
  setPlaying(!state.playing);
};
$("restart").onclick = restart;
$("go").onclick = () => load();
$("dice").onclick = randomMaze;
$("size").onchange = () => load();
$("radius").onchange = () => load();
$("seed").onkeydown = (e) => { if (e.key === "Enter") load(); };
$("speed").oninput = (e) => { state.speed = +e.target.value; $("speedVal").textContent = state.speed + "×"; };
$("bench").onclick = bench;
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
  if (e.code === "Space") { e.preventDefault(); $("play").click(); }
  else if (e.key === "r" || e.key === "R") restart();
  else if (e.key === "n" || e.key === "N") randomMaze();
});
let resizeTimer;
window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => state.data && sizeCanvases(), 150); });

load();
requestAnimationFrame(frame);
