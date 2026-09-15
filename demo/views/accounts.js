/* ============ 视图：账号矩阵（垂类/多域/配额/窗口，配置真实影响自动入队） ============ */
VIEWS = VIEWS || {};

VIEWS["账号矩阵"] = function () {
  const accs = Q.accounts();
  return `
    <div class="section-title">ACCOUNT MATRIX · 域配置直接决定引擎的自动入队去向</div>
    <div class="card">
      <table>
        <tr><th>账号</th><th>垂类定向</th><th>角色</th><th>今日配额</th><th>发布窗口</th><th>状态</th><th>操作</th></tr>
        ${accs.map(a => {
          const used = Q.accountUsage(a.id);
          return `<tr>
            <td class="col-title clickable" onclick="A.openAccount('${a.id}')">${a.name}</td>
            <td><span class="chip-mini">${a.vertical}</span></td>
            <td><span class="tag ${a.role === "主域" ? "ok" : a.role.startsWith("测试") ? "info" : "warn"}">${a.role}</span></td>
            <td style="font-family:var(--mono)">${used} / ${a.quota}</td>
            <td><small>${a.winStart}–${a.winEnd}</small></td>
            <td><span class="tag ${a.status === "active" ? "ok" : "warn"}">${a.status === "active" ? "在线" : "暂停"}</span></td>
            <td><div class="row-actions">
              <button class="btn sm ghost" onclick="A.openAccount('${a.id}')">编辑</button>
              <button class="btn sm ${a.status === "active" ? "ghost" : "primary"}" onclick="A.toggleAccount('${a.id}')">${a.status === "active" ? "暂停" : "恢复"}</button>
              ${a.role === "实验域" ? `<button class="btn sm danger" onclick="A.delAccount('${a.id}')">删除</button>` : ""}
            </div></td>
          </tr>`;
        }).join("")}
      </table>
      <div style="margin-top:12px"><button class="btn primary" onclick="A.newAccount()">+ 新建账号</button></div>
    </div>

    <div class="card" style="margin-top:14px">
      <b style="font-size:13px">多域测试 · 自动隔离</b>
      <div class="meta" style="margin-top:8px;line-height:1.7">
        · 主域承载稳定垂类内容；测试域/实验域跑选题与形态实验，数据互不污染。<br>
        · 暂停账号后引擎立即停止向其自动入队；恢复后继续。<br>
        · 垂类与剩余配额决定新成品的自动分配优先级（垂类精确匹配 &gt; 通用 &gt; 实验域）。
      </div>
    </div>`;
};

/* 新建账号弹窗（真实写入矩阵） */
A.newAccount = function () {
  App.modal(`
    <h2>新建账号</h2>
    <label class="f">账号名称</label><input id="na_name" style="width:100%" placeholder="例：财经快报">
    <div class="frow">
      <div><label class="f">垂类定向</label>
        <select id="na_vertical" style="width:100%">
          <option>科技数码</option><option>社会民生</option><option>泛文化娱乐</option>
          <option>汽车出行</option><option>财经商业</option><option>垂类实验</option>
        </select></div>
      <div><label class="f">角色（域）</label>
        <select id="na_role" style="width:100%">
          <option>主域</option><option>测试域A</option><option>测试域B</option><option>实验域</option>
        </select></div>
    </div>
    <div class="frow">
      <div><label class="f">日配额</label><input id="na_quota" type="number" min="1" max="20" value="6" style="width:100%"></div>
      <div><label class="f">发布窗口开始</label><input id="na_ws" type="time" value="10:00" style="width:100%"></div>
      <div><label class="f">发布窗口结束</label><input id="na_we" type="time" value="21:00" style="width:100%"></div>
    </div>
    <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:16px">
      <button class="btn ghost" onclick="A.closeModal()">取消</button>
      <button class="btn primary" onclick="A.createAccount()">创建并启用</button>
    </div>`);
};
A.createAccount = function () {
  const name = document.getElementById("na_name").value.trim();
  if (!name) { App.toast("请填写账号名称"); return; }
  const a = {
    id: uid("acc"), name,
    vertical: document.getElementById("na_vertical").value,
    role: document.getElementById("na_role").value,
    quota: Math.max(1, Math.min(20, Number(document.getElementById("na_quota").value) || 6)),
    winStart: document.getElementById("na_ws").value || "10:00",
    winEnd: document.getElementById("na_we").value || "21:00",
    status: "active", pref: "",
  };
  Store.state.accounts.push(a);
  log("acct", `新建账号「${name}」（${a.vertical} · ${a.role} · 日配额 ${a.quota}），已加入矩阵`);
  Store.save(); App.closeModal(); App.toast(`账号「${name}」已创建并启用`); App.softRefresh(true);
};

