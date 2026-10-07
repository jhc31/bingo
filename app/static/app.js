"use strict";

const UNIT = 25;
const STARS = [3, 4, 5, 6];
const state = {
  overview: null,
  live: null,
  backtest: null,
  stars: 3,
  liveStars: 3,
  btStars: 3,
  strategy: "logit",
  liveStrategy: "all",
  budget: 1000,
  plan: 12,
  clockOffset: 0,
  historyLimit: 50,
  loaded: {},
};

const $ = (sel) => document.querySelector(sel);
const fmt = (n, digits = 0) => Number(n).toLocaleString("zh-TW", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = (x, digits = 2) => `${(x * 100).toFixed(digits)}%`;
const signed = (n) => (n > 0 ? "+" : "") + fmt(n);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (_) { /* not JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

/* ---------- theme ---------- */
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem("theme"); } catch (_) { /* storage unavailable */ }
  if (saved) document.documentElement.dataset.theme = saved;
  $("#themeToggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (_) { /* storage unavailable */ }
  });
}

/* ---------- routing ---------- */
const TABS = ["predict", "live", "backtest", "simulate", "history"];
function route() {
  const tab = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "predict";
  TABS.forEach((t) => { $(`#tab-${t}`).hidden = t !== tab; });
  document.querySelectorAll(".tabs a").forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${tab}`));
  if (!state.loaded[tab]) {
    state.loaded[tab] = true;
    ({ live: loadLive, backtest: loadBacktest, simulate: initSimulator, history: loadHistory }[tab] || (() => {}))();
  }
}

/* ---------- helpers ---------- */
function ball(n, cls = "") {
  return `<span class="ball ${cls}">${String(n).padStart(2, "0")}</span>`;
}

function drawTime(dateStr, index) {
  const minutes = 7 * 60 + 5 + 5 * (index - 1);
  const hh = String(Math.floor(minutes / 60)).padStart(2, "0");
  const mm = String(minutes % 60).padStart(2, "0");
  return `${dateStr.slice(5).replace("-", "/")} ${hh}:${mm}`;
}

function chips(el, current, onPick) {
  el.innerHTML = STARS.map((k) => `<button type="button" class="chip ${k === current ? "active" : ""}" data-k="${k}">${k}星</button>`).join("");
  el.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => onPick(Number(b.dataset.k))));
}

function hypergeom(k) {
  const comb = (n, r) => { let c = 1; for (let i = 1; i <= r; i++) c = (c * (n - r + i)) / i; return c; };
  const total = comb(80, k);
  return Array.from({ length: k + 1 }, (_, h) => (comb(20, h) * comb(60, k - h)) / total);
}

/* ---------- per-viewer preferences ---------- */
function loadPref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (_) { return fallback; }
}
function savePref(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* storage unavailable */ }
}

/* ---------- overview / predictions ---------- */
async function loadOverview() {
  try {
    const ov = await getJSON("/api/overview");
    const changed = !state.overview || state.overview.latest_draw.draw_term !== ov.latest_draw.draw_term;
    state.overview = ov;
    state.clockOffset = new Date(ov.server_time).getTime() - Date.now();
    if (!ov.strategies[state.strategy]) state.strategy = "logit";
    return changed;
  } catch (e) {
    $("#predictBody").innerHTML = `<tr><td colspan="5" class="empty">無法載入資料：${esc(e.message)}</td></tr>`;
    return false;
  }
}

async function loadLiveStats() {
  try {
    state.live = await getJSON("/api/live-stats");
  } catch (_) {
    state.live = {};
  }
}

const strategyName = (s) => (state.overview && state.overview.strategies[s]) || s;
const liveRecord = (s, k) => state.live && state.live[s] && state.live[s].games[k];
const taipeiTime = (iso) => new Date(iso).toLocaleTimeString("zh-TW", { timeZone: "Asia/Taipei", hour12: false });

function returnRate(k, table) {
  return hypergeom(k).reduce((a, p, h) => a + p * (table[h] || 0), 0) / UNIT;
}

function renderOverview() {
  const ov = state.overview;
  const d = ov.latest_draw;
  $("#latestMeta").textContent = `第 ${d.draw_term} 期 · ${drawTime(d.draw_date, d.draw_index)}`;
  $("#latestBalls").innerHTML = d.numbers.map((n) => ball(n, n === d.super_number ? "super" : "")).join("");
  $("#nextMeta").textContent = `第 ${ov.next_draw.term} 期`;
  const t = new Date(ov.next_draw.time);
  $("#nextTime").textContent = `開獎時間 ${t.toLocaleString("zh-TW", { timeZone: "Asia/Taipei", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false })}`;
  const created = ov.predictions.length ? ov.predictions.map((p) => p.created_at).sort()[0] : null;
  let status = created
    ? `預測已產生（${taipeiTime(created)}）`
    : "等待本期號碼公布後產生預測（約開獎後 1~2 分鐘）";
  if (drawsBehind()) status = `已開獎的期數尚未公布，自動更新中…｜${status}`;
  if (ov.scheduler && ov.scheduler.last_error) status += `｜排程錯誤：${ov.scheduler.last_error}`;
  $("#predStatus").textContent = status;
  renderPromo();
  const sel = $("#strategySelect");
  if (!sel.options.length) {
    sel.innerHTML = Object.entries(ov.strategies).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  }
  sel.value = state.strategy;
  chips($("#starChips"), state.stars, (k) => { state.stars = k; savePref("stars", k); renderOverview(); });
  renderAdvice();
  renderPredictions();
}

function renderPromo() {
  const p = state.overview.payouts;
  const items = [...p.active_promotions.map((x) => ({ ...x, when: "進行中" })),
    ...p.upcoming_promotions.filter((x) => (new Date(x.start) - new Date(p.date)) / 864e5 <= 14).map((x) => ({ ...x, when: "即將開始" }))];
  $("#promoBanner").innerHTML = items.map((x) => {
    const parts = STARS.filter((k) => x.stars[k]).map((k) =>
      Object.entries(x.stars[k]).sort((a, b) => b[0] - a[0]).map(([h, v]) => `${k}星中${h} ${fmt(v)}`).join("、"));
    if (x.super_number) parts.push(`超級獎號 ${fmt(x.super_number)}`);
    if (x.big_small) parts.push(`猜大小/單雙 ${fmt(x.big_small)}`);
    return `<div class="promo"><strong>${esc(x.name)}（${x.when}，${x.start.slice(5)} ~ ${x.end.slice(5)}）</strong>${esc(parts.join("；"))}（每注 25 元獎金）</div>`;
  }).join("");
}

function renderAdvice() {
  const ov = state.overview, k = state.stars, games = ov.payouts.games;
  const pred = ov.predictions.find((p) => p.strategy === state.strategy);
  $("#pickLabel").textContent = `推薦號碼 · ${k}星 · 第 ${ov.next_draw.term} 期`;
  $("#pickBalls").innerHTML = pred
    ? pred.ranking.slice(0, k).sort((a, b) => a - b).map((n) => ball(n, "pick")).join("")
    : `<span class="muted">預測尚未產生，本期號碼公布後約 1 分鐘內出現</span>`;
  const rec = liveRecord(state.strategy, k);
  $("#pickNote").textContent = `${strategyName(state.strategy)}｜` + (rec
    ? `即時戰績 ${fmt(rec.n)} 期，回收率 ${pct(rec.return_rate, 1)}（理論 ${pct(rec.theoretical_return_rate, 1)}）`
    : "尚無即時戰績");

  // Game comparison under the payout table that applies to the next draw.
  const best = STARS.reduce((b, s) => (games[s].current.return_rate > games[b].current.return_rate ? s : b), STARS[0]);
  let html = STARS.map((s) => {
    const g = games[s];
    const extra = g.boosted ? `（平常 ${pct(g.base.return_rate, 1)}）` : "";
    return `<div class="game-row clickable ${s === best ? "best" : ""}" data-k="${s}" title="切換到 ${s}星">
      <span class="name">${s}星</span><span class="bar"><span style="width:${Math.min(100, g.current.return_rate * 100)}%"></span></span>
      <span class="val">${pct(g.current.return_rate, 1)}${extra}</span></div>`;
  }).join("");
  html += `<div class="muted small">★ 目前回收率最高：${best}星。所有玩法回收率都低於 100%，長期必虧，只是虧得多或少。</div>`;
  const soon = ov.payouts.upcoming_promotions.find((x) => STARS.some((s) => x.stars[s]) && (new Date(x.start) - new Date(ov.payouts.date)) / 864e5 <= 3);
  if (soon) {
    const boosted = STARS.filter((s) => soon.stars[s]).map((s) => {
      const t = { ...games[s].base_table };
      Object.entries(soon.stars[s]).forEach(([h, v]) => { t[h] = v; });
      return { s, rr: returnRate(s, t) };
    }).sort((a, b) => b.rr - a.rr);
    html += `<div class="small" style="margin-top:6px">${esc(soon.name)}（${soon.start.slice(5)} 起）：` +
      boosted.map((b) => `${b.s}星 ${pct(b.rr, 1)}`).join("、") + `，屆時建議改玩 ${boosted[0].s}星。</div>`;
  }
  $("#gameCompare").innerHTML = html;
  $("#gameCompare").querySelectorAll(".game-row").forEach((el) => el.addEventListener("click", () => {
    state.stars = Number(el.dataset.k); savePref("stars", state.stars); renderOverview();
  }));

  renderPayoutBox();
  renderMultipliers();
}

function renderPayoutBox() {
  const g = state.overview.payouts.games[state.stars];
  const tiers = Object.keys(g.table).map(Number).sort((a, b) => b - a);
  const tierHtml = tiers.map((h) => {
    const now = g.table[h], base = g.base_table[h];
    const val = now !== base ? `<s>${fmt(base)}</s><span class="boost">${fmt(now)}</span>` : fmt(now);
    return `<span class="tier">中${h}：${val}</span>`;
  }).join("");
  const rr = g.boosted
    ? `回收率 <strong>${pct(g.current.return_rate)}</strong>（平常 ${pct(g.base.return_rate)}）<span class="tag">加碼中</span>`
    : `回收率 <strong>${pct(g.current.return_rate)}</strong>`;
  $("#payoutBox").innerHTML = `<span><strong>${state.stars}星</strong> 每注 25 元</span>${tierHtml}
    <span>中獎率 ${pct(g.current.p_any_prize)}</span><span>${rr}</span>`;
}

const simCache = new Map();
function renderMultipliers() {
  const k = state.stars, n = state.plan, budget = state.budget;
  const table = state.overview.payouts.games[k].table;
  const rr = returnRate(k, table);
  const rec = Math.max(1, Math.min(50, Math.floor(budget / (UNIT * n))));
  const cands = [...new Set([1, 2, 3, 5, 10, rec])].filter((m) => m * UNIT <= budget).sort((a, b) => a - b);
  if (!cands.length) {
    $("#multBody").innerHTML = `<tr><td colspan="6" class="empty">預算至少要 25 元</td></tr>`;
    $("#multNote").textContent = "";
    return;
  }
  // Every multiplier is evaluated on the same simulated draws, so differences between rows
  // come from the multiplier alone, not from sampling noise.
  const key = JSON.stringify([k, table, budget, n, cands]);
  if (!simCache.has(key)) {
    const runs = n === 1 ? 1 : 4000;
    const pmf = hypergeom(k), cdf = [];
    pmf.reduce((acc, p, i) => (cdf[i] = acc + p), 0);
    const prizes = new Float64Array(runs * n);
    for (let i = 0; i < prizes.length; i++) {
      const u = Math.random();
      let h = 0;
      while (h < k && u > cdf[h]) h++;
      prizes[i] = table[h] || 0;
    }
    const out = {};
    for (const m of cands) {
      let wins = 0, busts = 0;
      for (let r = 0; r < runs; r++) {
        let bank = budget;
        for (let i = 0; i < n; i++) {
          if (UNIT * m > bank) { busts++; break; }
          bank += m * (prizes[r * n + i] - UNIT);
        }
        if (bank > budget) wins++;
      }
      out[m] = n === 1
        ? { pProfit: pmf.reduce((a, p, h) => a + ((table[h] || 0) > UNIT ? p : 0), 0), bust: 0 }
        : { pProfit: wins / runs, bust: busts / runs };
    }
    simCache.set(key, out);
  }
  const sims = simCache.get(key);
  $("#multBody").innerHTML = cands.map((m) => {
    const s = sims[m];
    const expected = m * n * UNIT * (rr - 1);
    return `<tr class="${m === rec ? "recommended" : ""}">
      <td>${m} 倍${m === rec ? '<span class="tag">建議</span>' : ""}</td>
      <td class="num">${fmt(UNIT * m)}</td><td class="num">${fmt(UNIT * m * n)}</td>
      <td class="num">${signed(Math.round(expected))}</td>
      <td class="num">${pct(s.pProfit, 1)}</td><td class="num">${pct(s.bust, 1)}</td></tr>`;
  }).join("");
  const short = budget < UNIT * n ? `預算不足以 1 倍玩完 ${n} 期，可能中途用光。` : "";
  $("#multNote").textContent = `${short}建議倍數＝預算 ÷（25 元 × 期數），確保一直沒中也能玩完 ${n} 期。` +
    `倍數不改變回收率（目前 ${pct(rr, 1)}），只放大輸贏；回測顯示累進、加倍（馬丁）下注會提高爆倉率而不提高回收率，建議固定倍數。`;
}

function renderPredictions() {
  const ov = state.overview, k = state.stars;
  $("#tableStars").textContent = `${k}星（與上方玩法同步）`;
  const prev = Object.fromEntries(ov.previous_predictions.map((p) => [p.strategy, p]));
  const preds = Object.fromEntries(ov.predictions.map((p) => [p.strategy, p]));
  if (!ov.predictions.length) {
    $("#predictBody").innerHTML = `<tr><td colspan="5" class="empty">下一期的預測尚未產生：會在本期號碼公布後約 1 分鐘內自動出現。</td></tr>`;
    return;
  }
  const latest = new Set(ov.latest_draw.numbers);
  $("#predictBody").innerHTML = Object.keys(ov.strategies).filter((s) => preds[s]).map((s) => {
    const p = preds[s];
    const picks = p.ranking.slice(0, k).sort((a, b) => a - b).map((n) => ball(n, "sm pick")).join("");
    const pv = prev[s];
    let prevCell = "—";
    if (pv && pv.hits) {
      const prevPicks = pv.ranking.slice(0, k).sort((a, b) => a - b)
        .map((n) => ball(n, `sm ${latest.has(n) ? "hit" : ""}`)).join("");
      prevCell = `<div class="balls" title="上期推薦，綠色為命中">${prevPicks}</div><span class="small muted">中 ${pv.hits[k - 1]}</span>`;
    }
    const ls = liveRecord(s, k);
    const cls = [s === state.strategy ? "selected" : "", s === "random" ? "control" : "", "clickable"].join(" ");
    return `<tr class="${cls}" data-s="${s}">
      <td class="strategy-name">${esc(p.description)}${s === state.strategy ? '<span class="tag">已選</span>' : ""}</td>
      <td><div class="balls">${picks}</div></td>
      <td>${prevCell}</td>
      <td class="num">${ls ? pct(ls.return_rate, 1) : "—"}</td>
      <td class="num">${ls ? fmt(ls.n) : 0}</td>
    </tr>`;
  }).join("");
  $("#predictBody").querySelectorAll("tr[data-s]").forEach((tr) => tr.addEventListener("click", () => selectStrategy(tr.dataset.s)));
}

function selectStrategy(s) {
  state.strategy = s;
  savePref("strategy", s);
  $("#strategySelect").value = s;
  renderAdvice();
  renderPredictions();
}

/* ---------- auto refresh ---------- */
function tickCountdown() {
  const ov = state.overview;
  if (!ov) return;
  const remain = new Date(ov.next_draw.time).getTime() - (Date.now() + state.clockOffset);
  if (remain > 0) {
    const s = Math.floor(remain / 1000);
    $("#countdown").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  } else {
    $("#countdown").textContent = "開獎中";
  }
  // Poll while a held draw's numbers are not yet published, or the next prediction is pending.
  const waitingDraw = remain < -20000 || drawsBehind();
  const waitingPred = !ov.predictions.length;
  const every = waitingDraw ? 15000 : 30000;
  if ((waitingDraw || waitingPred) && !state.polling && Date.now() - (state.lastPoll || 0) > every) {
    state.lastPoll = Date.now();
    refreshAll();
  }
}

/** True when a draw already took place but its numbers are not in yet (API publishes 1-2 min later). */
function drawsBehind() {
  const ov = state.overview, last = ov.latest_draw, next = ov.next_draw;
  return next.date === last.draw_date ? next.index - last.draw_index > 1 : last.draw_index < 203;
}

async function refreshAll() {
  state.polling = true;
  try {
    const changed = await loadOverview();
    if (!state.overview) return;
    if (changed) {
      await loadLiveStats();
      if (state.loaded.history) loadHistory();
      if (state.loaded.live) renderLive();
    }
    renderOverview();
  } finally {
    state.polling = false;
  }
}

/* ---------- live stats tab ---------- */
async function loadLive() {
  if (!state.live) await loadLiveStats();
  const sel = $("#liveStrategy");
  sel.innerHTML = `<option value="all">全部策略（比較）</option>` +
    Object.entries(state.overview ? state.overview.strategies : {}).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
  sel.value = state.liveStrategy;
  sel.addEventListener("change", () => { state.liveStrategy = sel.value; savePref("liveStrategy", sel.value); renderLive(); });
  renderLive();
}

function liveRow(label, g, cls = "") {
  return `<tr class="${cls}">
    <td class="strategy-name">${label}</td>
    <td class="num">${fmt(g.n)}</td>
    <td class="num">${g.avg_hits.toFixed(3)}</td>
    <td class="num">${g.expected_hits.toFixed(2)}</td>
    <td class="num">${g.z_hits >= 0 ? "+" : ""}${g.z_hits.toFixed(2)}</td>
    <td class="num">${pct(g.return_rate, 1)}</td>
    <td class="num">${pct(g.theoretical_return_rate, 1)}</td>
    <td class="num">${signed(g.profit_1x)}</td>
  </tr>`;
}

function renderLive() {
  chips($("#liveChips"), state.liveStars, (k) => { state.liveStars = k; renderLive(); });
  const k = state.liveStars, s = state.liveStrategy;
  const cols = ["期數", "平均命中", "期望", "z", "回收率", "理論回收率", "1倍累計損益"].map((c) => `<th class="num">${c}</th>`).join("");
  if (s === "all") {
    $("#liveHead").innerHTML = `<tr><th>策略</th>${cols}</tr>`;
    $("#liveDetailCard").hidden = true;
    const rows = Object.keys(state.overview.strategies).filter((x) => liveRecord(x, k));
    $("#liveBody").innerHTML = rows.length
      ? rows.map((x) => liveRow(esc(strategyName(x)), liveRecord(x, k), x === "random" ? "control" : "")).join("")
      : `<tr><td colspan="8" class="empty">尚無已開獎的即時預測，系統上線後會開始累積。</td></tr>`;
    return;
  }
  $("#liveHead").innerHTML = `<tr><th>玩法</th>${cols}</tr>`;
  const rows = STARS.filter((x) => liveRecord(s, x));
  $("#liveBody").innerHTML = rows.length
    ? rows.map((x) => liveRow(`${x}星`, liveRecord(s, x), x === k ? "selected" : "")).join("")
    : `<tr><td colspan="8" class="empty">這個策略還沒有已開獎的即時預測。</td></tr>`;
  loadStrategyDetail(s);
}

async function loadStrategyDetail(s) {
  const k = state.liveStars;
  $("#liveDetailCard").hidden = false;
  $("#liveDetailTitle").textContent = `${strategyName(s)}：最近 50 期預測（${k}星）`;
  let data;
  try {
    data = await getJSON(`/api/strategy/${encodeURIComponent(s)}?limit=50`);
  } catch (e) {
    $("#liveDetailBody").innerHTML = `<tr><td colspan="5" class="empty">無法載入：${esc(e.message)}</td></tr>`;
    return;
  }
  if (state.liveStrategy !== s || state.liveStars !== k) return;  // selection changed meanwhile
  $("#liveDetailBody").innerHTML = data.predictions.length ? data.predictions.map((p) => {
    const drawn = new Set(p.numbers || []);
    const picks = p.ranking.slice(0, k).sort((a, b) => a - b).map((n) => ball(n, `sm ${drawn.has(n) ? "hit" : ""}`)).join("");
    const status = !p.hits ? "待開獎" : p.live ? "開獎前產生" : "開獎後補產生（不計入戰績）";
    return `<tr><td>${p.target_term}<br><span class="small muted">${taipeiTime(p.target_time).slice(0, 5)}</span></td>
      <td><div class="balls">${picks}</div></td>
      <td class="num">${p.hits ? p.hits[k - 1] : "—"}</td>
      <td class="num">${p.prizes ? fmt(p.prizes[k]) : "—"}</td>
      <td class="small">${status}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">尚無預測紀錄</td></tr>`;
}

