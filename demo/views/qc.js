/* ============ 视图：自动质检（一票否决 + 质量分 + 留档重试） ============ */
VIEWS = VIEWS || {};

VIEWS["自动质检"] = function () {
  const list = Q.productions();
  const blocked = list.filter(p => p.status === "blocked");
  const held = list.filter(p => p.status === "held");
  const passed = list.filter(p => p.status === "qualified");
  return `
    <div class="section-title">QUALITY GATE · 硬性一票否决直接拦截 · 质量分 &lt; 75 留档降级
      <span class="right">通过 ${passed.length} · 留档 ${held.length} · 拦截 ${blocked.length}</span></div>

    <div class="stat-row" style="grid-template-columns:repeat(3,1fr)">
      <div class="card stat"><div class="v" style="color:var(--ok)">${passed.length}</div><div class="l">已放行入队</div></div>
      <div class="card stat"><div class="v" style="color:var(--warn)">${held.length}</div><div class="l">留档待重试</div></div>
      <div class="card stat"><div class="v" style="color:var(--danger)">${blocked.length}</div><div class="l">一票否决拦截</div></div>
    </div>

    ${list.length === 0 ? `<div class="empty"><div class="big">NO QC YET</div>首个成片产出后自动质检</div>` : `
    <div class="card"><table>
      <tr><th>产物</th><th>形态/规则</th><th>质检项</th><th>质量分</th><th>结论 / 操作</th></tr>
      ${list.map(p => {
        const st = PROD_STATUS[p.status];
        return `<tr>
          <td class="col-title clickable" onclick="A.openProduction('${p.id}')">${p.title}<small>${fmtAgo(p.createdAt)}</small></td>
          <td><small>${p.typeName} · ${p.rule}</small></td>
          <td><div class="checks">${p.quality.checks.map(c => `<span class="ck ${c.pass ? "pass" : "fail"}" title="${c.name}">${c.pass ? "✓" : "✗"}</span>`).join("")}</div>
            ${p.quality.vetoes.length ? `<small style="color:var(--danger)">${p.quality.vetoes[0]}</small>` : ""}</td>
          <td style="font-family:var(--mono);color:${p.quality.score >= 75 ? "var(--ok)" : "var(--warn)"}">${p.quality.score}</td>
          <td>
            <span class="tag ${st.cls}">${st.label}</span>
            ${p.status === "held" ? `<button class="btn sm primary" style="margin-left:6px" onclick="A.qcRetry('${p.id}')">立即重试</button>` : ""}
            ${p.status === "blocked" ? `<button class="btn sm danger" style="margin-left:6px" onclick="A.openProduction('${p.id}')">风险详情</button>` : ""}
          </td>
        </tr>`;
      }).join("")}
    </table></div>`}`;
};

/* 留档重试：真实重新评分，达标即自动入队 */
A.qcRetry = function (id) {
  const p = Q.production(id);
  if (!p || p.status !== "held") return;
  p.retries = (p.retries || 0) + 1;
  const ev = Q.event(p.eventId);
  // 重试模拟：二次剪辑/换模板后重评分，+4~12 分
  p.quality.score = Math.min(97, p.quality.score + Math.round(4 + Math.random() * 8));
  if (p.quality.score >= 75) {
    p.status = "qualified";
    const acc = ev ? assignAccount(ev) : null;
    if (acc) {
      p.accountId = acc.id;
      const maxOrder = Math.max(-1, ...Store.state.queue.filter(q => q.accountId === acc.id).map(q => q.order));
      Store.state.queue.push({ id: uid("q"), productionId: p.id, accountId: acc.id, status: "pending", order: maxOrder + 1, createdAt: nowMs(), publishedAt: null });
      log("qc", `「${p.title.slice(0, 14)}…」重试后质量分 ${p.quality.score}，已自动入队「${acc.name}」`);
      App.toast(`重试通过（${p.quality.score} 分），已自动入队「${acc.name}」`);
    } else {
      log("qc", `「${p.title.slice(0, 14)}…」重试通过但无可用账号，继续留档`);
      App.toast(`重试通过（${p.quality.score} 分），但无可用账号（暂停/配额满），继续留档`);
    }
  } else {
    log("qc", `「${p.title.slice(0, 14)}…」第 ${p.retries} 次重试仍 ${p.quality.score} 分，继续留档`);
    App.toast(`重试后 ${p.quality.score} 分，仍低于 75，继续留档`);
  }
  Store.save();
  App.softRefresh(true);
};