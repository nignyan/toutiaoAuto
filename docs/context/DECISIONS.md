# DECISIONS — 已拍板决策

> 每条只保留一个权威来源；被取代的决策应标注取代项。追加时记录日期与依据。

## D1 内容形态判定口径（2026-09-15 MVP 评审拍板）
- 来源：产品设计文档 §5。
- 判定优先级：规则 4（无有效媒体）→ 规则 1（视频独立成片）→ 规则 3（视频+图片混编）→ 规则 2（纯图集）。
- 信息密度：0–100；≥70 高（作视频主体，规则1准入），50–69 中（辅助素材，规则3准入），<50 低。
- 视频质量不足优先退到规则 3，而非直接暂缓；仅既达不到可用下限、图片又 <2 张才落规则 4。

## D2 素材授权合规底线（2026-09-15）
- 来源：产品设计文档 §4.3、§4.5。
- 仅 `authStatus = cleared` 的素材可进入生产；C 类素材视同“无有效媒体”参与形态判定。
- 素材不足时**降级形态**，但**不得降级合规标准**。
- 授权未确认为质量分硬性一票否决项之一。

## D3 MVP 数据回流不做自动调参
- 来源：产品设计文档 §4.7、§7。
- MVP 仅输出“建议动作”，由运营人工确认；自动调参列入后续演进（单次调幅 ≤15%、观察期 7 天、一键回滚、仅对当前账号生效）。

## D4 MVP 技术选型（2026-09-15 编码启动）
- 语言/框架：Python + FastAPI；pytest + ruff。
- 存储：SQLite（单文件，MVP 落库）；pydantic BaseModel 承载领域模型。
- 代码结构：`app/models`（领域模型）、`app/pipeline`（业务管道，首个核心模块为 `format_decision.py` 形态决策）、`app/daos`（SQLite 持久化）、`app/api`（FastAPI 路由）、`tests/`。

## D5 真实头条账号接入方案（2026-09-15 用户拍板）
- 结论：头条号无个人开放的发布 API，采用 **Playwright RPA 填草稿箱**方案：自动化把内容包填进投稿草稿箱，用户手动点发布；**自动发布（auto_publish）做成账号级开关，默认关闭**。
- 架构：统一定义 `PublishAdapter` 协议（`app/publish/adapter.py`），每个账号绑定 adapter 类型与独立浏览器 profile 目录（登录态隔离）；后续若取得 MCN 资质可插 API 适配器，上层队列不感知差异。
- 风险已告知：平台风控、页面改版需维护选择器（集中在 `SELECTORS` 常量）、多账号同 IP 关联。
- 演示前端：`demo/` 纯前端 + localStorage 状态；冒烟测试 `node demo/smoke.test.mjs`。

## D6 采集数据源与触发策略（2026-09-15 用户拍板）
- 策略 A：`SignalSource` 协议（与 PublishAdapter 同构）+ FixtureSource（测试/演示）+ **微博热搜**真实适配器（`weibo.com/ajax/side/hotSearch`，免登录公开 JSON）。X 需付费、抖音热榜需抓包对抗风控，均不进 MVP。
- 触发：API 端点 `POST /pipeline/collect`；调度逻辑写成可复用函数，定时轮询留后续薄封装。
- 容错：单源失败不影响其他源，记录 SourceStatus；采集记录不落库（范围外）。

## D7 事件聚类口径（2026-09-15 用户拍板）
- 算法：标题字符 bigram 集合的 **Jaccard 相似度 ≥ 0.35**（参数可配）并入事件；零新依赖，jieba 分词与语义向量均不采用。
- 评分：MVP `Event.score` = 归一化热度 0–100（微博 num 按批次 min-max 归一，极差为 0 取 50），并入取 max；加权评分模型留后续迭代。

## D8 素材来源与密度取值边界（2026-09-15 用户拍板）
- 素材双入口：① FixtureSource 信号自带模拟素材（模拟算法已识别属性）；② `ingest_asset` 手动补录。真实源事件无素材 → 命中规则 4 → DEFERRED 素材等待队列。
- 信息密度/清晰度在**入库时落库**，值由调用方提供（fixture 模拟算法结果 / 人工标注）；未来接视觉模型只替换取值来源，数据流不变。不做启发式估算（纯文本信号估不出真实密度，假精度）。
- 架构采用方案一：pipeline 纯函数 + 瘦 DAO + API 薄封装（同步），不引入进程内事件总线。规格见 `docs/specs/2026-09-15_热点采集聚类素材入库_设计文档.md`。

