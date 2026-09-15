/* Demo 业务逻辑冒烟测试：node demo/smoke.test.mjs
 * 用 localStorage 垫片加载 data.js + store.js，验证与后端同口径的规则评估、质检与账号分配。 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)));

// 浏览器环境垫片
globalThis.localStorage = {
  _d: {},
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};

const code = ["data.js", "store.js"].map(f => readFileSync(join(root, f), "utf8")).join("\n");
// VIEWS/A 已在 data.js 声明；在测试作用域内执行并导出需要的符号
const exports_ = new Function(`${code}
  return { Seed, Store, Q, evalRule, runQC, assignAccount, uid, nowMs };`)();
const { Store, Q, evalRule, runQC, assignAccount } = exports_;

let failed = 0;
function check(name, cond) {
  console.log((cond ? "PASS" : "FAIL") + "  " + name);
  if (!cond) failed++;
}

Store.load();
const s = Store.state;

// 规则判定与后端 format_decision.py 同口径：ev1 富视频→规则1，ev2 纯图→规则2，ev3 混编→规则3，ev4 待授权→规则4
check("ev1 高清高密度视频 → 规则1", evalRule(Q.event("ev1")).rule === "规则1");
check("ev2 无视频多图 → 规则2", evalRule(Q.event("ev2")).rule === "规则2");
check("ev3 低密度视频+多图 → 规则3", evalRule(Q.event("ev3")).rule === "规则3");
check("ev4 素材待授权 → 规则4(暂缓)", evalRule(Q.event("ev4")).rule === "规则4");

// 质检：ev1 素材全部已授权且有署名 → 无一票否决
const qc1 = runQC(Q.event("ev1"), evalRule(Q.event("ev1")));
check("ev1 质检无一票否决", qc1.vetoes.length === 0);
check("ev1 质检状态为 qualified 或 held", ["qualified", "held"].includes(qc1.status));
check("质检分在 40-97 区间", qc1.score >= 40 && qc1.score <= 97);

// 账号分配：ev1 为社会民生 → 民生一线(acc2)
const acc = assignAccount(Q.event("ev1"));
check("ev1 自动分配给「民生一线」", acc && acc.name === "民生一线");

// 暂停账号不再获得分配
const acc2 = Q.account("acc2");
acc2.status = "paused";
const accAfterPause = assignAccount(Q.event("ev1"));
check("暂停「民生一线」后不再分配给它", accAfterPause === null || accAfterPause.id !== "acc2");
acc2.status = "active";

// 配额用尽不再分配
acc2.quota = 1; // seed 中 acc2 已有 1 条待发布
check("配额用尽后不再分配", assignAccount(Q.event("ev1")) === null || assignAccount(Q.event("ev1")).id !== "acc2");

// 种子数据完整性
check("种子包含 5 个账号", s.accounts.length === 5);
check("种子包含 4 个初始事件", s.events.length === 4);
check("种子队列非空（ev1 已入队）", s.queue.length >= 1);
check("种子待授权素材可被补录", Q.assets().some(a => a.auth === "pending"));

console.log(failed === 0 ? "\n全部通过" : `\n${failed} 项失败`);
process.exit(failed === 0 ? 0 : 1);