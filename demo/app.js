/* ============ 全局路由壳：导航 / 流程步进条 / 抽屉 / 弹窗 / Toast / 活动流 ============ */

const NAV = [
  ["账号矩阵", "多域账号与垂类定向配置 · 直接决定自动入队去向"],
  ["热点雷达", "多源自动采集 · 评分达标自动聚类 · 无需人工"],
  ["选题中心", "事件聚类与规则判定 · 命中即自动触发生产"],
  ["素材资产", "入库即标密度与授权 · 补录授权可解锁暂缓事件"],
  ["生产引擎", "素材对齐到导出全自动 · 支持成片预览"],
  ["自动质检", "一票否决拦截 · 质量分 < 75 留档"],
  ["待发布队列", "排序 / 改标题 / 跳过 · 发布为唯一人工动作"],
  ["数据回流", "建议动作需人工确认 · 不自动调参"],
];
const FLOW = ["账号", "雷达", "选题", "素材", "生产", "质检", "队列", "回流"];
// 视图名 → 流程步进索引
const FLOW_INDEX = { "账号矩阵": 0, "热点雷达": 1, "选题中心": 2, "素材资产": 3, "生产引擎": 4, "自动质检": 5, "待发布队列": 6, "数据回流": 7 };
const LOG_KIND = { radar: "📡", cluster: "🧩", media: "🎞", build: "⚙️", qc: "🛡", queue: "🗂", publish: "🚀", reflux: "📊", acct: "👤", sys: "🔧" };

