/* ============ 视图：数据回流（建议动作需人工确认，确认/驳回真实生效） ============ */
VIEWS = VIEWS || {};

VIEWS["数据回流"] = function () {
  const s = Store.state;
  const sugs = Q.suggestions();
  // 用已发布数生成稳定但有变化的模拟热度条
  const heats = Array.from({ length: 24 }, (_, i) =>
    Math.round(20 + 55 * Math.abs(Math.sin((i + s.stats.published * 3) / 3.4)) + (i > 10 && i < 15 ? 18 : 0)));
  return `
    <div class="section-title">REFLUX · MVP 仅输出建议动作 · <b style="color:var(--accent)">不自动调参</b></div>

    <div class="kpis">
      <div class="card kpi"><div class="v">${s.stats.published}</div><div class="l">今日已发布</div></div>
      <div class="card kpi"><div class="v">+18%</div><div class="l">「直击」模板完播率</div></div>
      <div class="card kpi"><div class="v">12:00</div><div class="l">图集最优时段</div></div>
      <div class="card kpi"><div class="v" style="color:var(--accent)">${sugs.filter(x => x.status === "pending").length}</div><div class="l">待确认建议</div></div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <b style="font-size:13px">24 小时发布热度（模拟）</b>
      <div class="heat-strip">${heats.map(h => `<i style="height:${h}%" title="${h}"></i>`).join("")}</div>
      <div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;color:var(--ink-dim);margin-top:4px">
        <span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></div>
    </div>

    <div class="section-title">建议动作（人工确认后才生效 · 单次调幅 ≤ 15% · 可一键回滚）</div>
    <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(300px,1fr))">
      ${sugs.map(g => `
      <div class="advice">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="tag ${g.status === "confirmed" ? "ok" : g.status === "rejected" ? "danger" : "info"}">${g.type}</span>
          <span class="chip-mini" style="margin-left:auto">预期 ${g.impact}</span>
        </div>
        <p>${g.text}</p>
        ${g.status === "pending" ? `
        <div class="ops">
          <button class="btn sm primary" onclick="A.sugConfirm('${g.id}')">确认采纳</button>
          <button class="btn sm ghost" onclick="A.sugReject('${g.id}')">驳回</button>
        </div>` : `
        <div class="ops">
          <span class="tag ${g.status === "confirmed" ? "ok" : "danger"}">${g.status === "confirmed" ? "✓ 已采纳并下发（模拟）" : "✗ 已驳回"}</span>
          ${g.status === "confirmed" ? `<button class="btn sm ghost" onclick="A.sugReject('${g.id}')">回滚</button>` : ""}
        </div>`}
      </div>`).join("")}
    </div>`;
};

A.sugConfirm = function (id) {
  const g = Q.suggestions().find(x => x.id === id);
  if (!g) return;
  g.status = "confirmed";
  log("reflux", `运营采纳建议：「${g.type}」（${g.impact}），已下发模拟生效`);
  Store.save(); App.toast("建议已采纳并下发（模拟）"); App.softRefresh(true);
};
A.sugReject = function (id) {
  const g = Q.suggestions().find(x => x.id === id);
  if (!g) return;
  const wasConfirmed = g.status === "confirmed";
  g.status = "rejected";
  log("reflux", wasConfirmed ? `建议「${g.type}」已一键回滚` : `建议「${g.type}」被运营驳回`);
  Store.save(); App.toast(wasConfirmed ? "已回滚该建议" : "已驳回"); App.softRefresh(true);
};