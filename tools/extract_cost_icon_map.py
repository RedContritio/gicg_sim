import argparse
import json
import os
from collections import defaultdict
from typing import Any


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def walk_json_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".json"):
                yield os.path.join(dirpath, name)


def collect_cost_icon_pairs(obj: Any, mapping: dict[str, set[str]]) -> None:
    if isinstance(obj, dict):
        if "cost_type" in obj and "icon" in obj:
            ctype = str(obj["cost_type"])
            icon = str(obj["icon"])
            mapping[ctype].add(icon)
        for v in obj.values():
            collect_cost_icon_pairs(v, mapping)
    elif isinstance(obj, list):
        for item in obj:
            collect_cost_icon_pairs(item, mapping)


def build_cost_icon_map(data_root: str) -> dict[str, list[str]]:
    mapping: dict[str, set[str]] = defaultdict(set)

    for path in walk_json_files(data_root):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        collect_cost_icon_pairs(data, mapping)

    # 将 set 转为排序后的 list，便于查看和版本控制
    return {ctype: sorted(list(icons)) for ctype, icons in sorted(mapping.items())}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 data 目录扫描 JSON，提取 cost_type -> icon 的映射表。",
    )
    parser.add_argument(
        "--data-root",
        type=str,
        default="data",
        help="卡牌数据根目录（默认 data）",
    )
    parser.add_argument(
        "--out-file",
        type=str,
        default="data/meta/cost_type_icon_map.json",
        help="输出映射表文件路径（默认 data/meta/cost_type_icon_map.json）",
    )

    args = parser.parse_args()

    data_root = os.path.abspath(args.data_root)
    out_file = os.path.abspath(args.out_file)

    cost_icon_map = build_cost_icon_map(data_root)

    out_dir = os.path.dirname(out_file)
    ensure_dir(out_dir)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(cost_icon_map, f, ensure_ascii=False, indent=2)

    print(f"[INFO] cost_type -> icon 映射表已生成：{out_file}")
    print(f"[INFO] 共收集到 {len(cost_icon_map)} 种 cost_type")


if __name__ == "__main__":
    main()

