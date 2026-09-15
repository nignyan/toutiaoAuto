/* ============ 状态管理：单一数据源 + localStorage 持久化 + 业务规则 ============ */

const Store = {
  KEY: "hotflow_demo_v2",
  state: null,

  load() {
    try {
      const raw = localStorage.getItem(this.KEY);
      if (raw) { this.state = JSON.parse(raw); return; }
    } catch (e) { /* 损坏则重建 */ }
    this.state = Seed.build();
    this.save();
  },
  save() {
    try { localStorage.setItem(this.KEY, JSON.stringify(this.state)); } catch (e) {}
  },
  reset() {
    localStorage.removeItem(this.KEY);
    this.state = Seed.build();
    this.save();
  },
};

/* ---- 工具 ---- */
function uid(p) { return p + "_" + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4); }
function nowMs() { return Date.now(); }
function fmtAgo(ts) {
  const m = Math.max(0, Math.round((Date.now() - ts) / 60000));
  if (m < 1) return "刚刚";
  if (m < 60) return m + " 分钟前";
  const h = Math.floor(m / 60);
  if (h < 24) return h + " 小时前";
  return Math.floor(h / 24) + " 天前";
}
function fmtClock(ts) {
  const d = new Date(ts);
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
}
function log(kind, text) {
  Store.state.log.unshift({ ts: Date.now(), kind, text });
  if (Store.state.log.length > 200) Store.state.log.length = 200;
}

/* ---- 查询 ---- */
const Q = {
  signals: () => Store.state.signals,
  events: () => Store.state.events,
  assets: () => Store.state.assets,
  tasks: () => Store.state.tasks,
  productions: () => Store.state.productions,
  queue: () => Store.state.queue,
  accounts: () => Store.state.accounts,
  suggestions: () => Store.state.suggestions,
  event: id => Store.state.events.find(e => e.id === id),
  asset: id => Store.state.assets.find(a => a.id === id),
  production: id => Store.state.productions.find(p => p.id === id),
  account: id => Store.state.accounts.find(a => a.id === id),
  queueItem: id => Store.state.queue.find(q => q.id === id),
  eventAssets: ev => ev.assetIds.map(id => Q.asset(id)).filter(Boolean),
  usableAssets: ev => Q.eventAssets(ev).filter(a => a.auth === "cleared" && a.srcLevel !== "C"),
  accountQueue: accId => Store.state.queue
    .filter(q => q.accountId === accId)
    .sort((a, b) => a.order - b.order),
  accountUsage: accId => Store.state.queue
    .filter(q => q.accountId === accId && (q.status === "pending" || q.status === "published")).length,
};

/* ---- 规则评估：与后端 app/pipeline/format_decision.py 同口径（§5） ---- */
function evalRule(ev) {
  const usable = Q.usableAssets(ev);
  const videos = usable.filter(a => a.type === "video");
  const images = usable.filter(a => a.type === "image");
  const clearOk = a => a.clarity === "超清" || a.clarity === "清晰";
  const density = a => a.density == null ? 0 : a.density;

  const trace = [];
  const r1hit = videos.some(v => clearOk(v) && density(v) >= 70);
  trace.push({ rule: "规则1", desc: "存在「清晰度≥清晰」且「信息密度≥70」的视频", hit: r1hit });
  if (r1hit) return { rule: "规则1", format: "video", formatName: "30–60s 竖版视频", trace,
    reason: "存在高信息密度清晰视频，可独立成片" };

  const r3hit = videos.length > 0 && images.length > 0 && videos.some(v => clearOk(v) || density(v) >= 50);
  trace.push({ rule: "规则3", desc: "视频与图片兼有，视频达「清晰」或「密度≥50」之一", hit: r3hit });
  if (r3hit) return { rule: "规则3", format: "slideshow", formatName: "视频引子 + 图集混编", trace,
    reason: "视频作引子片段，图片承担背景与时间线" };

  const r2hit = videos.length === 0 && images.length >= 2;
  trace.push({ rule: "规则2", desc: "无可用视频，且图片 ≥ 2 张", hit: r2hit });
  if (r2hit) return { rule: "规则2", format: "slideshow", formatName: "图集视频", trace,
    reason: "多张现场/新闻图片，采用图集呈现" };

  trace.push({ rule: "规则4", desc: "无视频且图片 < 2 张（含全部未授权/C类）", hit: true });
  return { rule: "规则4", format: "defer", formatName: "暂缓生产", trace,
    reason: "无有效媒体，进入素材等待队列" };
}

/* ---- 质检评分（§4.5）：一票否决 + 质量分 ---- */
function runQC(ev, rule) {
  const usable = Q.usableAssets(ev);
  const all = Q.eventAssets(ev);
  const hasC = all.some(a => a.srcLevel === "C");
  const noAttr = usable.some(a => !a.attribution);
  const vetoes = [];
  if (hasC) vetoes.push("事件含 C 类（禁止）素材");
  if (noAttr) vetoes.push("存在素材署名缺失");

  const densities = usable.filter(a => a.type === "video" && a.density != null).map(a => a.density);
  const densityPart = densities.length ? densities.reduce((s, v) => s + v, 0) / densities.length * 0.28 : 8;
  const score = Math.max(40, Math.min(97, Math.round(60 + densityPart + ev.match * 0.06 + (Math.random() * 8 - 3))));

  const checks = Seed.qcChecks(vetoes.length === 0);
  return {
    score,
    vetoes,
    checks,
    status: vetoes.length ? "blocked" : (score < 75 ? "held" : "qualified"),
  };
}

/* ---- 账号分配：垂类匹配优先，跳过暂停账号与满配额账号 ---- */
function assignAccount(ev) {
  const cands = Store.state.accounts
    .filter(a => a.status === "active")
    .map(a => ({ a, fit: a.vertical === ev.vertical ? 2 : (a.role === "实验域" ? -1 : 1), room: a.quota - Q.accountUsage(a.id) }))
    .filter(x => x.room > 0)
    .sort((x, y) => y.fit - x.fit || y.room - x.room);
  return cands.length ? cands[0].a : null;
}

/* ---- 成品类型文案 ---- */
function productionTypeName(fmt) {
  return { video: "30–60s 竖版视频", slideshow: "图集视频", article: "图文资讯" }[fmt] || fmt;
}

/* ---- 事件状态文案 ---- */
const EV_STATUS = {
  ready: { label: "就绪 · 待自动生产", cls: "info" },
  producing: { label: "生产中", cls: "warn" },
  produced: { label: "已产出", cls: "ok" },
  deferred: { label: "暂缓 · 等待素材", cls: "danger" },
};
const PROD_STATUS = {
  qualified: { label: "质检通过", cls: "ok" },
  held: { label: "留档 · 待重试", cls: "warn" },
  blocked: { label: "一票否决拦截", cls: "danger" },
};
const QUEUE_STATUS = {
  pending: { label: "待发布", cls: "info" },
  published: { label: "已发布", cls: "ok" },
  skipped: { label: "已跳过", cls: "danger" },
};