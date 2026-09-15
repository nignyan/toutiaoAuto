/* ============ 视图：待发布队列（排序/改标题/预览/跳过/发布，全真实状态） ============ */
VIEWS = VIEWS || {};

function defaultQueueTab() {
  const accs = Q.accounts().filter(a => a.status === "active");
  return accs.length ? accs[0].id : (Q.accounts()[0] || {}).id;
}

VIEWS["待发布队列"] = function () {
  if (!App.vs.queueTab || !Q.account(App.vs.queueTab)) App.vs.queueTab = defaultQueueTab();
  const tab = App.vs.queueTab;
  const accs = Q.accounts();
  const acc = Q.account(tab);
  const items = acc ? Q.accountQueue(acc.id) : [];
  const used = acc ? Q.accountUsage(acc.id) : 0;

  return `
    <div class="section-title">DAILY SHIP · 队列全自动生成 · <b style="color:var(--accent)">发布为唯一人工动作</b></div>

    <div class="q-tabs">
      ${accs.map(a => `<div class="q-tab ${a.id === tab ? "on" : ""}" onclick="A.queueTab('${a.id}')">
        ${a.name}<small>${Q.accountUsage(a.id)}/${a.quota}</small>${a.status === "paused" ? " ⏸" : ""}</div>`).join("")}
    </div>

    ${acc ? `
    <div class="quota-line">
      <span>${acc.vertical} · ${acc.winStart}–${acc.winEnd} 发布窗口</span>
      <div class="bar"><i style="width:${Math.min(100, used / acc.quota * 100)}%;background:${used >= acc.quota ? "var(--danger)" : "linear-gradient(90deg,#ffb020,#ffd27a)"}"></i></div>
      <span>今日配额 ${used} / ${acc.quota}</span>
      ${acc.status === "paused" ? `<span class="tag warn">账号已暂停，引擎不再为其自动入队</span>` : ""}
    </div>

    ${items.length === 0 ? `<div class="empty"><div class="big">QUEUE EMPTY</div>引擎质检通过后将自动入队到这里</div>` : `
    <div class="card"><table>
      <tr><th style="width:30px">#</th><th>标题（点 ✎ 直接改）</th><th>形态</th><th>质分</th><th>状态 / 操作</th></tr>
      ${items.map((q, i) => {
        const p = Q.production(q.productionId);
        if (!p) return "";
        const st = QUEUE_STATUS[q.status];
        return `<tr>
          <td style="font-family:var(--mono);color:var(--ink-dim)">${q.status === "pending" ? `
            <button class="btn sm ghost" style="padding:1px 6px" ${i === 0 || items[i-1].status !== "pending" ? "disabled" : ""} onclick="A.moveQ('${q.id}',-1)">↑</button>
            <button class="btn sm ghost" style="padding:1px 6px" ${!items.slice(i+1).some(x => x.status === "pending") ? "disabled" : ""} onclick="A.moveQ('${q.id}',1)">↓</button>` : "—"}</td>
          <td class="col-title" id="qt_${q.id}">${p.title}<small>${fmtAgo(q.createdAt)}入队 · ${p.rule}</small></td>
          <td><small>${p.typeName}</small></td>
          <td style="font-family:var(--mono);color:${p.quality.score >= 75 ? "var(--ok)" : "var(--warn)"}">${p.quality.score}</td>
          <td>
            ${q.status === "pending" ? `
              <div class="row-actions">
                <button class="btn sm ghost" onclick="A.previewProd('${p.id}')">预览</button>
                <button class="btn sm ghost" onclick="A.editTitle('${q.id}')">✎ 改标题</button>
                <button class="btn sm ghost" onclick="A.skipQ('${q.id}')">跳过</button>
                <button class="btn sm primary" onclick="A.askPublish('${q.id}')">提交发布</button>
              </div>` : ""}
            ${q.status === "published" ? `<span class="tag ok">✓ 已发布</span> <small style="color:var(--ink-dim)">${q.publishedAt ? fmtClock(q.publishedAt) : ""}</small>` : ""}
            ${q.status === "skipped" ? `<span class="tag danger">已跳过</span> <button class="btn sm ghost" style="margin-left:6px" onclick="A.undoSkip('${q.id}')">撤销跳过</button>` : ""}
          </td>
        </tr>`;
      }).join("")}
    </table></div>`}` : `<div class="empty"><div class="big">NO ACCOUNT</div>请先在「账号矩阵」创建账号</div>`}`;
};

A.queueTab = function (id) { App.vs.queueTab = id; App.softRefresh(true); };

/* 队列内排序（仅待发布项参与） */
A.moveQ = function (id, dir) {
  const q = Q.queueItem(id);
  if (!q) return;
  const items = Q.accountQueue(q.accountId).filter(x => x.status === "pending");
  const idx = items.findIndex(x => x.id === id);
  const swap = items[idx + dir];
  if (!swap) return;
  const tmp = q.order; q.order = swap.order; swap.order = tmp;
  Store.save(); App.softRefresh(true);
};

/* 行内改标题 */
A.editTitle = function (id) {
  const q = Q.queueItem(id);
  const p = q && Q.production(q.productionId);
  if (!p) return;
  const td = document.getElementById("qt_" + id);
  td.innerHTML = `<input class="title-edit" id="qi_${id}" value="${p.title.replace(/"/g, "&quot;")}">`;
  const input = document.getElementById("qi_" + id);
  input.focus(); input.select();
  const commit = () => {
    const v = input.value.trim();
    if (v && v !== p.title) { p.title = v; log("queue", `标题已修改：「${v.slice(0, 18)}…」`); Store.save(); App.toast("标题已更新"); }
    App.softRefresh(true);
  };
  input.onblur = commit;
  input.onkeydown = e => { if (e.key === "Enter") commit(); if (e.key === "Escape") App.softRefresh(true); };
};

A.skipQ = function (id) {
  const q = Q.queueItem(id);
  if (!q) return;
  q.status = "skipped";
  log("queue", `「${(Q.production(q.productionId) || {}).title || ""}」被运营跳过`);
  Store.save(); App.toast("已跳过该条，可撤销"); App.softRefresh(true);
};
A.undoSkip = function (id) {
  const q = Q.queueItem(id);
  if (!q) return;
  q.status = "pending";
  log("queue", "撤销跳过，条目回到待发布");
  Store.save(); App.softRefresh(true);
};

/* 发布：二次确认弹窗 → 真实改状态 */
A.askPublish = function (id) {
  const q = Q.queueItem(id);
  const p = q && Q.production(q.productionId);
  const acc = q && Q.account(q.accountId);
  if (!p || !acc) return;
  App.modal(`
    <h2>确认发布</h2>
    <div class="dblock">
      <div class="kv"><span>账号</span><b>${acc.name}（${acc.vertical}）</b></div>
      <div class="kv"><span>标题</span><b style="max-width:300px;text-align:right">${p.title}</b></div>
      <div class="kv"><span>形态</span><b>${p.typeName} · ${p.rule}</b></div>
      <div class="kv"><span>质量分</span><b style="font-family:var(--mono)">${p.quality.score}</b></div>
    </div>
    <p class="meta" style="margin-bottom:14px">演示环境不真正调用头条发布接口；确认后本条状态流转为「已发布」并计入数据回流。</p>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn ghost" onclick="A.closeModal()">再想想</button>
      <button class="btn primary" onclick="A.confirmPublish('${id}')">确认发布</button>
    </div>`);
};
A.confirmPublish = function (id) {
  const q = Q.queueItem(id);
  const p = q && Q.production(q.productionId);
  const acc = q && Q.account(q.accountId);
  if (!q || q.status !== "pending") return;
  q.status = "published";
  q.publishedAt = nowMs();
  Store.state.stats.published++;
  log("publish", `「${p.title.slice(0, 16)}…」已由运营确认发布至「${acc.name}」`);
  Store.save();
  App.closeModal();
  App.toast(`已发布到「${acc.name}」（模拟）`);
  App.softRefresh(true);
};