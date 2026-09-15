/* ============ 视图：热点雷达（无人值守自动采集） ============ */
VIEWS = VIEWS || {};

VIEWS["热点雷达"] = function () {
  const s = Store.state;
  const signals = Q.signals();
  const running = s.sim.running;
  return `
    <div class="section-title">LIVE SIGNAL · 自动采集${running ? "运行中" : "已暂停"}
      <span class="right">入池阈值 热度 ≥ ${s.sim.threshold}</span></div>

    <div class="stat-row">
      <div class="card stat"><div class="v">${s.stats.collected}</div><div class="l">今日采集信号</div></div>
      <div class="card stat"><div class="v">${s.stats.deduped}</div><div class="l">去重后</div></div>
      <div class="card stat"><div class="v" style="color:var(--accent)">${s.stats.clustered}</div><div class="l">聚合为事件</div></div>
      <div class="card stat"><div class="v" style="color:var(--ok)">${signals.filter(x => x.status === "new").length}</div><div class="l">待聚类信号</div></div>
    </div>

    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
        <span class="live-dot"></span>
        <span class="meta" style="flex:1;min-width:200px">多源接入：新闻/RSS · X · 抖音热榜 · 垂直信息源。信号按「时效 × 热度 × 增速 × 垂类匹配」评分，<b style="color:var(--ink)">达标自动聚类，无需人工</b>。</span>
        <label style="font-size:12px;color:var(--ink-dim)">入池阈值</label>
        <input type="range" min="40" max="90" step="5" value="${s.sim.threshold}" style="width:130px"
          onchange="A.setThreshold(this.value)">
        <button class="btn sm ghost" onclick="A.inject()">手动注入信号</button>
        <button class="btn sm ${running ? "ghost" : "primary"}" onclick="A.toggleSim()">${running ? "暂停采集" : "恢复采集"}</button>
      </div>
    </div>

    ${signals.length === 0 ? `<div class="empty"><div class="big">NO SIGNAL</div>等待引擎采集…</div>` : ""}
    ${signals.slice(0, 20).map(sg => `
      <div class="signal-row ${sg.isNew ? "new-in" : ""}" onclick="A.openSignal('${sg.id}')">
        <div class="s-score" style="color:${sg.heat >= 80 ? "var(--accent)" : "var(--ink)"}">${sg.heat}</div>
        <div class="s-main">
          <div class="s-title">${sg.title}</div>
          <div class="s-sub">${sg.src} · 增速 <b class="rise">${sg.rise}</b> · 垂类匹配 ${sg.match}% · ${fmtAgo(sg.ts)}</div>
        </div>
        ${sg.status === "aggregated"
          ? `<span class="tag ok">● 已聚类</span>`
          : sg.heat >= s.sim.threshold
            ? `<span class="tag info">聚类中…</span>`
            : `<span class="tag warn">低于阈值，仅监测</span>`}
      </div>`).join("")}
  `;
};

/* 信号详情抽屉 */
A.openSignal = function (id) {
  const sg = Q.signals().find(x => x.id === id);
  if (!sg) return;
  const ev = sg.eventId ? Q.event(sg.eventId) : null;
  App.drawer(`
    <h2>${sg.title}</h2>
    <div class="dsub">SIGNAL DETAIL · ${sg.id}</div>
    <div class="dblock"><div class="bt">评分明细</div>
      <div class="kv"><span>热度</span><b style="font-family:var(--mono)">${sg.heat} / 100</b></div>
      <div class="kv"><span>增速</span><b class="rise">${sg.rise}</b></div>
      <div class="kv"><span>垂类匹配</span><b>${sg.match}%（${sg.vertical}）</b></div>
      <div class="kv"><span>来源</span><b>${sg.src}</b></div>
      <div class="kv"><span>采集时间</span><b>${fmtClock(sg.ts)}（${fmtAgo(sg.ts)}）</b></div>
    </div>
    <div class="dblock"><div class="bt">聚合去向</div>
      ${ev
        ? `<div class="kv"><span>事件</span><b>${ev.title.slice(0, 18)}…</b></div>
           <div class="kv"><span>事件状态</span><span class="tag ${EV_STATUS[ev.status].cls}">${EV_STATUS[ev.status].label}</span></div>
           <button class="btn sm ghost" style="margin-top:8px" onclick="A.closeDrawer();A.nav('选题中心');A.openEvent('${ev.id}')">查看事件 →</button>`
        : `<p class="meta">${sg.heat >= Store.state.sim.threshold ? "聚类处理中，下个引擎周期自动完成。" : `热度低于入池阈值（${Store.state.sim.threshold}），仅监测不聚类。`}</p>`}
    </div>`);
};