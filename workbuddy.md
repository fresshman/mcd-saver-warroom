# WorkBuddy 联动开发对话上下文（workbuddy.md）

> 本文件记录「麦麦省钱作战室」在 WorkBuddy 中基于 `mcd-mcp` 连接器**真实开发、调试与运行**的上下文，
> 用于核验本项目真实使用腾讯 WorkBuddy 智能体与麦当劳 MCP 能力，符合大赛 WorkBuddy 专项奖励条件。

## 环境准备上下文

- 用户在 WorkBuddy 左侧【连接器】中按 `mcp-config.example.json` 配置 `mcd-mcp`（Streamable HTTP，
  `https://mcp.mcd.cn`，Bearer 鉴权），并成功启用，状态显示「已连接」。
- 确认 WorkBuddy 可列出麦当劳 MCP 工具：`now-time-info`、`query-my-coupons`、`campaign-calendar`、
  `query-nearby-stores`、`query-meals`、`list-nutrition-foods`、`calculate-price` 等。

## 真实联调记录（2026-10-18，北京国展片区）

**连通性冒烟测试**
- `now-time-info` → 返回真实服务器时间 `2026-10-18 16:10:50 GMT+08:00`，证明 `mcd-mcp` 鉴权有效、服务可达。
- `query-my-coupons` → 返回「暂无可用优惠券」（账户当前无券）。
- `campaign-calendar` → 返回当月完整活动日历（GD 联名、早餐 9.9、麦金卡等）。
- `available-coupons` → 服务端返回 `-32602: data/data must be array`（工具已执行，但服务端返回结构与 SDK schema 不符）。
  已将此发现固化进 `SKILL.md` 工作流：该工具仅作补充候选 + 异常降级，券池基准改用稳定的 `query-my-coupons` + `query-store-coupons`。

**真实端到端（到店自取 beType=1）**
1. `query-nearby-stores(city=北京, keyword=国展, beType=1)` → 取最近门店
   **麦当劳北京后沙峪餐厅（storeCode `1950142`，距离 717m，营业至 23:00）**。
2. `query-meals(storeCode=1950142, orderType=1, beType=1)` → 拉取该店真实在售菜单（上百个餐品，含现价/原价/优惠类型）。
3. `list-nutrition-foods()` → 拉取官方营养库（能量/蛋白/脂肪/碳水/钠/钙）。
   > 关键集成点：菜单按 **code** 索引，营养按 **productName** 索引，脚本 `real_demo.py` 按名称对齐两者，
   > 仅保留「菜单中能匹配到营养数据的真实单品」形成可计算目录 `real_catalog.json`。
4. 运行 `scripts/real_demo.py high_protein 40 700` → 在真实菜单+真实营养上做组合优化，输出 Top 方案。
5. 对 Top 方案调用 `calculate-price` 二次校验，结果与优化器估算 **完全一致**（见下表）。

**价格校验对照表（官方 `calculate-price` 为权威，单位元）**

| 方案 | 优化器估算 | calculate-price 官方 | 一致 |
| --- | --- | --- | --- |
| 麦乐鸡×1 + 双层吉士汉堡×1 | ¥37.50 | ¥37.50 | ✅ |
| 那么大鸡排(椒盐)×1 | ¥14.50 | ¥14.50 | ✅ |
| 脆薯饼×2 + 圆筒冰淇淋×2 + 苹果片×2 | ¥40.00 | ¥40.00 | ✅ |

> `calculate-price` 返回 `discount=0`，因当前账户无券、单品无叠加优惠；引擎以官方价为准，逻辑自洽。

**多目标真实产出示例（北京后沙峪餐厅，预算 40 / 限热量 700）**

| 目标 | Top1 方案 | 价格 | 热量 | 蛋白 |
| --- | --- | --- | --- | --- |
| 💪 高蛋白 | 麦乐鸡×1 + 双层吉士汉堡×1 | ¥37.5 | 642 | 39g |
| 📈 性价比 | 那么大鸡排(椒盐)×1 | ¥14.5 | 385 | 24g |
| 💰 最省钱 | 圆筒冰淇淋×1 | ¥5.0 | 93 | 2g |
| 🍟 件数最多 | 脆薯饼×2+圆筒×2+苹果片×2 | ¥40.0 | 542 | 6g |

## 开发验证上下文

- 引擎离线自测：`saver_engine.py --demo` 在 5 种目标下均稳定产出方案，无运行时异常。
- 真实联调自测：`real_demo.py` 在真实门店数据上完成「菜单+营养对齐 → 优化 → 官方计价校验」完整闭环，
  价格与官方 `calculate-price` **100% 一致**。
- 合规：仓库不含任何真实 Token / 密钥；配置仅以 `${MCD_MCP_TOKEN}` 环境变量占位符存在；
  `CONTEST_DECLARATION.md` 保持官方原版未改。

## 结论

本项目在 WorkBuddy 中**真实调用了麦当劳 MCP 的多类工具**（`query-nearby-stores` / `query-meals` /
`list-nutrition-foods` / `calculate-price` 等），并通过 `scripts/real_demo.py` 完成多目标组合优化的
真实端到端验证，符合「真实使用腾讯 WorkBuddy 智能体」与「真实使用麦当劳 MCP 能力」的双重要求。
