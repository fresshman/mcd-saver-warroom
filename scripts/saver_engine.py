#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦省钱作战室 —— 多目标最优解引擎 (saver_engine.py)

核心能力：
    给定「菜单(价格/营养/标签) + 优惠券规则 + 用户目标(预算/营养/偏好)」，
    枚举候选餐篮 -> 应用最优优惠券组合 -> 过滤约束 -> 输出帕累托最优方案。

与单纯「列券」类 Skill 的差异：
    本引擎做真实的多目标组合优化，目标模式包括：
      - cheapest      最省钱（预算内最低实付）
      - best_value    性价比最高（每元营养最高）
      - high_protein  高蛋白（限热量内蛋白最大化）
      - max_items     解馋（预算内件数最多）
      - balanced      均衡（价格与营养双优，帕累托前沿）

价格权威说明：
    引擎内置轻量计价模型用于大规模枚举；最终 Top 方案应由 WorkBuddy
    通过麦当劳 MCP 的 `calculate-price` 工具二次校验（见 SKILL.md 工作流）。

用法：
    python saver_engine.py --demo                 # 用内嵌样例离线演示
    python saver_engine.py --input data.json      # 用指定 JSON 求解
    python saver_engine.py --goal high_protein --budget 40

输入 JSON 结构见文件底部 DEMO_DATA，或运行 --dump-sample 导出样例。
"""

import argparse
import json
import random
import sys
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Item:
    code: str
    name: str
    price: float
    calories: float = 0.0
    protein: float = 0.0
    tags: List[str] = field(default_factory=list)
    category: str = "other"


@dataclass
class Coupon:
    cid: str
    name: str
    # 类型: fixed=满threshold减value; percent=打折(0.8即8折), 可带max_discount上限;
    #       item_fixed=指定商品减value(仅对applies_to内商品生效)
    ctype: str
    threshold: float = 0.0
    value: float = 0.0
    max_discount: float = 9999.0
    applies_to: List[str] = field(default_factory=list)  # 空=全场通用
    min_spend: float = 0.0


@dataclass
class Plan:
    items: List[Item]  # 已含数量(重复即多件)
    subtotal: float
    discount: float
    payable: float
    coupons_used: List[str]
    calories: float
    protein: float
    count: int

    def score_value(self) -> float:
        """每元营养（蛋白+热量/20），用于性价比排序。"""
        if self.payable <= 0:
            return 0.0
        return (self.protein * 1.0 + self.calories / 20.0) / self.payable


# --------------------------------------------------------------------------- #
# 优惠券应用
# --------------------------------------------------------------------------- #
def best_coupon_combo(items: List[Item], coupons: List[Coupon]) -> (float, List[str]):
    """对给定餐篮贪心选择最优优惠券组合，返回 (优惠金额, 使用券id列表)。"""
    subtotal = sum(i.price for i in items)
    # 候选券：满足最低消费且(全场券或含篮中商品)
    usable = [c for c in coupons if subtotal >= c.min_spend and _applies_any(c, items)]
    savings = {}
    for c in usable:
        savings[c.cid] = _coupon_saving(c, items, subtotal)
    # 按节省额降序，贪心叠加（fixed/percent 通常互斥于同一笔，这里取单券最优 + 一件折扣券）
    ranked = sorted(savings.items(), key=lambda x: x[1], reverse=True)
    best_single = ranked[0] if ranked else (None, 0.0)
    # 额外尝试「一件折扣券」叠加（适用于指定商品减）
    item_coupons = [c for c in usable if c.ctype == "item_fixed"]
    extra = 0.0
    used_extra = []
    for c in sorted(item_coupons, key=lambda c: _coupon_saving(c, items, subtotal), reverse=True):
        s = _coupon_saving(c, items, subtotal)
        if s > 0:
            extra += s
            used_extra.append(c.cid)
    total_save = best_single[1] + extra
    used = ([best_single[0]] if best_single[0] else []) + used_extra
    return min(total_save, subtotal), [u for u in used if u]


def _applies_any(c: Coupon, items: List[Item]) -> bool:
    if not c.applies_to:
        return True
    return any(i.code in c.applies_to for i in items)


def _coupon_saving(c: Coupon, items: List[Item], subtotal: float) -> float:
    if c.ctype == "fixed":
        return c.value if subtotal >= c.threshold else 0.0
    if c.ctype == "percent":
        return min(subtotal * (1 - c.value), c.max_discount)
    if c.ctype == "item_fixed":
        # 仅对适用商品生效，取篮中该商品单价折减（每件最多减 value）
        save = 0.0
        for i in items:
            if i.code in c.applies_to:
                save += min(i.price, c.value)
        return save
    return 0.0


# --------------------------------------------------------------------------- #
# 候选餐篮生成
# --------------------------------------------------------------------------- #
def generate_candidates(menu: List[Item], goal: str, rng: random.Random) -> List[List[Item]]:
    """多策略生成候选餐篮，保证多样性以便后续帕累托筛选。"""
    cands: List[List[Item]] = []
    n = len(menu)

    def add(basket):
        if 1 <= len(basket) <= 5:
            cands.append(basket)

    # 1) 单品 / 双人 / 三人直选（全部组合小集合）
    for i in range(n):
        add([menu[i]])
        for j in range(i, n):
            add([menu[i], menu[j]])
            for k in range(j, n):
                add([menu[i], menu[j], menu[k]])

    # 2) 目标导向贪心
    if goal == "high_protein":
        ordered = sorted(menu, key=lambda x: (x.protein / max(x.price, 1)), reverse=True)
    elif goal in ("cheapest", "max_items"):
        ordered = sorted(menu, key=lambda x: x.price)
    elif goal == "best_value":
        ordered = sorted(menu, key=lambda x: (x.protein + x.calories / 20) / max(x.price, 1), reverse=True)
    else:  # balanced
        ordered = sorted(menu, key=lambda x: x.price)
    add(ordered[:3])
    add(ordered[:4] + [ordered[-1]])

    # 3) 随机采样（带偏好扰动，扩大搜索面）
    for _ in range(400):
        size = rng.randint(2, 4)
        basket = [menu[rng.randrange(n)] for _ in range(size)]
        add(basket)
    return cands


# --------------------------------------------------------------------------- #
# 约束与评分
# --------------------------------------------------------------------------- #
def feasible(plan: Plan, budget: float, max_cal: Optional[float],
             min_protein: float, exclude: List[str], require_tags: List[str]) -> bool:
    if plan.payable > budget + 1e-6:
        return False
    if max_cal is not None and plan.calories > max_cal + 1e-6:
        return False
    if plan.protein < min_protein - 1e-6:
        return False
    if any(tag in exclude for it in plan.items for tag in it.tags):
        return False
    if require_tags:
        have = {t for it in plan.items for t in it.tags}
        if not all(rt in have for rt in require_tags):
            return False
    return True


def pareto_front(plans: List[Plan]) -> List[Plan]:
    """保留非支配解：不被其它解在(更低实付, 更高营养)上同时超越。"""
    front = []
    for p in plans:
        dominated = False
        for q in plans:
            if q is p:
                continue
            if (q.payable <= p.payable and q.protein >= p.protein and q.calories >= p.calories
                    and (q.payable < p.payable or q.protein > p.protein or q.calories > p.calories)):
                dominated = True
                break
        if not dominated:
            front.append(p)
    # 按实付升序、营养降序
    front.sort(key=lambda x: (x.payable, -x.protein))
    return front


# --------------------------------------------------------------------------- #
# 主求解
# --------------------------------------------------------------------------- #
def solve(menu: List[Item], coupons: List[Coupon], args) -> List[Plan]:
    rng = random.Random(42)
    budget = args.budget
    max_cal = args.max_cal
    min_protein = args.min_protein
    exclude = set(args.exclude or [])
    require_tags = args.require or []

    candidates = generate_candidates(menu, args.goal, rng)
    plans: List[Plan] = []
    for basket in candidates:
        subtotal = sum(i.price for i in basket)
        discount, used = best_coupon_combo(basket, coupons)
        payable = round(subtotal - discount, 2)
        plan = Plan(
            items=basket,
            subtotal=round(subtotal, 2),
            discount=round(discount, 2),
            payable=payable,
            coupons_used=used,
            calories=round(sum(i.calories for i in basket), 1),
            protein=round(sum(i.protein for i in basket), 1),
            count=len(basket),
        )
        if feasible(plan, budget, max_cal, min_protein, exclude, require_tags):
            plans.append(plan)

    if not plans:
        return []

    # 按目标排序取 Top-K，再补帕累托前沿
    if args.goal == "cheapest":
        plans.sort(key=lambda p: (p.payable, -p.protein))
    elif args.goal == "best_value":
        plans.sort(key=lambda p: -p.score_value())
    elif args.goal == "high_protein":
        plans.sort(key=lambda p: (-p.protein, p.payable))
    elif args.goal == "max_items":
        plans.sort(key=lambda p: (-p.count, p.payable))
    else:
        plans = pareto_front(plans)
        return plans[: args.top_k]

    return plans[: args.top_k]


# --------------------------------------------------------------------------- #
# 展示
# --------------------------------------------------------------------------- #
def render(plans: List[Plan]) -> str:
    if not plans:
        return "未找到满足约束的方案，建议放宽预算或营养目标。"
    lines = [f"✅ 共生成 {len(plans)} 个推荐方案：\n"]
    for idx, p in enumerate(plans, 1):
        items = " + ".join(f"{i.name}(¥{i.price:.1f})" for i in p.items)
        lines.append(f"方案{idx}：{items}")
        lines.append(f"   原价 ¥{p.subtotal:.2f}  优惠 -¥{p.discount:.2f}  "
                     f"→ 实付 ¥{p.payable:.2f}  | 热量 {p.calories:.0f}kcal  蛋白 {p.protein:.0f}g  件数 {p.count}")
        if p.coupons_used:
            lines.append(f"   用券：{', '.join(p.coupons_used)}")
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 内嵌样例（无 Token 也可演示）
# --------------------------------------------------------------------------- #
DEMO_DATA = {
    "menu": [
        {"code": "M1", "name": "巨无霸", "price": 24.0, "calories": 563, "protein": 28, "tags": ["汉堡", "招牌"], "category": "burger"},
        {"code": "M2", "name": "麦辣鸡腿堡", "price": 21.0, "calories": 517, "protein": 25, "tags": ["汉堡"], "category": "burger"},
        {"code": "M3", "name": "双层吉士堡", "price": 19.0, "calories": 450, "protein": 26, "tags": ["汉堡"], "category": "burger"},
        {"code": "M4", "name": "麦香鸡", "price": 14.0, "calories": 410, "protein": 16, "tags": ["汉堡", "平价"], "category": "burger"},
        {"code": "F1", "name": "中薯条", "price": 12.0, "calories": 320, "protein": 4, "tags": ["小吃"], "category": "side"},
        {"code": "F2", "name": "玉米杯", "price": 10.0, "calories": 120, "protein": 3, "tags": ["小吃", "轻食"], "category": "side"},
        {"code": "D1", "name": "可口可乐中杯", "price": 9.0, "calories": 150, "protein": 0, "tags": ["饮料"], "category": "drink"},
        {"code": "D2", "name": "鲜煮咖啡", "price": 13.0, "calories": 5, "protein": 1, "tags": ["饮料", "提神"], "category": "drink"},
        {"code": "B1", "name": "麦麦脆汁鸡(2块)", "price": 22.0, "calories": 480, "protein": 30, "tags": ["鸡", "招牌"], "category": "chicken"},
        {"code": "B2", "name": "麦辣鸡翅(2块)", "price": 16.0, "calories": 350, "protein": 18, "tags": ["鸡"], "category": "chicken"},
        {"code": "S1", "name": "吉士蛋麦满分", "price": 13.0, "calories": 290, "protein": 15, "tags": ["早餐"], "category": "breakfast"},
        {"code": "S2", "name": "猪柳蛋麦满分", "price": 17.0, "calories": 420, "protein": 22, "tags": ["早餐"], "category": "breakfast"},
    ],
    "coupons": [
        {"cid": "C1", "name": "满40减8", "ctype": "fixed", "threshold": 40, "value": 8, "applies_to": [], "min_spend": 0},
        {"cid": "C2", "name": "满60减15", "ctype": "fixed", "threshold": 60, "value": 15, "applies_to": [], "min_spend": 0},
        {"cid": "C3", "name": "全场8折(上限10)", "ctype": "percent", "value": 0.8, "max_discount": 10, "applies_to": [], "min_spend": 0},
        {"cid": "C4", "name": "巨无霸特减5", "ctype": "item_fixed", "value": 5, "applies_to": ["M1"], "min_spend": 0},
        {"cid": "C5", "name": "麦辣鸡翅特减3", "ctype": "item_fixed", "value": 3, "applies_to": ["B2"], "min_spend": 0},
    ],
}


def load_data(path: Optional[str]) -> (List[Item], List[Coupon]):
    raw = json.load(open(path, "r", encoding="utf-8")) if path else DEMO_DATA
    menu = [Item(**m) for m in raw["menu"]]
    coupons = [Coupon(**c) for c in raw.get("coupons", [])]
    return menu, coupons


def main():
    ap = argparse.ArgumentParser(description="麦麦省钱作战室 优化引擎")
    ap.add_argument("--input", help="输入 JSON 路径(含 menu/coupons)")
    ap.add_argument("--demo", action="store_true", help="使用内嵌样例演示")
    ap.add_argument("--dump-sample", action="store_true", help="导出样例 JSON 到 sample_data.json")
    ap.add_argument("--goal", default="balanced",
                    choices=["cheapest", "best_value", "high_protein", "max_items", "balanced"])
    ap.add_argument("--budget", type=float, default=40.0)
    ap.add_argument("--max-cal", type=float, default=None, help="热量上限 kcal")
    ap.add_argument("--min-protein", type=float, default=0.0)
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--exclude", nargs="*", default=[], help="排除含这些标签的商品")
    ap.add_argument("--require", nargs="*", default=[], help="必须含这些标签")
    args = ap.parse_args()

    if args.dump_sample:
        with open("sample_data.json", "w", encoding="utf-8") as f:
            json.dump(DEMO_DATA, f, ensure_ascii=False, indent=2)
        print("已导出 sample_data.json")
        return

    use_demo = args.demo or not args.input
    menu, coupons = load_data(None if use_demo else args.input)

    plans = solve(menu, coupons, args)
    print(f"[目标={args.goal}  预算≤¥{args.budget}]")
    print(render(plans))

    # 同时输出机器可读 JSON
    out = {
        "goal": args.goal,
        "budget": args.budget,
        "recommendations": [
            {
                "items": [asdict(i) for i in p.items],
                "subtotal": p.subtotal,
                "discount": p.discount,
                "payable": p.payable,
                "coupons_used": p.coupons_used,
                "calories": p.calories,
                "protein": p.protein,
                "count": p.count,
            }
            for p in plans
        ],
    }
    with open("plan_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("（结构化结果已写入 plan_result.json）")


if __name__ == "__main__":
    main()