## D9 内容生产引擎口径（2026-09-16 用户拍板）
- 范围：生产引擎 + 自动质检闭环（产品文档 §4.4 + §4.5）；账号自动分配与待发布队列入队留下一迭代。
- 文本生成：`ContentComposer` 协议 + `TemplateComposer` 模板实现（零外部依赖），LLM 留协议插槽；同事件多版本产出（快讯/解读版）不在本迭代。
- 触发：仅 API 手动触发（`POST /pipeline/produce` 单事件 + `/all` 批量），无自动联动、无事件总线（沿用 D8 方案一）。
- 质检：一票否决（事件来源缺失 / 素材不可用 / 授权未确认 / 署名缺失；**引用比例超限不实现**——素材无原文可比对，属假检查）+ 确定性质量分公式（≥75 `QUALIFIED`，否则 `HELD`，有否决 `BLOCKED`）。
- 事件状态机：`READY → PRODUCED` 一次性，重复生产拒绝；held/blocked 是成品质检态，「留档次日重试」属发布配额概念，归下一迭代。
- 生产时**实时复跑** `decide_format`（不读历史判定），与 asset_ingest 重评估同口径。
- 模块：`composer.py` / `quality_check.py` / `producer.py` 双模块分工，质检为独立纯函数可复用。规格见 `docs/specs/2026-09-16_内容生产引擎_设计文档.md`。

## D10 账号自动分配与待发布队列入队口径（2026-09-16 用户拍板）
- 范围：QUALIFIED 成品 → 账号分配 → 待发布队列入队（产品文档 §4.6 上半段）；队列状态流转与 RPA 填稿联动属发布执行迭代。
- 触发：仅 API 手动触发（`POST /pipeline/enqueue` 单成品 + `/all` 批量），无事件总线（沿用 D8/D9 方案一）。
- 角色域：`Account.role` = `primary`（主域）/ `test`（测试域）/ `experiment`（实验域）；**测试域不参与自动分配**（产品文档分配优先级链仅含垂类精确匹配 > 通用主域 > 实验域，测试域内容人工控制）。
- 成品垂类：`Production.vertical`（默认空=通用）；MVP 无事件垂类分类来源，精确匹配层级策略完整实现但 API 生产流中通常不触发，字段为后续垂类分类就绪。
- 配额口径：`daily_quota` = 当日入队上限；已用 = 当日（UTC 日期前缀）该账号队列条目数，跳过/失败不释放；`quota=0` 视为不参与分配。
- 队列幂等：production与队列项 1:1（`UNIQUE(production_id)` 唯一索引兜底）；重复入队单成品拒绝（409）；`enqueue_all` 预过滤已入队成品，skipped 只记录真实失败。
- 批量顺序：质量分降序（配额紧张时优质内容优先，与 `produce_all` 分数优先同构）；同层级账号按配置时间升序（先配置者优先）。
- 发布窗口 MVP 不参与分配判定，队列项 `scheduled_for` 留空；账号删除仅限实验域，且有 PENDING 队列项时拒绝。
- 规格：`docs/specs/2026-09-16_账号分配与发布队列_设计文档.md`。

## D11 素材等待队列超时归档口径（2026-09-16）
- 来源：产品设计文档 §4.4（暂缓生产与素材等待队列）；本迭代未单独建规格文档，以本条为口径权威。
- 等待起点：`Event.deferred_at` 记录进入等待队列时间（模型 validator 兜底：status=DEFERRED 且为空时自动填当前时刻，显式传入不覆盖）；存量库旧 deferred 行无该值时回退 `created_at`。
- 重试计数：「已重试 n 次」= 等待期间每次素材补录尝试（`ingest_asset` 命中 DEFERRED 事件）计 1 次，落 `deferred_retries`；转 READY 后计数冻结，仅作观察口径。
- 超时判定：`now - 等待起点` **严格大于** 24 小时（「超过 24 小时」）才归档；纯函数 `expired_deferred` 可测，编排 `archive_expired` 事务批量落库。
- 归档语义：DEFERRED → ARCHIVED 不可逆（「不再尝试」）：`ingest_asset` 只重评估 DEFERRED 事件，补录素材照常落库但不复活归档事件；produce/enqueue 只取 READY/QUALIFIED，天然不感知归档事件。
- 触发：仅 API 手动触发 `POST /pipeline/wait-queue/timeout`（幂等，重复调用无副作用），无定时器（沿用 D8/D9/D10 方案一）。

## D12 内容生产引擎复审收口（2026-09-16 grill 拍板）
- 来源：对 D9 已实现设计的复审拷问（用户逐题拍板）；本条为权威收口记录，产品文档 §4.4/§4.5 与 RISKS.md 口径同步修订。
- HELD 处置：MVP 降级为「留档 + 人工捞回」（`GET /productions?status=held`），不自动次日重试；产品文档「降级次日重试」自动化列为演进项。不破坏事件 409 / 队列 1:1 语义。
- 一次性生产：接受 READY→PRODUCED 一次性（时效优先）；素材晚到、授权补录解锁对已 PRODUCED 事件无效，为已知局限，重生产能力列演进项。
- 署名否决粒度：保持素材级从严（任一 usable 素材无 attribution → 成品 BLOCKED）；「素材级剔除」列演进项，按实际 BLOCKED 率复盘。
- 质量分语义错位：接受确定性均值公式；「形态判定看最好素材 vs 质检看平均素材」的错位记入 RISKS.md，观察期后按运营数据调权，按形态分公式列演进项。
- 演进项显式暂不做（MVP）：多版本产出（§4.4）、重复事件/相似脚本/重复镜头检测、风险标签 + 待确认队列、标题与脚本一致性检查（模板生成构造性一致，仅对 LLM 实现有意义）、LLM composer（协议已预留）；引用比例超限维持「假检查不实现」（D9）。

