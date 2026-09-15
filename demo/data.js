/* ============ 种子数据：所有数据均为模拟，但结构对齐产品设计文档 ============ */

/* 全局容器需先于各视图脚本声明（视图脚本加载时即向 A/VIEWS 挂方法） */
var VIEWS = {};
var A = {};

const Seed = (() => {

  // 候选热点池：引擎自动采集时随机取用
  const SIGNAL_POOL = [
    { title: "国产AI芯片宣布量产，性能对标国际旗舰", src: "垂直信息源", kw: "AI芯片", vertical: "科技数码", heat: [70, 95] },
    { title: "某新能源车企发布新车型，续航突破1000公里", src: "垂直信息源", kw: "新能源车", vertical: "汽车出行", heat: [68, 92] },
    { title: "高校食堂新菜走红，学生排队一小时打卡", src: "抖音热榜", kw: "高校食堂", vertical: "社会民生", heat: [60, 88] },
    { title: "千万粉丝博主带货翻车，涉嫌虚假宣传被立案", src: "X/抖音热榜", kw: "带货翻车", vertical: "社会民生", heat: [75, 96] },
    { title: "多地发布高温红色预警，部分景区临时闭园", src: "新闻/RSS", kw: "极端高温", vertical: "社会民生", heat: [65, 90] },
    { title: "小众非遗技艺走红短视频，年轻人争相体验", src: "抖音热榜", kw: "非遗", vertical: "泛文化娱乐", heat: [55, 85] },
    { title: "城市马拉松开跑，业余选手打破赛会纪录", src: "新闻/RSS", kw: "马拉松", vertical: "社会民生", heat: [50, 80] },
    { title: "头部手机厂商官宣自研系统新版本发布", src: "垂直信息源", kw: "手机系统", vertical: "科技数码", heat: [62, 90] },
    { title: "网红城市夜市爆火，凌晨仍排队", src: "抖音热榜", kw: "夜市", vertical: "泛文化娱乐", heat: [58, 86] },
    { title: "新修订行业标准发布，涉及新能源电池安全", src: "新闻/RSS", kw: "电池安全", vertical: "汽车出行", heat: [55, 82] },
    { title: "国产大模型开源新版本，开发者社区热议", src: "X/垂直信息源", kw: "大模型", vertical: "科技数码", heat: [66, 94] },
    { title: "某地开通跨省地铁，通勤时间缩短一半", src: "新闻/RSS", kw: "跨省地铁", vertical: "社会民生", heat: [60, 84] },
    { title: "老电影修复版重映，票房逆跌", src: "抖音热榜", kw: "电影重映", vertical: "泛文化娱乐", heat: [50, 78] },
    { title: "无人机配送试点扩容至多城", src: "垂直信息源", kw: "无人机配送", vertical: "科技数码", heat: [57, 85] },
    { title: "新款混动车型油耗实测引争议", src: "X/抖音热榜", kw: "混动车", vertical: "汽车出行", heat: [60, 88] },
    { title: "高校毕业生进社区食堂创业引关注", src: "新闻/RSS", kw: "高校食堂", vertical: "社会民生", heat: [52, 76] },
  ];

  // 事件对应的素材生成模板（决定形态判定走向）
  const ASSET_SPECS = {
    rich_video: [ // 规则1：高清高密度视频
      { t: "video", c: "超清", d: 84, lvl: "A", auth: "cleared", dur: 58, attr: "来源：官方发布" },
      { t: "video", c: "清晰", d: 77, lvl: "A", auth: "cleared", dur: 43, attr: "来源：官方发布" },
      { t: "image", c: "清晰", d: null, lvl: "B", auth: "cleared", dur: null, attr: "来源：新闻图库" },
    ],
    mixed: [ // 规则3：视频质量不足 + 多图
      { t: "video", c: "清晰", d: 56, lvl: "B", auth: "cleared", dur: 31, attr: "来源：合作媒体" },
      { t: "image", c: "清晰", d: null, lvl: "B", auth: "cleared", dur: null, attr: "来源：合作媒体" },
      { t: "image", c: "清晰", d: null, lvl: "A", auth: "cleared", dur: null, attr: "来源：官方发布" },
    ],
    images: [ // 规则2：纯图集
      { t: "image", c: "清晰", d: null, lvl: "B", auth: "cleared", dur: null, attr: "来源：新闻图库" },
      { t: "image", c: "清晰", d: null, lvl: "B", auth: "cleared", dur: null, attr: "来源：新闻图库" },
      { t: "image", c: "一般", d: null, lvl: "A", auth: "cleared", dur: null, attr: "来源：官方发布" },
    ],
    thin: [ // 规则4：媒体不足 → 暂缓（授权待确认，可补录解锁）
      { t: "image", c: "一般", d: null, lvl: "B", auth: "pending", dur: null, attr: "" },
      { t: "text", c: null, d: null, lvl: "A", auth: "cleared", dur: null, attr: "来源：公开报道" },
    ],
  };
  const SPEC_KEYS = ["rich_video", "mixed", "images", "thin", "rich_video", "images"];

  const ACCOUNTS = [
    { name: "蓝鲸视野", vertical: "科技数码", role: "主域", quota: 8, winStart: "12:00", winEnd: "22:30", status: "active", pref: "热点速递 · 新品测评" },
    { name: "民生一线", vertical: "社会民生", role: "主域", quota: 8, winStart: "08:00", winEnd: "20:00", status: "active", pref: "突发 · 本地生活" },
    { name: "潮玩研究所", vertical: "泛文化娱乐", role: "测试域A", quota: 6, winStart: "14:00", winEnd: "23:00", status: "active", pref: "年轻人向 · 轻解读" },
    { name: "出行未来", vertical: "汽车出行", role: "测试域B", quota: 6, winStart: "11:30", winEnd: "21:00", status: "active", pref: "新车 · 实测" },
    { name: "HotTest-01", vertical: "垂类实验", role: "实验域", quota: 4, winStart: "10:00", winEnd: "22:00", status: "paused", pref: "形态实验专用" },
  ];

  const SUGGESTIONS = [
    { type: "标题模板", text: "「突发#直击」类标题模板近 7 天完播率高于均值 18%，建议沿用并提高权重。", impact: "完播 +18%" },
    { type: "发布时段", text: "图集视频在 12:00–14:00 时段表现更好，建议将「潮玩研究所」发布窗口前移至午间。", impact: "播放 +9%" },
    { type: "选题权重", text: "「高校食堂」类热点在科技垂类匹配度连续 3 天走低（88→64），建议下调该类选题权重。", impact: "匹配 +6%" },
    { type: "形态配比", text: "本周竖版视频占比 78%，图文类低于保底 2 条/日，建议提高图文类事件优先级。", impact: "结构均衡" },
  ];

  // 初始已聚合的事件（让首次打开就有内容可看）
  const INIT_EVENTS = [
    {
      title: "某地突发山火，救援力量连夜展开扑救", kw: "山火", vertical: "社会民生",
      score: 96, match: 92, spec: "rich_video",
      signals: [{ title: "某地突发山火，救援力量连夜展开扑救", src: "新闻/RSS", heat: 96, rise: "+320%" }],
    },
    {
      title: "千万粉丝博主带货翻车，涉嫌虚假宣传", kw: "带货翻车", vertical: "社会民生",
      score: 91, match: 74, spec: "images",
      signals: [{ title: "千万粉丝博主带货翻车，涉嫌虚假宣传", src: "X/抖音热榜", heat: 91, rise: "+180%" }],
    },
    {
      title: "某新能源车企发布新车型，续航突破1000公里", kw: "新能源车", vertical: "汽车出行",
      score: 84, match: 90, spec: "mixed",
      signals: [{ title: "某新能源车企发布新车型，续航突破1000公里", src: "垂直信息源", heat: 84, rise: "+64%" }],
    },
    {
      title: "小众非遗技艺走红短视频，年轻人争相打卡", kw: "非遗", vertical: "泛文化娱乐",
      score: 79, match: 70, spec: "thin",
      signals: [{ title: "小众非遗技艺走红短视频，年轻人争相打卡", src: "抖音热榜", heat: 79, rise: "+38%" }],
    },
  ];

  function build() {
    const now = Date.now();
    const s = {
      sim: { running: true, speed: 1, tick: 0, threshold: 55 },
      stats: { collected: 249, deduped: 207, clustered: 42, published: 0 },
      signals: [],
      events: [],
      assets: [],
      tasks: [],
      productions: [],
      queue: [],
      accounts: ACCOUNTS.map((a, i) => ({ id: "acc" + (i + 1), ...a })),
      suggestions: SUGGESTIONS.map((g, i) => ({ id: "sug" + (i + 1), status: "pending", ...g })),
      log: [],
      usedKw: ["山火", "带货翻车", "新能源车", "非遗"],
    };

    // 初始事件 + 素材
    INIT_EVENTS.forEach((e, i) => {
      const evId = "ev" + (i + 1);
      const created = now - (i + 1) * 9 * 60000;
      const assets = ASSET_SPECS[e.spec].map((sp, j) => ({
        id: "as" + evId + "_" + j,
        eventId: evId,
        name: assetName(e.kw, sp, j),
        type: sp.t, clarity: sp.c, density: sp.d, dur: sp.dur,
        srcLevel: sp.lvl, auth: sp.auth, attribution: sp.attr,
        fingerprint: "fp_" + e.kw + "_" + (sp.t === "image" ? (j % 2) : j),
        ingestedAt: created + j * 40000,
      }));
      s.assets.push(...assets);
      const deferred = e.spec === "thin";
      s.events.push({
        id: evId, title: e.title, kw: e.kw, vertical: e.vertical,
        score: e.score, match: e.match, assetIds: assets.map(a => a.id),
        status: deferred ? "deferred" : "ready",
        retries: deferred ? 1 : 0,
        createdAt: created,
        timeline: e.signals.map((g, k) => ({ ts: created - (k + 1) * 5 * 60000, title: g.title, src: g.src, heat: g.heat, rise: g.rise })),
      });
      // 已聚合信号进雷达列表
      e.signals.forEach((g, k) => {
        s.signals.push({
          id: "sg" + evId + "_" + k, title: g.title, src: g.src, kw: e.kw, vertical: e.vertical,
          heat: g.heat, rise: g.rise, match: e.match, ts: created - k * 5 * 60000,
          status: "aggregated", eventId: evId,
        });
      });
    });

    // 一条已完成生产的成品 + 入队（演示队列不为空）
    const prodId = "pd_seed1";
    s.productions.push({
      id: prodId, eventId: "ev1", accountId: "acc2",
      type: "video", typeName: "30–60s 竖版视频",
      title: "突发山火：救援力量连夜扑救现场直击",
      duration: 58, rule: "规则1",
      quality: { score: 86, checks: qcChecks(true), vetoes: [] },
      status: "qualified", createdAt: now - 20 * 60000,
    });
    s.queue.push({
      id: "q_seed1", productionId: prodId, accountId: "acc2",
      status: "pending", order: 0, createdAt: now - 19 * 60000, publishedAt: null,
    });

    s.log.push(
      { ts: now - 19 * 60000, kind: "queue", text: "「突发山火」成片质检通过（86 分），已自动入队「民生一线」" },
      { ts: now - 21 * 60000, kind: "qc", text: "「突发山火」完成自动质检：一票否决项全通过" },
      { ts: now - 24 * 60000, kind: "build", text: "「突发山火」命中规则1，自动启动竖版视频生产" },
      { ts: now - 30 * 60000, kind: "cluster", text: "4 条信号聚类为事件，进入选题池" },
      { ts: now - 31 * 60000, kind: "radar", text: "多源采集器启动：新闻/RSS · X · 抖音热榜 · 垂直信息源" },
    );
    return s;
  }

  function assetName(kw, sp, j) {
    const ext = { video: ".mp4", image: ".jpg", text: ".txt" }[sp.t];
    const label = { video: "现场片段", image: "现场图", text: "文字摘要" }[sp.t];
    return `${kw}·${label}${String(j + 1).padStart(2, "0")}${ext}`;
  }

  function qcChecks(allPass) {
    return [
      { name: "事件来源完整", pass: allPass },
      { name: "素材可用", pass: allPass },
      { name: "授权已确认", pass: allPass },
      { name: "引用比例合规", pass: allPass },
      { name: "署名齐全", pass: allPass },
    ];
  }

  return { build, SIGNAL_POOL, ASSET_SPECS, SPEC_KEYS, assetName, qcChecks };
})();