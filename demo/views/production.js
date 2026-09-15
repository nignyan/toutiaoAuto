/* ============ 视图：生产引擎（任务实时推进 + 成片预览） ============ */
VIEWS = VIEWS || {};

VIEWS["生产引擎"] = function () {
  const running = Q.tasks().filter(t => t.status === "running");
  const done = Q.productions().slice(0, 9);
  return `
    <div class="section-title">BUILD ENGINE · 素材对齐 → 粗剪 → 字幕 → 包装 → 导出，全程自动
      <span class="right">并发上限 2 · 运行中 ${running.length}</span></div>

    ${running.length === 0 ? "" : `
    <div class="section-title" style="color:var(--info)">进行中的任务</div>
    ${running.map(t => {
      const ev = Q.event(t.eventId);
      return `
      <div class="task">
        <div style="min-width:0;flex:1">
          <div style="font-weight:600;font-size:13.5px">${ev ? ev.title : "—"}</div>
          <div class="tprog"><div class="bar" style="margin-top:10px"><i style="width:${t.progress}%;background:linear-gradient(90deg,#59a7ff,#8fc4ff)"></i></div></div>
          <div class="tstage">${t.rule} · ${t.stage}…</div>
        </div>
        <div class="pct" style="color:var(--info)">${t.progress}%</div>
      </div>`;
    }).join("")}`}

    <div class="section-title" style="margin-top:${running.length ? "22px" : "0"}">已产出成品（最近 ${done.length} 条）</div>
    ${done.length === 0 ? `<div class="empty"><div class="big">NO OUTPUT</div>等待就绪事件自动触发生产…</div>` : ""}
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">${done.map(p => {
      const st = PROD_STATUS[p.status];
      return `
      <div class="card clickable" onclick="A.openProduction('${p.id}')">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <span class="tag ${p.rule === "规则1" ? "ok" : "info"}">${p.rule}</span>
          <span class="chip-mini">${p.typeName}</span>
          <span class="tag ${st.cls}" style="margin-left:auto">${st.label}</span>
        </div>
        <h3 style="font-size:14px;margin:12px 0 8px;line-height:1.45">${p.title}</h3>
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span class="meta">质分 <b style="font-family:var(--mono);color:${p.quality.score >= 75 ? "var(--ok)" : "var(--warn)"}">${p.quality.score}</b>
            ${p.accountId && Q.account(p.accountId) ? " · " + Q.account(p.accountId).name : ""}</span>
          <button class="btn sm ghost" onclick="event.stopPropagation();A.previewProd('${p.id}')">预览成片</button>
        </div>
      </div>`;
    }).join("")}
    </div>`;
};

/* 成品详情抽屉 */
A.openProduction = function (id) {
  const p = Q.production(id);
  if (!p) return;
  const ev = Q.event(p.eventId);
  const st = PROD_STATUS[p.status];
  App.drawer(`
    <h2>${p.title}</h2>
    <div class="dsub">PRODUCTION · ${p.id} · ${fmtAgo(p.createdAt)}产出</div>
    <div class="dblock"><div class="bt">成品信息</div>
      <div class="kv"><span>形态</span><b>${p.typeName}${p.duration ? " · " + p.duration + "s" : ""}</b></div>
      <div class="kv"><span>命中规则</span><b>${p.rule}</b></div>
      <div class="kv"><span>质检状态</span><span class="tag ${st.cls}">${st.label}</span></div>
      <div class="kv"><span>质量分</span><b style="font-family:var(--mono)">${p.quality.score} / 100</b></div>
      <div class="kv"><span>分配账号</span><b>${p.accountId && Q.account(p.accountId) ? Q.account(p.accountId).name : "未分配"}</b></div>
    </div>
    <div class="dblock"><div class="bt">质检项</div>
      <div class="checks">${p.quality.checks.map(c => `<span class="ck ${c.pass ? "pass" : "fail"}">${c.pass ? "✓" : "✗"} ${c.name}</span>`).join("")}</div>
      ${p.quality.vetoes.length ? `<p class="meta" style="margin-top:8px;color:var(--danger)">一票否决：${p.quality.vetoes.join("、")}</p>` : ""}
    </div>
    <button class="btn primary" style="width:100%" onclick="A.closeDrawer();A.previewProd('${p.id}')">预览成片</button>
    ${ev ? `<button class="btn ghost" style="width:100%;margin-top:8px" onclick="A.closeDrawer();A.nav('选题中心');A.openEvent('${ev.id}')">查看来源事件</button>` : ""}
  `);
};

/* 成片预览弹窗：模拟播放器，可真实播放进度 */
A.previewProd = function (id) {
  const p = Q.production(id);
  if (!p) return;
  const dur = p.duration || 12;
  App.modal(`
    <h2>成片预览（模拟）</h2>
    <div class="player" id="player">
      <div class="screen">
        <div class="big">${p.type === "video" ? "▶" : "▦"}</div>
        <div class="ptitle">${p.title}</div>
        <span class="chip-mini">${p.typeName} · ${p.rule}</span>
      </div>
      <div class="ctrl">
        <button class="btn sm" id="playBtn">播放</button>
        <div class="pbar"><i id="pbarI" style="animation-duration:${dur}s"></i></div>
        <span id="ptime">00:00 / 00:${String(dur).padStart(2, "0")}</span>
      </div>
    </div>
    <p class="meta" style="margin-top:12px">演示环境不渲染真实视频；播放器用于验证「预览 → 确认发布」操作流。</p>
  `);
  let t = 0, timer = null;
  const btn = document.getElementById("playBtn");
  const player = document.getElementById("player");
  const ptime = document.getElementById("ptime");
  btn.onclick = () => {
    if (timer) { clearInterval(timer); timer = null; btn.textContent = "播放"; player.classList.remove("playing"); return; }
    player.classList.add("playing"); btn.textContent = "暂停";
    const bar = document.getElementById("pbarI");
    bar.style.animation = "none"; bar.offsetHeight; // 重启动画
    bar.style.animation = "";
    t = 0;
    timer = setInterval(() => {
      t++;
      ptime.textContent = "00:" + String(Math.min(t, dur)).padStart(2, "0") + " / 00:" + String(dur).padStart(2, "0");
      if (t >= dur) { clearInterval(timer); timer = null; btn.textContent = "重播"; player.classList.remove("playing"); }
    }, 1000);
  };
};