## D13 发布执行口径（2026-09-16 用户拍板）
- 范围：队列状态流转 + RPA 填稿联动 + 队列管理操作全量对齐产品 §4.6（预览/行内改标题/调整排序/跳过可撤销/提交发布）；规格见 `docs/specs/2026-09-16_发布执行_设计文档.md`。
- 状态机：队列 `PublishStatus` 新增 `draft_ready`（草稿箱已填，等待人工在头条后台点发布）；`pending → 派发 → draft_ready（auto_publish=False）/ published（auto_publish=True）/ failed →（重试）`；`draft_ready → 人工确认 → published`；`skipped ⇄ pending`。
- 派发守卫：仅 `pending/failed` 可派发（failed 可重试；draft_ready 拒绝避免重复草稿；skipped 需先撤销）；适配器 `NEEDS_LOGIN/FAILED` 均映射 `failed`，原因记入 `publish_result`（格式 `[适配器状态] 消息`）；适配器异常（未装 Playwright 等）容错落库不冒泡；适配器失败也是 200（结果落库）。
- 内容包：`build_package` 按图文形态只填标题/正文/标签——素材均为远程 URL、无本地媒体文件，媒体上传列演进项（需素材本地化 + 选择器校准）；`tags` 无来源留空。
- 排序：`publish_queue.sort_key`（默认 0 退化为 FIFO，向后兼容），列表按 `sort_key ASC, created_at ASC, id ASC`；PATCH 直接回写 sort_key，前端按展示序重排（如 10/20/30 留空隙）；配额核算不受影响（仍按 created_at UTC 日前缀，跳过/失败不释放）。
- 行内改标题：PATCH 队列项落到 `production.title`（队列与成品 1:1）；改标题与排序跨表同事务。
- 触发：仅 API 手动单条派发，无批量派发（RPA 每账号打开真实浏览器，需人工监督；沿用 D8/D9/D10 方案一）；派发时账号已暂停不拦截（暂停语义是「不再获得新分配」，D10）。
- 账号删除守卫由「存在 pending」扩为「存在 pending 或 draft_ready」（草稿待发布仍占用账号）。
- 审核状态/素材来源回流（产品 §4.6）属数据回流迭代（§4.7），本迭代不做。
- 工程教训：`DB.transaction()` 持有非重入 `threading.Lock`，事务内不得调用 `db.run/query`（会二次抢锁死锁），只能用 `*_with(conn)` 原生 execute——PATCH 端点曾因此死锁，预检移到事务外修复。

## D14 存草稿真机校准与 CDP 路线（2026-09-16 用户拍板）
- 根因（探针 v4 系列取证，证据存档 `.scratch/selector-calibration/`）：存草稿失败不是选择器问题——图文页保存 API `POST /mp/agw/article/publish` 在 launch_persistent_context 的 Chromium 自动化指纹下恒返回 `err_no=7050 保存失败`（fill 自动填 7050、人工手输 7050 ×4、348 字长文 7050，草稿箱始终为空）；同一内容经 CDP 连接用户真实 Chrome 实测 `err_no=0` 保存成功且草稿箱可见（探针 v5，pgc_id 落库）。
- 拍板：走「CDP 路线 A」——适配器 `connect_over_cdp` 接管用户真实 Chrome（`--remote-debugging-port=9222` + 专用 user-data-dir，Chrome 136+ 禁止默认 profile 开调试端口）；profile 模式（launch_persistent_context）降级为遗留兜底，不再用于存草稿主链路。
- CDP 语义：优先复用已打开的头条标签页，退出仅关闭本进程新建的标签页；`browser.close()` 仅断开 CDP 连接、不杀用户浏览器进程；进入页面统一 `goto` 头条首页（未登录 302 到 /auth/** 作登录检测信号）。
- 配置接线：构造器 `cdp_endpoint`；CLI `--cdp-endpoint`（留空回读环境变量 `TOUTIAO_CDP_ENDPOINT`）；API 工厂 `get_adapter` 同样回读该环境变量；两种测试注入（`browser_factory`/`cdp_browser_factory`）互不影响。
- 图文选择器 5 键已真机校准（登录入口按钮 / 图文发布页 URL / 标题 textarea / 正文 .ProseMirror / 「预览并发布」消歧），集中在 `SELECTORS`；视频链路、tag、存草稿按钮仍为占位（MVP 出界）。
- 遗留清理：探针草稿（校准探测 v4/v4c/v4d/v5 等）需人工在头条草稿箱删除；探针脚本 `scripts/calibrate_*.py` 为一次性工具，用后可删。