/* ---------- backtest tab ---------- */
async function loadBacktest() {
  try {
    state.backtest = await getJSON("/api/backtest");
  } catch (e) {
    $("#btMeta").textContent = `無法載入回測結果：${e.message}`;
    return;
  }
  const bt = state.backtest;
  $("#theoryBody").innerHTML = STARS.map((k) => {
    const t = bt.theoretical[k];
    return `<tr><td>${k}星</td><td class="num">${pct(t.base.p_any_prize)}</td><td class="num">${pct(t.base.p_profit)}</td>
      <td class="num">${pct(t.base.return_rate)}</td><td class="num">${pct(t.promo.return_rate)}</td></tr>`;
  }).join("");
  const m = bt.meta;
  $("#btMeta").textContent = `回測期間 ${m.first_eval_date} ~ ${m.last_eval_date}，共 ${fmt(m.draws_evaluated)} 期，walk-forward（每期只用之前的資料）。` +
    `Bonferroni 校正後顯著門檻 p < ${m.bonferroni_alpha.toFixed(5)}，沒有任何策略達到。長條為平常獎金回收率，直線為理論值。`;
  $("#dailyBody").innerHTML = STARS.flatMap((k) => [["base", "平常"], ["promo", "快閃加碼"], ["promo_days", "歷史真實加碼日"]]
    .filter(([key]) => bt.daily_sessions[k][key])
    .map(([key, name]) => {
      const d = bt.daily_sessions[k][key];
      return `<tr><td>${k}星</td><td>${name}${key === "promo_days" ? `（${d.days} 天）` : ""}</td>
        <td class="num">${pct(d.flat_1x.p_day_profit, 1)}</td><td class="num">${signed(d.flat_1x.mean)}</td>
        <td class="num">${pct(d.martingale.p_day_profit, 1)}</td><td class="num">${pct(d.martingale.p_bust, 1)}</td></tr>`;
    })).join("");
  renderBacktest();
}

