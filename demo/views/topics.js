/* ============ 视图：选题中心（事件聚类 · 命中即自动生产） ============ */
VIEWS = VIEWS || {};

VIEWS["选题中心"] = function () {
  const f = App.vs.topicFilter || "all";
  const list = Q.events().filter(e => f === "all" || e.status === f);
  const chip = (key, label) => `<button class="fchip ${f === key ? "on" : ""}" onclick="A.topicFilter('${key}')">${label}</button>`;
  return `
    <div class="section-title">EVENT CLUSTER · 命中规则与合规素材后<b style="color:var(--accent)">自动触发生产</b>
      <span class="right">共 ${Q.events().length} 个事件</span></div>
    <div class="filters">
      ${chip("all", "全部")}${chip("ready", "就绪")}${chip("producing", "生产中")}
      ${chip("produced", "已产出")}${chip("deferred", "暂缓/等待素材")}
    </div>
    ${list.length === 0 ? `<div class="empty"><div class="big">EMPTY</div>当前筛选下没有事件</div>` : ""}
    <div class="ev-grid">${list.map(ev => {
      const rule = evalRule(ev);
      const st = EV_STATUS[ev.status];
      return `
      <div class="card ev-card" onclick="A.openEvent('${ev.id}')">
        <div class="etop">
          <span class="tag ${rule.rule === "规则1" ? "ok" : rule.rule === "规则4" ? "danger" : "info"}">${rule.rule}</span>
          <span class="chip-mini">${rule.formatName}</span>
          <span class="tag ${st.cls}" style="margin-left:auto">${st.label}</span>
        </div>
        <h3>${ev.title}</h3>
        <div class="meta">热度 ${ev.score} · 垂类 ${ev.vertical} · 匹配 ${ev.match}% · 素材 ${ev.assetIds.length} 条 · ${fmtAgo(ev.createdAt)}</div>
        <div class="bar" style="margin-top:10px"><i style="width:${ev.score}%;background:linear-gradient(90deg,#ffb020,#ffd27a)"></i></div>
        ${ev.status === "deferred" ? `<div class="meta" style="margin-top:8px;color:var(--warn)">已重试取数 ${ev.retries} 次 · 跨日保留 24h</div>` : ""}
      </div>`;
    }).join("")}
    </div>`;
};

A.topicFilter = function (f) { App.vs.topicFilter = f; App.softRefresh(true); };

/* 事件详情抽屉：时间线 + 素材 + 规则判定追溯 */
A.openEvent = function (id) {
  const ev = Q.event(id);
  if (!ev) return;
  const rule = evalRule(ev);
  const assets = Q.eventAssets(ev);
  const st = EV_STATUS[ev.status];
  App.drawer(`
    <h2>${ev.title}</h2>
    <div class="dsub">EVENT · ${ev.id} · ${fmtAgo(ev.createdAt)}创建</div>

    <div class="dblock"><div class="bt">状态与判定</div>
      <div class="kv"><span>当前状态</span><span class="tag ${st.cls}">${st.label}</span></div>
      <div class="kv"><span>命中规则</span><b>${rule.rule} → ${rule.formatName}</b></div>
      <div class="kv"><span>判定说明</span><b style="max-width:230px;text-align:right">${rule.reason}</b></div>
    </div>

    <div class="dblock"><div class="bt">规则追溯（自上而下 · 命中即止）</div>
      ${rule.trace.map(t => `
        <div class="kv"><span>${t.rule}　${t.desc}</span>
        <span class="tag ${t.hit ? "ok" : ""}" style="${t.hit ? "" : "color:#5c6a7c;background:#1c2634"}">${t.hit ? "✓ 命中" : "✗"}</span></div>`).join("")}
    </div>

    <div class="dblock"><div class="bt">关联素材（${assets.length}）</div>
      ${assets.map(a => `
        <div class="kv clickable" onclick="A.closeDrawer();A.nav('素材资产');A.openAsset('${a.id}')">
          <span>${a.name}</span>
          <span><span class="tag ${a.auth === "cleared" ? "ok" : a.auth === "pending" ? "warn" : "danger"}">${a.auth === "cleared" ? "已授权" : a.auth === "pending" ? "待授权" : "禁用"}</span>
          <span class="chip-mini">${a.srcLevel} 级</span></span>
        </div>`).join("")}
      ${assets.some(a => a.auth === "pending") ? `<button class="btn sm primary" style="margin-top:8px" onclick="A.closeDrawer();A.nav('素材资产')">去素材池补录授权 →</button>` : ""}
    </div>

    <div class="dblock"><div class="bt">事件时间线（${ev.timeline.length} 条信号聚合）</div>
      ${ev.timeline.slice(0, 6).map(t => `
        <div class="kv"><span>${fmtClock(t.ts)} · ${t.src}</span><b style="font-family:var(--mono)">${t.heat} <b class="rise" style="font-size:10px">${t.rise}</b></b></div>`).join("")}
    </div>

    ${ev.status === "deferred" ? `<button class="btn primary" style="width:100%" onclick="A.retryEvent('${ev.id}')">立即重试取数</button>` : ""}
  `);
};

/* 暂缓事件：手动重试取数（真实走一次引擎补素材逻辑） */
A.retryEvent = function (id) {
  const ev = Q.event(id);
  if (!ev) return;
  // 直接对该事件执行一次补素材
  const isVideo = Math.random() < 0.5;
  ev.retries++;
  const a = {
    id: uid("as"), eventId: ev.id,
    name: Seed.assetName(ev.kw, { t: isVideo ? "video" : "image" }, ev.retries + 2),
    type: isVideo ? "video" : "image", clarity: "清晰",
    density: isVideo ? Math.round(45 + Math.random() * 40) : null,
    dur: isVideo ? Math.round(20 + Math.random() * 40) : null,
    srcLevel: "B", auth: "cleared", attribution: "来源：合作媒体",
    fingerprint: "fp_" + ev.kw + "_m" + ev.retries, ingestedAt: nowMs(),
  };
  Store.state.assets.push(a);
  ev.assetIds.push(a.id);
  const rule = evalRule(ev);
  if (rule.format !== "defer") ev.status = "ready";
  log("media", `手动重试取数：「${ev.kw}」补到 ${a.type === "video" ? "视频" : "图片"}素材，${ev.status === "ready" ? "命中" + rule.rule + "，自动就绪" : "仍不足，继续等待"}`);
  Store.save();
  App.toast(ev.status === "ready" ? `已补到素材，命中${rule.rule}，自动转入生产候选` : "已补到素材，但仍不满足形态条件");
  App.closeDrawer();
  App.softRefresh(true);
};