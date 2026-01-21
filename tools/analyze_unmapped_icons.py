import argparse
import json
import os
from collections import defaultdict


def walk_json_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".json"):
                yield os.path.join(dirpath, name)


def analyze_unmapped_icons(action_map_path: str, action_dir: str) -> None:
    """
    分析使用中文描述的 icon URL，列出相关卡牌信息，帮助用户判断应该使用什么 cost_type。
    """
    # 读取映射表，找出使用中文描述的条目
    try:
        with open(action_map_path, "r", encoding="utf-8") as f:
            action_map_data = json.load(f)
    except Exception:
        print(f"[ERROR] 无法读取映射表：{action_map_path}")
        return

    unmapped_urls: dict[str, str] = {}  # {icon_url: description}
    for mapping in action_map_data.get("mappings", []):
        icon_url = mapping.get("icon_url", "")
        cost_type = mapping.get("cost_type", "").strip()
        if icon_url and cost_type and not cost_type.isdigit():
            unmapped_urls[icon_url] = cost_type

    if not unmapped_urls:
        print("[INFO] 没有找到使用中文描述的映射条目")
        return

    print(f"[INFO] 找到 {len(unmapped_urls)} 个使用中文描述的映射：")
    for url, desc in unmapped_urls.items():
        print(f"  - {desc}: {url[:60]}...")

    # 扫描 action 卡牌，找出使用这些 URL 的卡牌
    print("\n[INFO] 相关卡牌信息：\n")
    
    for icon_url, description in unmapped_urls.items():
        print(f"=" * 80)
        print(f"描述: {description}")
        print(f"URL: {icon_url[:80]}...")
        print(f"-" * 80)
        
        cards_info: list[dict] = []
        
        for path in walk_json_files(action_dir):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            
            # 检查是否使用了这个 icon_url
            used_fields: list[str] = []
            for key, value in data.items():
                if key.endswith("_icon") and value == icon_url:
                    used_fields.append(key)
            
            if used_fields:
                card_info = {
                    "name": data.get("name", "未知"),
                    "id": data.get("id", "未知"),
                    "action_type": data.get("action_type", ""),
                    "used_fields": used_fields,
                    "cost_info": {
                        k: v
                        for k, v in data.items()
                        if k.startswith("cost_") and not k.endswith("_icon")
                    },
                }
                cards_info.append(card_info)
        
        # 按 cost 信息分组显示
        cost_groups: dict[str, list[dict]] = defaultdict(list)
        for card in cards_info:
            cost_key = json.dumps(card["cost_info"], sort_keys=True, ensure_ascii=False)
            cost_groups[cost_key].append(card)
        
        print(f"共找到 {len(cards_info)} 张卡牌，分为 {len(cost_groups)} 种 cost 模式：\n")
        
        for idx, (cost_key, cards) in enumerate(cost_groups.items(), 1):
            cost_info = json.loads(cost_key)
            print(f"模式 {idx} (共 {len(cards)} 张卡牌):")
            print(f"  Cost 信息: {cost_info}")
            print(f"  使用的字段: {cards[0]['used_fields']}")
            print(f"  示例卡牌:")
            for card in cards[:5]:  # 只显示前 5 张
                print(f"    - {card['name']} (ID: {card['id']}, 类型: {card['action_type']})")
            if len(cards) > 5:
                print(f"    ... 还有 {len(cards) - 5} 张")
            print()
        
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="分析使用中文描述的 icon URL，列出相关卡牌信息，帮助判断应该使用什么 cost_type。",
    )
    parser.add_argument(
        "--action-dir",
        type=str,
        default="data/action",
        help="action 卡牌目录（默认 data/action）",
    )
    parser.add_argument(
        "--action-icon-map",
        type=str,
        default="data/meta/action_icon_urls_to_map.json",
        help="action 卡牌 icon URL 映射表（默认 data/meta/action_icon_urls_to_map.json）",
    )

    args = parser.parse_args()
    action_dir = os.path.abspath(args.action_dir)
    action_map_path = os.path.abspath(args.action_icon_map)

    analyze_unmapped_icons(action_map_path, action_dir)


if __name__ == "__main__":
    main()
