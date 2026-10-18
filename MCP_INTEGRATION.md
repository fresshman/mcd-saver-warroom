# MCP 集成说明 (MCP Integration)

本文件说明参赛项目「麦麦省钱作战室」实际使用的麦当劳中国 MCP Server、调用的 Tool、调用流程与业务价值。

## 1. 接入的 MCP Server

| 项 | 值 |
| --- | --- |
| 服务提供方 | 麦当劳中国（金拱门） |
| 开放平台 | https://open.mcd.cn/mcp |
| Server 地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP |
| 鉴权方式 | 请求头 `Authorization: Bearer <MCP_TOKEN>` |
| 速率限制 | 每 Token 600 次/分钟（超出返回 429） |
| 配置文件示例 | `mcp-config.example.json`（仅含环境变量占位符） |

> 在 WorkBuddy 中以「自定义连接器 → 配置 MCP」方式接入，连接器名为 `mcd-mcp`。

## 2. 实际调用的 Tool 清单

| Tool 名称 | 调用阶段 | 用途 | 关键参数 |
| --- | --- | --- | --- |
| `auto-bind-coupons` | 收集券池 | 一键领取麦麦省当前所有可用券 | 无（自动领取全部） |
| `query-my-coupons` | 收集券池 | 查询账户已持有的全部优惠券 | 无 |
| `query-store-coupons` | 收集券池 | 查询当前门店可用优惠券列表 | storeId |
| `available-coupons` | 收集券池 | 查询当前可领取的麦麦省券列表 | 无 |
| `query-meals` | 收集菜单 | 获取当前门店可售餐品（编码/价格/标签） | storeId |
| `list-nutrition-foods` | 收集营养 | 获取餐品营养（能量/蛋白/脂肪/钠等） | 无 |
| `query-meal-detail` | 收集营养 | 补全套餐组成与可替换项 | mealCode |
| `calculate-price` | 价格校验 | 给定商品+券计算应付（权威价格） | items, coupons |
| `create-order` | 执行下单 | （可选）按方案创建订单并返回支付链接 | storeId, items, diningType |

> 说明：`create-order` 为可选执行环节，默认仅给出「领券 + 下单」路径，由用户在官方渠道确认，
> 避免代客下单风险；如需端到端，可在用户显式授权后调用。

## 2.1 真实联调发现的工具行为差异（2026-10-18 实测）

| Tool | 实测结果 | 处理策略 |
| --- | --- | --- |
| `now-time-info` | ✅ 正常，返回服务器时间 | 直接使用 |
| `query-my-coupons` | ✅ 正常（当前账户无券） | 券池基准来源之一 |
| `campaign-calendar` | ✅ 正常，返回当月活动 | 活动播报使用 |
| `query-nearby-stores` | ✅ 正常，返回门店列表含 storeCode | 到店场景入口 |
| `query-meals` | ✅ 正常，返回菜单（code/现价/原价/优惠类型） | 菜单主源 |
| `list-nutrition-foods` | ✅ 正常，返回营养（按 productName 索引） | 营养主源 |
| `calculate-price` | ✅ 正常，返回权威价格（单位：分） | 价格校验权威 |
| `available-coupons` | ⚠️ 服务端 `-32602: data/data must be array` | **仅作补充候选 + 异常降级**，券池基准改用 `query-my-coupons` + `query-store-coupons` |

> `available-coupons` 的报错为麦当劳服务端返回结构与 SDK schema 不一致所致（工具已执行，非鉴权问题），
> 已在 `SKILL.md` 工作流中加固降级逻辑，确保运行时即便该工具异常也不会卡死。

## 2.2 跨源数据对齐说明

- `query-meals` 返回菜单以**商品 code** 为索引（含 `currentPrice` / `originalPrice` / `discountType`）；
- `list-nutrition-foods` 返回营养以**商品名称（productName）**为索引（能量/蛋白/脂肪/碳水/钠/钙）；
- 两者 schema 不同，需在集成层按名称做对齐。本项目 `scripts/real_demo.py` 采用「名称子串匹配」
  将真实菜单与真实营养对齐，仅保留可计算营养的单品，形成 `real_catalog.json` 后再做优化。
- `calculate-price` 的返回价格单位为**分**，展示时需除以 100 转为元——已在脚本与展示层统一处理。

## 3. 调用流程

```
[1] 收集券池
    auto-bind-coupons → query-my-coupons → query-store-coupons → available-coupons
                         │
[2] 收集菜单与营养        ▼
    query-meals → list-nutrition-foods → (query-meal-detail 补全)
                         │
[3] 运行引擎              ▼
    scripts/saver_engine.py --input data.json --goal <模式> --budget <预算>
    枚举候选篮 → 应用最优券 → 约束过滤 → 帕累托排序
                         │
[4] 价格校验              ▼
    calculate-price(Top 方案)  →  用官方实付覆盖本地估算
                         │
[5] 呈现 + 路径           ▼
    方案卡 + 一键领券/下单路径
```

## 4. 业务价值

- **对用户**：把分散在多个入口的券、菜单、营养信息聚合为一句话决策，显著降低「怎么点最划算」
  的决策成本，并在减脂/增肌等营养约束场景下给出可执行方案。
- **对麦当劳生态**：提升优惠券核销率（自动领券 + 最优组合）、促进到店/外送转化、增强用户粘性。
- **对开发者/赛事**：展示了 MCP「真实串联多工具完成一个完整决策闭环」的能力，而非单工具演示，
  符合大赛对「真实使用麦当劳 MCP 能力」的要求。