function renderBacktest() {
  chips($("#btChips"), state.btStars, (k) => { state.btStars = k; renderBacktest(); });
  const bt = state.backtest, k = state.btStars;
  const rows = Object.entries(bt.strategies)
    .map(([name, s]) => ({ name, desc: s.description, g: s.games[k] }))
    .sort((a, b) => b.g.base.return_rate - a.g.base.return_rate);
  $("#btBody").innerHTML = rows.map(({ name, desc, g }) => `<tr class="${name === "random" ? "control" : ""}">
    <td class="strategy-name">${esc(desc)}</td>
    <td class="num">${g.avg_hits.toFixed(4)}</td>
    <td class="num">${g.z_hits >= 0 ? "+" : ""}${g.z_hits.toFixed(2)}</td>
    <td class="num">${g.z_first_half.toFixed(2)} / ${g.z_second_half.toFixed(2)}</td>
    <td class="num">${pct(g.base.p_any_prize)}</td>
    <td class="num">${pct(g.base.return_rate)}</td>
    <td class="num">${pct(g.promo.return_rate)}</td>
    <td class="num">${fmt(g.base.max_drawdown_1x)}</td>
    <td class="num">${g.longest_no_prize_streak} 期</td></tr>`).join("");
  barChart($("#btChart"), rows.map((r) => ({
    label: r.desc, value: r.g.base.return_rate, control: r.name === "random",
    tip: `${r.desc}<br>回收率 ${pct(r.g.base.return_rate)}<br>平均命中 ${r.g.avg_hits.toFixed(4)}（z ${r.g.z_hits.toFixed(2)}）`,
  })), bt.theoretical[k].base.return_rate);
}

