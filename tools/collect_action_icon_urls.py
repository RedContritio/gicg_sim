import argparse
import json
import os
from collections import defaultdict


def walk_json_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".json"):
                yield os.path.join(dirpath, name)


def collect_action_icon_urls(action_dir: str) -> dict[str, list[str]]:
    """
    收集所有 action 卡牌中出现的 cost_typeX_icon URL。
    
    返回: {icon_url: [出现该 URL 的卡牌文件名列表]}
    """
    url_to_cards: dict[str, list[str]] = defaultdict(list)
    
    for path in walk_json_files(action_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        
        card_name = os.path.basename(path)
        
        # 收集所有 cost_typeX_icon 字段中的 URL
        for key, value in data.items():
            if (
                isinstance(key, str)
                and key.endswith("_icon")
                and isinstance(value, str)
                and value.startswith("http")
            ):
                url_to_cards[value].append(f"{card_name} ({key})")
    
    return dict(url_to_cards)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="收集 action 卡牌中所有出现的 cost icon URL，生成待填映射表。",
    )
    parser.add_argument(
        "--action-dir",
        type=str,
        default="data/action",
        help="action 卡牌目录（默认 data/action）",
    )
    parser.add_argument(
        "--out-file",
        type=str,
        default="data/meta/action_icon_urls_to_map.json",
        help="输出文件路径（默认 data/meta/action_icon_urls_to_map.json）",
    )
    parser.add_argument(
        "--role-icon-map",
        type=str,
        default="data/meta/cost_type_icon_map.json",
        help="role 卡牌的 cost_type -> icon 映射表（用于参考，默认 data/meta/cost_type_icon_map.json）",
    )

    args = parser.parse_args()
    action_dir = os.path.abspath(args.action_dir)
    out_file = os.path.abspath(args.out_file)
    
    # 收集 action 卡牌中的 icon URL
    url_to_cards = collect_action_icon_urls(action_dir)
    
    # 读取 role 卡牌的映射表作为参考
    role_icon_map = {}
    try:
        with open(args.role_icon_map, "r", encoding="utf-8") as f:
            role_map = json.load(f)
            for cost_type, icon_urls in role_map.items():
                for icon_url in icon_urls:
                    if icon_url and icon_url.startswith("http"):
                        role_icon_map[icon_url] = cost_type
    except Exception:
        pass
    
    # 构建输出结构：列出每个 URL，以及它可能对应的 role 映射（如果有）
    output = {
        "说明": "此文件用于手动填写 action 卡牌中 icon URL 到 cost_type 的映射关系。",
        "填写说明": [
            "1. 对于每个 icon_url，在 'cost_type' 字段填写对应的 cost_type 值（字符串格式，如 '11'）",
            "2. 如果某个 URL 在 role 映射表中已存在，'role_mapping_hint' 会显示可能的对应关系",
            "3. 填写完成后，运行 normalize_cost_icons.py 时会使用此映射表",
        ],
        "mappings": [],
    }
    
    for icon_url, cards in sorted(url_to_cards.items()):
        mapping_entry = {
            "icon_url": icon_url,
            "cost_type": "",  # 待填写
            "role_mapping_hint": role_icon_map.get(icon_url, None),
            "appears_in_cards": sorted(cards)[:10],  # 只显示前 10 个，避免文件过大
            "total_card_count": len(cards),
        }
        output["mappings"].append(mapping_entry)
    
    # 确保输出目录存在
    out_dir = os.path.dirname(out_file)
    os.makedirs(out_dir, exist_ok=True)
    
    # 保存文件
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"[INFO] 已收集 {len(url_to_cards)} 个不同的 icon URL")
    print(f"[INFO] 映射表已保存到：{out_file}")
    print(f"[INFO] 请手动填写每个 URL 对应的 cost_type，然后重新运行 normalize_cost_icons.py")


if __name__ == "__main__":
    main()
