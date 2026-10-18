#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦麦省钱作战室 · 真实端到端演示 (real_demo.py)
读取 real_catalog.json（真实菜单+真实营养对齐后的商品目录），
按目标做组合优化，输出 Top 方案 + 供 calculate-price 校验的商品清单。
"""
import json
import itertools
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CATALOG = os.path.join(_HERE, "real_catalog.json")


def load_catalog(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def score_basket(items, goal):
    """items: list of (item_dict, qty). 返回 (score, metrics)。"""
    total_price = sum(it["price"] * q for it, q in items)
    total_kcal = sum(it["kcal"] * q for it, q in items)
    total_protein = sum(it["protein"] * q for it, q in items)
    total_fat = sum(it["fat"] * q for it, q in items)
    total_sodium = sum(it["sodium"] * q for it, q in items)
    n = sum(q for _, q in items)
    metrics = {
        "price": round(total_price, 2),
        "kcal": total_kcal,
        "protein": total_protein,
        "fat": total_fat,
        "sodium": total_sodium,
        "items": n,
        "detail": [{"code": it["code"], "name": it["name"],
                    "qty": q, "unit_price": it["price"],
                    "subtotal": round(it["price"] * q, 2)} for it, q in items],
    }
    if goal == "high_protein":
        # 单位价格蛋白质密度优先，蛋白质总量为辅
        score = total_protein - 0.05 * total_price
    elif goal == "cheapest":
        score = -total_price
    elif goal == "best_value":
        score = total_protein / max(total_price, 0.01)
    elif goal == "max_items":
        score = n - 0.1 * total_price
    elif goal == "balanced":
        score = total_protein / max(total_price, 0.01) - 0.002 * max(total_kcal - 500, 0)
    else:
        score = total_protein
    return score, metrics


def optimize(catalog, goal="high_protein", budget=40.0, max_kcal=700, max_size=3):
    items = catalog["items"]
    candidates = []
    # 生成 1..max_size 件的组合（允许同品重复用 qty 表示，这里枚举组合后展开 qty）
    for size in range(1, max_size + 1):
        for combo in itertools.combinations(range(len(items)), size):
            # 对每件 1..2 份
            qty_choices = itertools.product([1, 2], repeat=size)
            for qts in qty_choices:
                basket = [(items[i], q) for i, q in zip(combo, qts)]
                price = sum(it["price"] * q for it, q in basket)
                kcal = sum(it["kcal"] * q for it, q in basket)
                if price > budget or kcal > max_kcal:
                    continue
                score, metrics = score_basket(basket, goal)
                candidates.append((score, metrics))
    # 除重（同商品组合不同顺序但 qty 组合相同已天然去重；仍按 detail 排序去重）
    seen = set()
    uniq = []
    for score, m in candidates:
        key = tuple((d["code"], d["qty"]) for d in m["detail"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append((score, m))
    uniq.sort(key=lambda x: x[0], reverse=True)
    return uniq[:5]


def main():
    goal = sys.argv[1] if len(sys.argv) > 1 else "high_protein"
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 40.0
    max_kcal = float(sys.argv[3]) if len(sys.argv) > 3 else 700.0

    cat = load_catalog(CATALOG)
    top = optimize(cat, goal=goal, budget=budget, max_kcal=max_kcal)
    print(f"门店: {cat['storeName']} ({cat['storeCode']})")
    print(f"目标={goal}  预算≤{budget}  限热量≤{max_kcal}kcal  候选方案数={len(top)}")
    print("=" * 60)
    for rank, (score, m) in enumerate(top, 1):
        names = " + ".join(f"{d['name']}×{d['qty']}" for d in m["detail"])
        print(f"方案{rank}  评分={score:.2f}  ¥{m['price']}  {m['kcal']}kcal  "
              f"蛋白{m['protein']}g  脂肪{m['fat']}g  钠{m['sodium']}mg  件数{m['items']}")
        print(f"       {names}")
    # 导出 Top1 供 calculate-price 校验
    if top:
        top1 = top[0][1]
        payload = {
            "storeCode": cat["storeCode"],
            "orderType": 1,
            "beType": 1,
            "items": [{"productCode": d["code"], "quantity": d["qty"]} for d in top1["detail"]],
        }
        with open(os.path.join(_HERE, "calc_payload.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n→ 已写出 calc_payload.json（供 calculate-price 校验）")


if __name__ == "__main__":
    main()
