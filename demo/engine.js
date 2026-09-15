/* ============ 自动化引擎：驱动 采集→聚类→生产→质检→入队 全流程 ============ */

const Engine = {
  timer: null,

  start() {
    this.stop();
    this.timer = setInterval(() => this.tick(), 3000);
  },
  stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } },

  toggle() {
    Store.state.sim.running = !Store.state.sim.running;
    log("sys", Store.state.sim.running ? "自动化引擎已继续运行" : "自动化引擎已暂停（演示）");
    Store.save(); App.refreshTop();
  },
  setSpeed(v) { Store.state.sim.speed = Number(v) || 1; Store.save(); },

  tick() {
    const s = Store.state;
    if (!s.sim.running) return;
    s.sim.tick++;
    const speed = s.sim.speed;

    if (Math.random() < 0.45 * speed) this.spawnSignal();
    this.clusterPass();
    if (Math.random() < 0.2 * speed) this.deferredPass();
    this.producePass();
    this.taskPass(speed);

    Store.save();
    App.softRefresh();
  },

  /* 1. 采集：从候选池取一条新信号 */
  spawnSignal() {
    const s = Store.state;
    const pool = Seed.SIGNAL_POOL.filter(p => !s.usedKw.includes(p.kw) || Math.random() < 0.25);
    if (!pool.length) return;
    const p = pool[Math.floor(Math.random() * pool.length)];
    const heat = Math.round(p.heat[0] + Math.random() * (p.heat[1] - p.heat[0]));
    const rise = "+" + Math.round(30 + Math.random() * 290) + "%";
    const match = Math.round(50 + Math.random() * 45);
    const sg = {
      id: uid("sg"), title: p.title, src: p.src, kw: p.kw, vertical: p.vertical,
      heat, rise, match, ts: nowMs(), status: "new", eventId: null, isNew: true,
    };
    s.signals.unshift(sg);
    if (s.signals.length > 40) s.signals.length = 40;
    s.stats.collected++;
    s.stats.deduped++;
    log("radar", `采集到新信号：「${p.kw}」热度 ${heat}`);
  },

  /* 2. 聚类：达标信号自动合并进已有事件或生成新事件 */
  clusterPass() {
    const s = Store.state;
    s.signals.filter(sg => sg.status === "new" && sg.heat >= s.sim.threshold).forEach(sg => {
      let ev = s.events.find(e => e.kw === sg.kw);
      if (ev) {
        ev.score = Math.max(ev.score, sg.heat);
        ev.timeline.unshift({ ts: sg.ts, title: sg.title, src: sg.src, heat: sg.heat, rise: sg.rise });
        sg.status = "aggregated"; sg.eventId = ev.id;
        log("cluster", `信号「${sg.kw}」并入已有事件，事件热度升至 ${ev.score}`);
      } else {
        ev = this.createEvent(sg);
        sg.status = "aggregated"; sg.eventId = ev.id;
        s.stats.clustered++;
        log("cluster", `信号聚类为新事件：「${ev.title.slice(0, 16)}…」（评分 ${ev.score}）`);
      }
    });
  },

  createEvent(sg) {
    const s = Store.state;
    const specKey = Seed.SPEC_KEYS[Math.floor(Math.random() * Seed.SPEC_KEYS.length)];
    const spec = Seed.ASSET_SPECS[specKey];
    const evId = uid("ev");
    const assets = spec.map((sp, j) => ({
      id: uid("as"), eventId: evId,
      name: Seed.assetName(sg.kw, sp, j),
      type: sp.t, clarity: sp.c, density: sp.d, dur: sp.dur,
      srcLevel: sp.lvl, auth: sp.auth, attribution: sp.attr,
      fingerprint: "fp_" + sg.kw + "_" + (sp.t === "image" ? (j % 2) : j),
      ingestedAt: nowMs(),
    }));
    s.assets.push(...assets);
    const ev = {
      id: evId, title: sg.title, kw: sg.kw, vertical: sg.vertical,
      score: sg.heat, match: sg.match, assetIds: assets.map(a => a.id),
      status: specKey === "thin" ? "deferred" : "ready",
      retries: 0, createdAt: nowMs(),
      timeline: [{ ts: sg.ts, title: sg.title, src: sg.src, heat: sg.heat, rise: sg.rise }],
    };
    s.events.unshift(ev);
    if (!s.usedKw.includes(sg.kw)) s.usedKw.push(sg.kw);
    if (ev.status === "deferred") log("cluster", `「${ev.kw}」无有效媒体素材，按规则4暂缓，进入素材等待队列`);
    return ev;
  },

  /* 3. 素材等待队列：暂缓事件持续尝试补素材，补到则自动就绪 */
  deferredPass() {
    const s = Store.state;
    s.events.filter(e => e.status === "deferred").forEach(ev => {
      if (ev.retries >= 3) return;
      ev.retries++;
      // 模拟补到一条已授权素材
      const isVideo = Math.random() < 0.4;
      const a = {
        id: uid("as"), eventId: ev.id,
        name: Seed.assetName(ev.kw, { t: isVideo ? "video" : "image" }, ev.retries + 2),
        type: isVideo ? "video" : "image",
        clarity: "清晰", density: isVideo ? Math.round(40 + Math.random() * 45) : null,
        dur: isVideo ? Math.round(20 + Math.random() * 40) : null,
        srcLevel: "B", auth: "cleared", attribution: "来源：合作媒体",
        fingerprint: "fp_" + ev.kw + "_r" + ev.retries, ingestedAt: nowMs(),
      };
      s.assets.push(a);
      ev.assetIds.push(a.id);
      const rule = evalRule(ev);
      if (rule.format !== "defer") {
        ev.status = "ready";
        log("media", `「${ev.kw}」第 ${ev.retries} 次重试补到素材，命中${rule.rule}，自动就绪`);
      } else {
        log("media", `「${ev.kw}」第 ${ev.retries} 次重试补到素材，但仍不足（仍命中规则4），继续等待`);
      }
    });
  },

  /* 4. 生产：就绪事件自动启动生产任务（最多并发 2 个） */
  producePass() {
    const s = Store.state;
    const running = s.tasks.filter(t => t.status === "running").length;
    if (running >= 2) return;
    const ev = s.events.find(e => e.status === "ready");
    if (!ev) return;
    ev.status = "producing";
    const rule = evalRule(ev);
    s.tasks.unshift({
      id: uid("tk"), eventId: ev.id, rule: rule.rule, format: rule.format,
      progress: 0, stage: "素材对齐", status: "running", startedAt: nowMs(),
    });
    log("build", `「${ev.kw}」命中${rule.rule}，自动启动${rule.formatName}生产`);
  },

  /* 5. 生产任务推进 → 完成即质检 → 合格自动入队 */
  taskPass(speed) {
    const s = Store.state;
    s.tasks.filter(t => t.status === "running").forEach(t => {
      t.progress = Math.min(100, t.progress + Math.round((14 + Math.random() * 16) * speed));
      t.stage = ["素材对齐", "智能粗剪", "字幕生成", "封面包装", "导出成片"][Math.min(4, Math.floor(t.progress / 22))];
      if (t.progress < 100) return;

      t.status = "done";
      const ev = Q.event(t.eventId);
      if (!ev) return;
      const rule = evalRule(ev);
      const qc = runQC(ev, rule);
      const acc = qc.status === "qualified" ? assignAccount(ev) : null;
      const prod = {
        id: uid("pd"), eventId: ev.id, accountId: acc ? acc.id : "",
        type: rule.format === "video" ? "video" : (rule.format === "slideshow" ? "slideshow" : "article"),
        typeName: productionTypeName(rule.format === "defer" ? "article" : rule.format),
        title: genTitle(ev, rule), duration: rule.format === "video" ? 58 : 0,
        rule: rule.rule, quality: qc, status: qc.status, createdAt: nowMs(), retries: 0,
      };
      s.productions.unshift(prod);
      ev.status = "produced";

      if (qc.status === "blocked") {
        log("qc", `「${ev.kw}」触发一票否决：${qc.vetoes.join("、")}，已拦截并转入待确认`);
      } else if (qc.status === "held") {
        log("qc", `「${ev.kw}」质量分 ${qc.score} < 75，留档，次日自动降级重试`);
      } else if (acc) {
        const maxOrder = Math.max(-1, ...s.queue.filter(q => q.accountId === acc.id).map(q => q.order));
        s.queue.push({ id: uid("q"), productionId: prod.id, accountId: acc.id, status: "pending", order: maxOrder + 1, createdAt: nowMs(), publishedAt: null });
        log("queue", `「${ev.kw}」质检通过（${qc.score} 分），已自动入队「${acc.name}」待发布`);
      } else {
        prod.status = "held";
        log("qc", `「${ev.kw}」质检通过但无可用账号（暂停或配额已满），留档待分配`);
      }
    });
  },

  /* 手动注入一条信号（雷达页按钮） */
  inject() { this.spawnSignal(); Store.save(); App.softRefresh(); },
};

/* 标题生成（模拟）：按形态给不同模板 */
function genTitle(ev, rule) {
  const t = ev.title.replace(/[，。].*$/, "");
  if (rule.format === "video") return `直击｜${t}`;
  if (rule.format === "slideshow") return `图集｜${t}，现场画面一览`;
  return `快讯｜${t}`;
}