/* 编辑抽屉（域设置真实保存） */
A.openAccount = function (id) {
  const a = Q.account(id);
  if (!a) return;
  const items = Q.accountQueue(a.id);
  App.drawer(`
    <h2>${a.name}</h2>
    <div class="dsub">ACCOUNT · ${a.id} · ${a.role}</div>
    <div class="dblock"><div class="bt">域设置（保存后立即影响自动入队）</div>
      <label class="f">账号名称</label><input id="ea_name" style="width:100%" value="${a.name}">
      <label class="f">垂类定向</label>
      <select id="ea_vertical" style="width:100%">
        ${["科技数码", "社会民生", "泛文化娱乐", "汽车出行", "财经商业", "垂类实验"].map(v => `<option ${v === a.vertical ? "selected" : ""}>${v}</option>`).join("")}
      </select>
      <div class="frow">
        <div><label class="f">日配额</label><input id="ea_quota" type="number" min="1" max="20" value="${a.quota}" style="width:100%"></div>
        <div><label class="f">窗口开始</label><input id="ea_ws" type="time" value="${a.winStart}" style="width:100%"></div>
        <div><label class="f">窗口结束</label><input id="ea_we" type="time" value="${a.winEnd}" style="width:100%"></div>
      </div>
      <label class="f">内容偏好标签</label><input id="ea_pref" style="width:100%" value="${a.pref || ""}" placeholder="例：热点速递 · 新品测评">
      <button class="btn primary" style="width:100%;margin-top:14px" onclick="A.saveAccount('${a.id}')">保存设置</button>
    </div>
    <div class="dblock"><div class="bt">今日队列（${items.length}）</div>
      ${items.length === 0 ? `<p class="meta">暂无队列条目</p>` : items.map(q => {
        const p = Q.production(q.productionId);
        return p ? `<div class="kv"><span>${p.title.slice(0, 20)}…</span><span class="tag ${QUEUE_STATUS[q.status].cls}">${QUEUE_STATUS[q.status].label}</span></div>` : "";
      }).join("")}
    </div>`);
};
A.saveAccount = function (id) {
  const a = Q.account(id);
  if (!a) return;
  a.name = document.getElementById("ea_name").value.trim() || a.name;
  a.vertical = document.getElementById("ea_vertical").value;
  a.quota = Math.max(1, Math.min(20, Number(document.getElementById("ea_quota").value) || a.quota));
  a.winStart = document.getElementById("ea_ws").value || a.winStart;
  a.winEnd = document.getElementById("ea_we").value || a.winEnd;
  a.pref = document.getElementById("ea_pref").value;
  log("acct", `账号「${a.name}」域设置已更新（${a.vertical} · 配额 ${a.quota} · ${a.winStart}–${a.winEnd}）`);
  Store.save(); App.closeDrawer(); App.toast("域设置已保存，引擎即刻按新配置分配"); App.softRefresh(true);
};
A.toggleAccount = function (id) {
  const a = Q.account(id);
  if (!a) return;
  a.status = a.status === "active" ? "paused" : "active";
  log("acct", `账号「${a.name}」已${a.status === "active" ? "恢复在线，引擎恢复自动入队" : "暂停，引擎停止向其入队"}`);
  Store.save(); App.toast(`「${a.name}」已${a.status === "active" ? "恢复" : "暂停"}`); App.softRefresh(true);
};
A.delAccount = function (id) {
  const a = Q.account(id);
  if (!a || a.role !== "实验域") return;
  App.modal(`
    <h2>删除实验域账号</h2>
    <p class="meta" style="margin-bottom:14px">将删除「${a.name}」及其未发布队列条目，已发布记录保留。此操作不可撤销（演示内可重置数据恢复）。</p>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <button class="btn ghost" onclick="A.closeModal()">取消</button>
      <button class="btn danger" onclick="A.confirmDelAccount('${id}')">确认删除</button>
    </div>`);
};
A.confirmDelAccount = function (id) {
  const a = Q.account(id);
  if (!a) return;
  Store.state.queue = Store.state.queue.filter(q => !(q.accountId === id && q.status === "pending"));
  Store.state.accounts = Store.state.accounts.filter(x => x.id !== id);
  if (App.vs.queueTab === id) delete App.vs.queueTab;
  log("acct", `实验域账号「${a.name}」已删除`);
  Store.save(); App.closeModal(); App.toast(`已删除「${a.name}」`); App.softRefresh(true);
};