/* ---------- charts (plain SVG) ---------- */
const tooltip = () => $("#tooltip");
function bindTooltips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      const t = tooltip();
      t.innerHTML = el.dataset.tip;
      t.hidden = false;
      const x = Math.min(e.clientX + 14, window.innerWidth - t.offsetWidth - 8);
      t.style.left = `${x}px`;
      t.style.top = `${e.clientY + 14}px`;
    });
    el.addEventListener("mouseleave", () => { tooltip().hidden = true; });
  });
}

function niceMax(v) {
  const step = 0.1;
  return Math.ceil(v / step) * step;
}

function barChart(el, data, refValue) {
  const W = 760, rowH = 26, labelW = 210, padR = 56, top = 8, bottom = 28;
  const H = top + data.length * rowH + bottom;
  const max = niceMax(Math.max(refValue, ...data.map((d) => d.value)) * 1.02);
  const x = (v) => labelW + (v / max) * (W - labelW - padR);
  const ticks = [];
  for (let v = 0; v <= max + 1e-9; v += 0.1) ticks.push(v);
  const bars = data.map((d, i) => {
    const y = top + i * rowH + 5, h = 16, w = Math.max(x(d.value) - labelW, 1);
    const color = d.control ? "var(--text-3)" : "var(--accent)";
    // Rounded data end, square at the baseline.
    const path = `M${labelW},${y} h${w - 4} a4,4 0 0 1 4,4 v${h - 8} a4,4 0 0 1 -4,4 h${-(w - 4)} z`;
    return `<g data-tip="${esc(d.tip)}">
      <rect x="0" y="${top + i * rowH}" width="${W}" height="${rowH}" fill="transparent"/>
      <text x="${labelW - 8}" y="${y + 12}" text-anchor="end">${esc(d.label)}</text>
      <path d="${path}" fill="${color}"/>
      <text x="${labelW + w + 6}" y="${y + 12}">${pct(d.value, 1)}</text></g>`;
  }).join("");
  const grid = ticks.map((v) => `<line class="gridline" x1="${x(v)}" x2="${x(v)}" y1="${top}" y2="${H - bottom}"/>
    <text x="${x(v)}" y="${H - 8}" text-anchor="middle">${Math.round(v * 100)}%</text>`).join("");
  const ref = `<line class="ref" x1="${x(refValue)}" x2="${x(refValue)}" y1="${top - 4}" y2="${H - bottom}"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="各策略回收率">${grid}${bars}${ref}</svg>
    <div class="chart-legend"><span><i style="background:var(--accent)"></i>選號策略</span>
    <span><i style="background:var(--text-3)"></i>隨機對照組</span>
    <span><i style="background:var(--text-2);height:2px;width:14px"></i>理論回收率 ${pct(refValue)}</span></div>`;
  bindTooltips(el);
}

