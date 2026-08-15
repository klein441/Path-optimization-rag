"""离线反馈调权脚本 — 读取 recommendation_feedback 计算权重并写入缓存

用法：
  python back/scripts/apply_feedback_weights.py
  python back/scripts/apply_feedback_weights.py --no-cache   # 只打印预览，不写缓存
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import fetch_feedback_rows, get_feedback_max_id
from feedback_weights import compute_weights


def main():
    no_cache = "--no-cache" in sys.argv
    rows = fetch_feedback_rows()
    max_id = get_feedback_max_id()
    print(f"反馈记录: {len(rows)} 条 (max_id={max_id})")
    if not rows:
        print("无反馈数据，无需调权。")
        return 0

    fw = compute_weights(rows)
    print(f"路由调权: {len(fw.route_adjust)} 条")
    for k, v in sorted(fw.route_adjust.items(), key=lambda x: -x[1]["score_bonus"])[:10]:
        factory, port = k.split("||")
        print(f"  {factory} | {port}: score_bonus={v['score_bonus']} delta_mean={v['delta_mean']} count={v['count']}")
    print(f"工厂加分: {len(fw.factory_boost)} 个 -> {fw.factory_boost}")
    print(f"港口加分: {len(fw.port_boost)} 个 -> {fw.port_boost}")

    if no_cache:
        print("(--no-cache) 未写入缓存。")
        return 0

    import json
    import time
    import config
    fw.max_id = max_id
    fw.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(config.FEEDBACK_WEIGHTS_CACHE), exist_ok=True)
    with open(config.FEEDBACK_WEIGHTS_CACHE, "w", encoding="utf-8") as f:
        json.dump(fw.to_dict(), f, ensure_ascii=False, indent=2)
    print(f"已写入缓存: {config.FEEDBACK_WEIGHTS_CACHE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())