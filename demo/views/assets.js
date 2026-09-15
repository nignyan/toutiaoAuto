/* ============ 视图：素材资产池（入库即标密度与授权，可补录授权解锁生产） ============ */
VIEWS = VIEWS || {};

VIEWS["素材资产"] = function () {
  const f = App.vs.assetFilter || "all";
  const list = Q.assets().filter(a =>
    f === "all" ? true :
    f === "pending" ? a.auth !== "cleared" :
    a.type === f);
  const chip = (key, label) => `<button class="fchip ${f === key ? "on" : ""}" onclick="A.assetFilter('${key}')">${label}</button>`;
  const pendingCount = Q.assets().filter(a => a.auth === "pending").length;
  return `
    <div class="section-title">MEDIA POOL · 入库即计算信息密度并标注来源分级/授权
      <span class="right">${Q.assets().length} 条素材 · ${pendingCount} 条待授权</span></div>
    <div class="filters">
      ${chip("all", "全部")}${chip("video", "视频")}${chip("image", "图片")}${chip("text", "文字")}
      ${chip("pending", `待授权 ${pendingCount ? "· " + pendingCount : ""}`)}
    </div>
    ${list.length === 0 ? `<div class="empty"><div class="big">EMPTY</div>当前筛选下没有素材</div>` : ""}
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(250px,1fr))">${list.map(a => {
      const ev = Q.event(a.eventId);
      const authTag = a.auth === "cleared" ? `<span class="tag ok">已授权</span>`
        : a.auth === "pending" ? `<span class="tag warn">待授权</span>` : `<span class="tag danger">已禁用</span>`;
      return `
      <div class="card clickable" onclick="A.openAsset('${a.id}')">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <span class="tag ${a.type === "video" ? "ok" : a.type === "image" ? "info" : ""}">${{ video: "视频", image: "图片", text: "文字" }[a.type]}</span>
          ${authTag}
          <span class="chip-mini" style="margin-left:auto">${a.srcLevel} 级</span>
        </div>
        <div style="font-weight:600;font-size:13px;margin-bottom:10px">${a.name}</div>
        <div style="display:flex;justify-content:space-between;align-items:flex-end">
          <div><div style="font-family:var(--mono);font-size:10.5px;color:var(--ink-dim)">清晰度</div>
            <div style="font-size:13px">${a.clarity || "—"}</div></div>
          <div style="text-align:right"><div style="font-family:var(--mono);font-size:10.5px;color:var(--ink-dim)">信息密度</div>
            <div style="font-family:var(--mono);font-size:20px;font-weight:600;color:${a.density == null ? "var(--ink-dim)" : a.density >= 70 ? "var(--ok)" : a.density >= 50 ? "var(--warn)" : "var(--danger)"}">${a.density == null ? "N/A" : a.density}</div></div>
          <div style="text-align:right"><div style="font-family:var(--mono);font-size:10.5px;color:var(--ink-dim)">时长</div>
            <div style="font-family:var(--mono);font-size:15px">${a.dur ? "0:" + String(a.dur).padStart(2, "0") : "—"}</div></div>
        </div>
        <div class="meta" style="margin-top:10px">所属事件：${ev ? ev.title.slice(0, 14) + "…" : "—"}</div>
      </div>`;
    }).join("")}
    </div>`;
};

A.assetFilter = function (f) { App.vs.assetFilter = f; App.softRefresh(true); };