function histogram(el, values) {
  const sorted = [...values].sort((a, b) => a - b);
  const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
  let lo = q(0.005), hi = q(0.995);
  if (hi - lo < 1) hi = lo + 1;
  const nb = 32, bw = (hi - lo) / nb;
  const counts = new Array(nb).fill(0);
  values.forEach((v) => { counts[Math.max(0, Math.min(nb - 1, Math.floor((v - lo) / bw)))] += 1; });
  const W = 760, H = 240, padL = 48, padB = 30, top = 8;
  const maxC = Math.max(...counts);
  const cw = (W - padL) / nb;
  const bars = counts.map((c, i) => {
    const from = lo + i * bw, to = from + bw;
    const h = (c / maxC) * (H - padB - top);
    const color = (from + to) / 2 >= 0 ? "var(--gain)" : "var(--loss)";
    const xx = padL + i * cw + 1, w = Math.max(cw - 2, 1), y = H - padB - h;
    const r = Math.min(4, h, w / 2);
    const path = h > 0 ? `M${xx},${H - padB} v${-(h - r)} a${r},${r} 0 0 1 ${r},${-r} h${w - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} z` : "";
    return `<g data-tip="${fmt(from)} ~ ${fmt(to)} 元<br>${pct(c / values.length, 1)} 的場次">
      <rect x="${padL + i * cw}" y="${top}" width="${cw}" height="${H - padB - top}" fill="transparent"/>
      <path d="${path}" fill="${color}"/></g>`;
  }).join("");
  const axisTicks = [lo, lo + (hi - lo) / 2, hi].map((v) => {
    const xx = padL + ((v - lo) / (hi - lo)) * (W - padL);
    return `<text x="${xx}" y="${H - 8}" text-anchor="middle">${fmt(v)}</text>`;
  }).join("");
  const zeroX = padL + ((0 - lo) / (hi - lo)) * (W - padL);
  const zero = lo < 0 && hi > 0 ? `<line class="ref" x1="${zeroX}" x2="${zeroX}" y1="${top}" y2="${H - padB}"/>
    <text x="${zeroX + 4}" y="${top + 12}">損益 0</text>` : "";
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="每場損益分佈">
    <line class="gridline" x1="${padL}" x2="${W}" y1="${H - padB}" y2="${H - padB}"/>
    <text x="0" y="${top + 12}">場次</text>${bars}${zero}${axisTicks}</svg>
    <div class="chart-legend"><span><i style="background:var(--loss)"></i>虧損</span><span><i style="background:var(--gain)"></i>獲利</span><span>橫軸：每場損益（元）</span></div>`;
  bindTooltips(el);
}

/* ---------- simulator ---------- */
function simTables(k) {
  const g = state.overview.payouts.games;
  const opts = [{ label: "平常獎金", table: g[k].base_table }];
  const seen = new Set([JSON.stringify(g[k].base_table)]);
  const promos = [...state.overview.payouts.active_promotions, ...state.overview.payouts.upcoming_promotions];
  promos.forEach((p) => {
    if (!p.stars[k]) return;
    const t = { ...g[k].base_table };
    Object.entries(p.stars[k]).forEach(([h, v]) => { t[h] = v; });
    const key = JSON.stringify(t);
    if (!seen.has(key)) { seen.add(key); opts.push({ label: p.name, table: t }); }
  });
  return opts;
}

function initSimulator() {
  const form = $("#simForm");
  const fill = () => {
    if (!state.overview) return;
    const k = Number(form.stars.value || 3);
    const opts = simTables(k);
    form.table.innerHTML = opts.map((o, i) => `<option value="${i}">${esc(o.label)}</option>`).join("");
    form.table.value = state.overview.payouts.games[k].boosted ? String(opts.length - 1) : "0";
    form._opts = opts;
  };
  form.stars.innerHTML = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((k) => `<option value="${k}" ${k === 3 ? "selected" : ""}>${k}星</option>`).join("");
  form.stars.addEventListener("change", fill);
  const syncMode = () => { form.maxMult.disabled = form.mode.value === "fixed"; };
  form.mode.addEventListener("change", syncMode);
  syncMode();
  fill();
  form.addEventListener("submit", (e) => { e.preventDefault(); runSimulation(form); });
  if (state.overview) runSimulation(form);
}

/** Monte Carlo sessions: each draw's hit count is sampled from the exact hypergeometric pmf. */
function simulate({ k, table, mode, start, maxM, bankroll, draws, runs }) {
  const pmf = hypergeom(k), cdf = [];
  pmf.reduce((acc, p, i) => (cdf[i] = acc + p), 0);
  const prize = Array.from({ length: k + 1 }, (_, h) => table[h] || 0);
  const profits = new Array(runs);
  let busts = 0, staked = 0, paid = 0;
  for (let r = 0; r < runs; r++) {
    let bank = bankroll, m = start;
    for (let i = 0; i < draws; i++) {
      const stake = UNIT * m;
      if (stake > bank) { busts++; break; }
      const u = Math.random();
      let h = 0;
      while (h < k && u > cdf[h]) h++;
      const win = prize[h] * m;
      bank += win - stake;
      staked += stake; paid += win;
      if (mode === "step") m = win > stake ? start : Math.min(m + 1, maxM);
      else if (mode === "double") m = win > stake ? start : Math.min(m * 2, maxM);
    }
    profits[r] = bank - bankroll;
  }
  return { profits, busts, staked, paid, pmf, prize };
}

function runSimulation(form) {
  const k = Number(form.stars.value);
  const table = form._opts[Number(form.table.value)].table;
  const mode = form.mode.value;
  const start = Math.max(1, Math.min(50, Number(form.mult.value) || 1));
  const maxM = mode === "fixed" ? start : Math.max(start, Math.min(50, Number(form.maxMult.value) || start));
  const bankroll = Math.max(UNIT, Number(form.bankroll.value) || 10000);
  const runs = Number(form.runs.value);
  const r = simulate({ k, table, mode, start, maxM, bankroll, draws: Number(form.draws.value), runs });
  const arr = r.profits.sort((a, b) => a - b);
  const q = (p) => arr[Math.min(arr.length - 1, Math.floor(p * arr.length))];
  const mean = arr.reduce((a, b) => a + b, 0) / arr.length;
  const theo = r.pmf.reduce((a, p, h) => a + p * r.prize[h], 0) / UNIT;
  const tiles = [
    ["獲利機率", pct(arr.filter((v) => v > 0).length / arr.length, 1)],
    ["平均損益", `${signed(Math.round(mean))} 元`],
    ["中位數", `${signed(Math.round(q(0.5)))} 元`],
    ["5% ~ 95% 範圍", `${fmt(q(0.05))} ~ ${fmt(q(0.95))}`],
    ["爆倉率", pct(r.busts / runs, 1)],
    ["實際／理論回收率", `${pct(r.paid / r.staked, 1)} / ${pct(theo, 1)}`],
  ];
  $("#simTiles").innerHTML = tiles.map(([l, v]) => `<div class="tile"><div class="label">${l}</div><div class="value">${v}</div></div>`).join("");
  histogram($("#simChart"), arr);
}

/* ---------- history ---------- */
async function loadHistory() {
  try {
    const rows = await getJSON(`/api/draws?limit=${state.historyLimit}`);
    $("#historyList").innerHTML = rows.map((d) => `<div class="row">
      <div class="meta">第 ${d.draw_term} 期<br>${drawTime(d.draw_date, d.draw_index)}</div>
      <div class="balls">${d.numbers.map((n) => ball(n, `sm ${n === d.super_number ? "super" : ""}`)).join("")}</div></div>`).join("");
    $("#moreHistory").hidden = state.historyLimit >= 500;
  } catch (e) {
    $("#historyList").innerHTML = `<p class="empty">無法載入：${esc(e.message)}</p>`;
  }
}

/* ---------- boot ---------- */
async function boot() {
  initTheme();
  state.strategy = loadPref("strategy", state.strategy);
  state.stars = loadPref("stars", state.stars);
  state.liveStrategy = loadPref("liveStrategy", state.liveStrategy);
  state.budget = loadPref("budget", state.budget);
  state.plan = loadPref("plan", state.plan);
  $("#budgetInput").value = state.budget;
  $("#drawsSelect").value = String(state.plan);
  $("#strategySelect").addEventListener("change", (e) => selectStrategy(e.target.value));
  $("#budgetInput").addEventListener("change", (e) => {
    state.budget = Math.max(UNIT, Number(e.target.value) || 1000); savePref("budget", state.budget);
    if (state.overview) renderMultipliers();
  });
  $("#drawsSelect").addEventListener("change", (e) => {
    state.plan = Number(e.target.value); savePref("plan", state.plan);
    if (state.overview) renderMultipliers();
  });
  $("#moreHistory").addEventListener("click", () => { state.historyLimit = Math.min(500, state.historyLimit + 100); loadHistory(); });
  window.addEventListener("hashchange", route);
  await Promise.all([loadOverview(), loadLiveStats()]);
  if (state.overview) renderOverview();
  route();
  setInterval(tickCountdown, 1000);
  tickCountdown();
}

boot();