const App = {
  current: "待发布队列",
  vs: {}, // 各视图的临时筛选状态（不持久化）

  boot() {
    Store.load();
    // 渲染导航
    document.getElementById("nav").innerHTML = NAV.map((n, i) =>
      `<button data-nav="${n[0]}"><span class="idx">${String(i + 1).padStart(2, "0")}</span><span>${n[0]}</span><span class="cnt" data-cnt="${n[0]}"></span></button>`).join("");
    document.querySelectorAll("[data-nav]").forEach(b => b.onclick = () => this.nav(b.dataset.nav));
    document.getElementById("simBtn").onclick = () => Engine.toggle();
    document.getElementById("simSpeed").onchange = e => Engine.setSpeed(e.target.value);
    document.getElementById("simSpeed").value = String(Store.state.sim.speed);
    document.getElementById("logBtn").onclick = () => this.openLog();
    document.getElementById("resetBtn").onclick = () => this.askReset();
    document.getElementById("drawerMask").onclick = () => this.closeDrawer();
    document.getElementById("modalMask").onclick = () => this.closeModal();
    Engine.start();
    this.nav(this.current);
  },

  nav(name) {
    this.current = name;
    document.querySelectorAll("[data-nav]").forEach(b => b.classList.toggle("active", b.dataset.nav === name));
    const meta = NAV.find(n => n[0] === name);
    document.getElementById("pageTitle").textContent = name;
    document.getElementById("pageHint").textContent = meta ? meta[1] : "";
    this.renderPipeline();
    document.getElementById("stage").innerHTML = VIEWS[name]();
  },

  /* 流程步进条：实时显示各阶段数量与完成态 */
  renderPipeline() {
    const s = Store.state;
    const counts = [
      s.accounts.length,
      s.signals.filter(x => x.status === "new").length,
      s.events.length,
      s.assets.length,
      s.tasks.filter(t => t.status === "running").length,
      s.productions.length,
      s.queue.filter(q => q.status === "pending").length,
      s.suggestions.filter(x => x.status === "pending").length,
    ];
    const cur = FLOW_INDEX[this.current];
    document.getElementById("pipeline").innerHTML = FLOW.map((f, i) => `
      <div class="pipe ${i < cur ? "done" : i === cur ? "on" : ""}" onclick="App.nav('${NAV[i][0]}')">
        <div class="cap"><span>${String(i + 1).padStart(2, "0")}</span><b>${counts[i]}</b></div>
        <div class="track"></div><div class="lbl">${f}</div>
      </div>`).join("");
    // 导航计数徽标
    const navCnt = { "热点雷达": s.signals.filter(x => x.status === "new").length, "待发布队列": s.queue.filter(q => q.status === "pending").length, "数据回流": s.suggestions.filter(x => x.status === "pending").length, "自动质检": s.productions.filter(p => p.status === "held" || p.status === "blocked").length };
    document.querySelectorAll("[data-cnt]").forEach(el => {
      const v = navCnt[el.dataset.cnt] || 0;
      el.textContent = v || "";
      el.classList.toggle("hot", v > 0);
    });
  },

  refreshTop() {
    const b = document.getElementById("simBtn");
    const running = Store.state.sim.running;
    b.textContent = running ? "● 引擎运行中" : "‖ 引擎已暂停";
    b.classList.toggle("paused", !running);
    document.getElementById("logCount").textContent = Store.state.log.length;
  },

  /* 引擎 tick 后的软刷新：正在输入/看弹窗时只更新步进条，不打断操作 */
  softRefresh(force) {
    this.refreshTop();
    this.renderPipeline();
    if (!force) {
      const ae = document.activeElement;
      const busy = (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA" || ae.tagName === "SELECT"))
        || document.getElementById("modal").classList.contains("show")
        || document.getElementById("drawer").classList.contains("show");
      if (busy) return;
    }
    document.getElementById("stage").innerHTML = VIEWS[this.current]();
  },

  drawer(html) {
    document.getElementById("drawer").innerHTML = `<button class="x" onclick="A.closeDrawer()">✕</button>` + html;
    document.getElementById("drawer").classList.add("show");
    document.getElementById("drawerMask").classList.add("show");
  },
  closeDrawer() {
    document.getElementById("drawer").classList.remove("show");
    document.getElementById("drawerMask").classList.remove("show");
  },
  modal(html) {
    document.getElementById("modal").innerHTML = `<button class="x" onclick="A.closeModal()">✕</button>` + html;
    document.getElementById("modal").classList.add("show");
    document.getElementById("modalMask").classList.add("show");
  },
  closeModal() {
    document.getElementById("modal").classList.remove("show");
    document.getElementById("modalMask").classList.remove("show");
  },

  toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(this._tt);
    this._tt = setTimeout(() => t.classList.remove("show"), 2600);
  },

  openLog() {
    const logs = Store.state.log.slice(0, 60);
    this.drawer(`
      <h2>自动化活动流</h2>
      <div class="dsub">引擎与运营的每一次状态流转都记录在案</div>
      ${logs.length === 0 ? `<p class="meta">暂无记录</p>` : logs.map(l => `
        <div class="log-item"><span class="lt">${fmtClock(l.ts)}</span>
        <span class="lk">${LOG_KIND[l.kind] || "·"}</span><span>${l.text}</span></div>`).join("")}`);
  },

  askReset() {
    this.modal(`
      <h2>重置演示数据</h2>
      <p class="meta" style="margin-bottom:14px">将清空浏览器本地保存的全部状态（含你新建的账号、已发布记录），恢复为初始演示数据。</p>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn ghost" onclick="A.closeModal()">取消</button>
        <button class="btn danger" onclick="A.doReset()">确认重置</button>
      </div>`);
  },
};

/* 全局动作入口（A 已在 data.js 声明，这里合并基础动作；视图专属动作在各视图文件中挂载） */
Object.assign(A, {
  nav: n => App.nav(n),
  toggleSim: () => Engine.toggle(),
  setThreshold: v => { Store.state.sim.threshold = Number(v); Store.save(); App.toast(`入池阈值已调整为 ${v}，后续信号按新阈值聚类`); App.softRefresh(true); },
  inject: () => Engine.inject(),
  closeDrawer: () => App.closeDrawer(),
  closeModal: () => App.closeModal(),
  doReset: () => { Store.reset(); App.vs = {}; App.closeModal(); App.toast("演示数据已重置"); App.nav(App.current); App.refreshTop(); },
});

window.addEventListener("load", () => { App.boot(); App.refreshTop(); });