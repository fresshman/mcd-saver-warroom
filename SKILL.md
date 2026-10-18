---
name: mcd-saver-warroom
description: |
  麦麦省钱作战室 —— 基于麦当劳中国 MCP 的多目标最优解点餐引擎。给定「预算 + 营养目标 + 偏好」，
  自动拉取可领/可用优惠券、当前门店菜单与餐品营养，调用优化引擎枚举组合、应用最优券、过滤约束，
  输出帕累托最优的省钱方案（最省钱 / 性价比最高 / 高蛋白限热量 / 件数最多 / 均衡），并用
  calculate-price 二次校验实付，给出一键领券下单路径。Use when the user wants the cheapest or
  best-value McDonald's order, budget meal planning, coupon stacking optimization, high-protein or
  diet-friendly McDonald's combos, or "怎么点最划算 / 麦麦省钱 / 优惠券怎么用最省 / 减脂期麦当劳 /
  预算内吃最好 / 麦当劳性价比". Triggers: 省钱/最划算/怎么点便宜/麦麦省钱/优惠券/最便宜/性价比/
  高蛋白/减脂期/预算点餐/麦当劳搭配/最优组合, cheapest/best-value/saver/coupon-stacking/budget-meal/
  mcd-mcp.
license: MIT
metadata:
  author: User
  version: "1.0.0"
---

# 麦麦省钱作战室 (McSaver War Room)

基于**麦当劳中国 MCP (`mcd-mcp`)** 的多目标最优解点餐引擎。它不只是「列出优惠券」，而是把
**真实菜单 + 真实优惠券 + 真实营养数据** 喂给一个组合优化引擎，在预算与营养约束下求解
**帕累托最优**的点餐方案，并用麦当劳官方的 `calculate-price` 工具对 Top 方案做价格校验，
最终给出可执行的「领券 + 下单」路径。

## Prerequisites

- **麦当劳 MCP Token**：在 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) 申请，配置到 WorkBuddy 的
  `mcd-mcp` 自定义连接器（参见 `mcp-config.example.json`）。
- **WorkBuddy**：官方合作伙伴客户端，用于加载本 Skill 并连接 `mcd-mcp` 连接器。
- **Python**：运行优化引擎 `scripts/saver_engine.py`（3.11+，纯标准库，无需第三方依赖）。

## Architecture

```
用户目标(预算/营养/偏好)
   │
   ▼
WorkBuddy + mcd-mcp 连接器
   ├─ available-coupons / auto-bind-coupons / query-my-coupons / query-store-coupons  → 券池
   ├─ query-meals                                                            → 门店菜单
   └─ list-nutrition-foods / query-meal-detail                              → 营养数据
   │
   ▼
scripts/saver_engine.py  ── 枚举候选篮 → 应用最优券 → 约束过滤 → 帕累托排序
   │
   ▼
calculate-price (MCP)   ── 对 Top 方案二次校验实付
   │
   ▼
呈现 方案卡 + 一键领券/下单路径
```

## Workflow（麦当劳 MCP 真实调用流程）

> 以下工具均为 `mcd-mcp` 连接器提供的真实工具，须在 WorkBuddy 中已启用该连接器后调用。

1. **收集优惠券池**
   - `query-my-coupons`：查询账户下已持有的全部优惠券（**首选，稳定可用**）。
   - `query-store-coupons`：查询当前门店可用的优惠券列表（**首选，稳定可用**）。
   - `auto-bind-coupons`：一键领取麦麦省当前所有可用券（无需指定 couponId）。
   - `available-coupons`：查询当前可领取的麦麦省券列表（**补充候选**）。
   - **健壮性说明**：`available-coupons` 实测存在服务端输出 schema 校验错误
     （`MCP error -32602: data/data must be array`，属麦当劳服务端问题，非配置问题）。
     调用时应对该工具做 try/catch，失败则跳过，并以 `query-my-coupons` + `query-store-coupons`
     的结果作为券池基准，保证流程不中断。
   - 汇总为券池（含满减/折扣/指定商品减等类型）。

2. **收集菜单与营养**
   - `query-meals`：获取当前门店可售餐品（编码、价格、标签、分类）。
   - `list-nutrition-foods`：获取餐品营养（能量、蛋白质、脂肪、碳水、钠等）。
   - 必要时 `query-meal-detail` 补全套餐组成与可替换项。

3. **运行优化引擎**
   - 将菜单 + 券池 + 用户目标写入临时 JSON，调用：
     `python scripts/saver_engine.py --input <data.json> --goal <模式> --budget <预算>`
   - 目标模式：`cheapest`(最省钱) / `best_value`(性价比最高) / `high_protein`(高蛋白限热量) /
     `max_items`(件数最多) / `balanced`(均衡帕累托)。

4. **价格校验**
   - 对引擎输出的 Top 方案，调用 `calculate-price`（传入商品列表 + 适用券），用官方结果覆盖
     引擎的本地估算，确保实付金额与麦当劳一致。

5. **呈现与可执行路径**
   - 输出每张方案卡：商品清单、原价、优惠、实付、热量/蛋白、用券明细。
   - 给出「领券 → 下单」路径：用 `create-order`（如需直接下单）或提示用户前往麦麦省领券后下单。

## Usage

在 WorkBuddy 对话框中直接表达目标即可触发，例如：

| 用户说法 | 引擎目标 | 说明 |
| --- | --- | --- |
| “预算 30 怎么点最划算” | `cheapest` | 预算内实付最低 |
| “40 块吃到蛋白质最高，热量别超 700” | `high_protein` + `--max-cal 700` | 减脂/增肌场景 |
| “给我搭个性价比最高的组合” | `best_value` | 每元营养最高 |
| “20 块解个馋，件数越多越好” | `max_items` | 件数最大化 |
| “预算 50，给我几个均衡方案” | `balanced` | 价格×营养帕累托前沿 |

也可离线验证引擎（无需 Token）：

```
python scripts/saver_engine.py --demo --goal high_protein --budget 40 --max-cal 700
```

## Output

| 产物 | 说明 |
| --- | --- |
| 方案卡（对话内） | 每套方案的清单/原价/优惠/实付/营养/用券 |
| `plan_result.json` | 引擎输出的结构化结果，供 `calculate-price` 校验与下单使用 |

## Why It Wins（差异化）

- **真实多用 MCP**：覆盖券、菜单、营养、`calculate-price` 四类共 8+ 工具，非摆设式调用。
- **真的在做优化**：组合枚举 + 券叠加 + 多目标帕累托，而非「把券列出来」。
- **价格权威**：以官方 `calculate-price` 为最终校验，结果可信。
- **可分享**：方案卡天然适合截图传播，利于 Star 增长。

## Scope

本 Skill 不存储任何真实 Token / 密钥；配置仅以环境变量占位符存在。所有下单行为需用户在
麦当劳官方渠道确认，本 Skill 仅提供参考方案，不构成营养或医疗建议。