/* 素材详情：完整字段 + 指纹去重组 + 授权补录（真实改状态） */
A.openAsset = function (id) {
  const a = Q.asset(id);
  if (!a) return;
  const ev = Q.event(a.eventId);
  const siblings = Q.assets().filter(x => x.fingerprint === a.fingerprint && x.id !== a.id);
  App.drawer(`
    <h2>${a.name}</h2>
    <div class="dsub">ASSET · ${a.id} · ${fmtAgo(a.ingestedAt)}入库</div>

    <div class="dblock"><div class="bt">素材属性</div>
      <div class="kv"><span>类型</span><b>${{ video: "视频", image: "图片", text: "文字" }[a.type]}</b></div>
      <div class="kv"><span>清晰度</span><b>${a.clarity || "—"}</b></div>
      <div class="kv"><span>信息密度</span><b style="font-family:var(--mono)">${a.density == null ? "N/A" : a.density + " / 100"}</b></div>
      <div class="kv"><span>时长</span><b>${a.dur ? a.dur + " 秒" : "—"}</b></div>
      <div class="kv"><span>去重指纹</span><b style="font-family:var(--mono);font-size:11px">${a.fingerprint}</b></div>
      ${siblings.length ? `<div class="kv"><span>同指纹素材</span><b>${siblings.length} 条已标记去重</b></div>` : ""}
    </div>

    <div class="dblock"><div class="bt">来源与授权（§4.3）</div>
      <div class="kv"><span>来源分级</span><span class="tag ${a.srcLevel === "A" ? "ok" : a.srcLevel === "B" ? "info" : "danger"}">${a.srcLevel} 级 · ${{ A: "可直接使用", B: "限定条件使用", C: "禁止使用" }[a.srcLevel]}</span></div>
      <div class="kv"><span>授权状态</span><span class="tag ${a.auth === "cleared" ? "ok" : a.auth === "pending" ? "warn" : "danger"}">${{ cleared: "cleared · 已确认", pending: "pending · 待确认", blocked: "blocked · 已禁用" }[a.auth]}</span></div>
      <div class="kv"><span>署名文本</span><b style="max-width:220px;text-align:right">${a.attribution || "（缺失）"}</b></div>
      ${a.auth === "cleared"
        ? `<p class="meta" style="margin-top:8px;color:var(--ok)">✓ 该素材可进入生产</p>`
        : a.srcLevel === "C"
          ? `<p class="meta" style="margin-top:8px;color:var(--danger)">C 类素材视同「无有效媒体」，不可补录解锁。</p>`
          : `
        <label class="f">补录授权凭证 / 署名文本</label>
        <input id="authAttr" style="width:100%" placeholder="例：来源：合作媒体（已取得授权）" value="">
        <button class="btn primary" style="width:100%;margin-top:10px" onclick="A.clearAuth('${a.id}')">确认授权，解锁素材</button>
        <p class="meta" style="margin-top:8px">解锁后若所属事件因此满足形态条件，将自动转入生产候选。</p>`}
    </div>

    ${ev ? `<div class="dblock"><div class="bt">所属事件</div>
      <div class="kv"><span>事件</span><b style="max-width:230px;text-align:right">${ev.title}</b></div>
      <div class="kv"><span>事件状态</span><span class="tag ${EV_STATUS[ev.status].cls}">${EV_STATUS[ev.status].label}</span></div>
      <button class="btn sm ghost" style="margin-top:8px" onclick="A.closeDrawer();A.nav('选题中心');A.openEvent('${ev.id}')">查看事件 →</button>
    </div>` : ""}
  `);
};

/* 补录授权：真实改状态，并可能让暂缓事件自动就绪 */
A.clearAuth = function (id) {
  const a = Q.asset(id);
  if (!a) return;
  const attr = (document.getElementById("authAttr") || {}).value || "来源：已补录授权";
  a.auth = "cleared";
  a.attribution = attr;
  const ev = Q.event(a.eventId);
  let extra = "";
  if (ev && ev.status === "deferred") {
    const rule = evalRule(ev);
    if (rule.format !== "defer") { ev.status = "ready"; extra = `；所属事件命中${rule.rule}，已自动转入生产候选`; }
  }
  log("media", `素材「${a.name}」授权已补录确认${extra}`);
  Store.save();
  App.toast("授权已确认，素材解锁" + extra);
  App.closeDrawer();
  App.softRefresh(true);
};