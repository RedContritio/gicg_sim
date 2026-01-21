import argparse
import json
import os
from copy import deepcopy
from typing import Any


def walk_json_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".json"):
                yield os.path.join(dirpath, name)


def build_icon_to_cost_type_map(
    icon_map_path: str, action_map_path: str | None = None
) -> dict[str, str]:
    """
    从 cost_type_icon_map.json 和 action_icon_urls_to_map.json 建立反向映射：icon URL -> cost_type。
    """
    icon_to_type: dict[str, str] = {}

    # 读取 role 卡牌的映射表
    try:
        with open(icon_map_path, "r", encoding="utf-8") as f:
            cost_type_icon_map = json.load(f)
        for cost_type, icon_urls in cost_type_icon_map.items():
            for icon_url in icon_urls:
                if icon_url and icon_url.startswith("http"):
                    icon_to_type[icon_url] = cost_type
    except Exception:
        pass

    # 读取 action 卡牌的手动映射表
    if action_map_path:
        try:
            with open(action_map_path, "r", encoding="utf-8") as f:
                action_map_data = json.load(f)
            for mapping in action_map_data.get("mappings", []):
                icon_url = mapping.get("icon_url", "")
                cost_type = mapping.get("cost_type", "").strip()
                if icon_url and cost_type:
                    # 允许任何字符串作为 cost_type（包括中文）
                    icon_to_type[icon_url] = cost_type
        except Exception:
            pass

    return icon_to_type


def normalize_role_card(obj: Any) -> tuple[Any, bool]:
    """
    处理角色卡牌：删除 skill_costs 中的 icon 字段。
    """
    changed = False

    if isinstance(obj, dict):
        # 处理 skill_costs 中的 icon 字段
        if "cost_type" in obj and "cost_num" in obj and "icon" in obj:
            del obj["icon"]
            changed = True

        # 递归子字段
        for k, v in list(obj.items()):
            new_v, sub_changed = normalize_role_card(v)
            if sub_changed:
                obj[k] = new_v
                changed = True

    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_item, sub_changed = normalize_role_card(item)
            if sub_changed:
                obj[idx] = new_item
                changed = True

    return obj, changed


def normalize_action_card(obj: Any, icon_to_type: dict[str, str]) -> tuple[Any, bool]:
    """
    处理行动卡牌：基于 cost_typeX_icon 反推 cost_typeX，然后删除 icon 字段。
    """
    changed = False

    if isinstance(obj, dict):
        # 处理 cost_typeX_icon 字段（如 cost_type1_icon, cost_type2_icon 等）
        icon_keys_to_remove: list[str] = []
        type_keys_to_add: dict[str, str] = {}

        for k, v in obj.items():
            if (
                isinstance(k, str)
                and k.endswith("_icon")
                and isinstance(v, str)
                and v.startswith("http")
            ):
                # 尝试从映射表查找对应的 cost_type
                cost_type = icon_to_type.get(v)
                if cost_type:
                    # 提取数字部分（如 cost_type1_icon -> 1）
                    prefix = k[: -len("_icon")]
                    if prefix.startswith("cost_type"):
                        num_part = prefix[len("cost_type") :]
                        type_key = f"cost_type{num_part}"
                        type_keys_to_add[type_key] = cost_type
                        icon_keys_to_remove.append(k)
                    else:
                        # 如果格式不对，也删除 icon 字段
                        icon_keys_to_remove.append(k)
                elif v:  # 如果有 URL 但找不到映射，也删除（可能是无效数据）
                    icon_keys_to_remove.append(k)

        # 添加 cost_type 字段
        if type_keys_to_add:
            for type_key, type_value in type_keys_to_add.items():
                obj[type_key] = type_value
            changed = True

        # 删除 icon 字段
        if icon_keys_to_remove:
            for k in icon_keys_to_remove:
                del obj[k]
            changed = True

        # 递归子字段
        for k, v in list(obj.items()):
            new_v, sub_changed = normalize_action_card(v, icon_to_type)
            if sub_changed:
                obj[k] = new_v
                changed = True

    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_item, sub_changed = normalize_action_card(item, icon_to_type)
            if sub_changed:
                obj[idx] = new_item
                changed = True

    return obj, changed


def normalize_file(path: str, icon_to_type: dict[str, str]) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False

    original = deepcopy(data)

    # 判断是角色卡牌还是行动卡牌
    is_action = "action" in path.lower() or os.path.basename(os.path.dirname(path)) == "action"

    if is_action:
        data, changed = normalize_action_card(data, icon_to_type)
    else:
        data, changed = normalize_role_card(data)

    if not changed:
        return False

    # 保存修改后的数据
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="删除 data 中卡牌 JSON 的 cost icon URL 相关字段，仅保留类型和数值。对于 action 卡牌，基于 icon URL 反推 cost_type。",
    )
    parser.add_argument(
        "--data-root",
        type=str,
        default="data",
        help="卡牌数据根目录（默认 data）",
    )
    parser.add_argument(
        "--icon-map",
        type=str,
        default="data/meta/cost_type_icon_map.json",
        help="cost_type -> icon 映射表路径（默认 data/meta/cost_type_icon_map.json）",
    )
    parser.add_argument(
        "--action-icon-map",
        type=str,
        default="data/meta/action_icon_urls_to_map.json",
        help="action 卡牌 icon URL 到 cost_type 的手动映射表（默认 data/meta/action_icon_urls_to_map.json）",
    )

    args = parser.parse_args()
    data_root = os.path.abspath(args.data_root)
    icon_map_path = os.path.abspath(args.icon_map)
    action_map_path = os.path.abspath(args.action_icon_map) if args.action_icon_map else None

    # 建立 icon -> cost_type 反向映射
    icon_to_type = build_icon_to_cost_type_map(icon_map_path, action_map_path)
    if not icon_to_type:
        print(f"[WARN] 无法加载映射表，action 卡牌的 cost_type 反推将失败")
    else:
        print(f"[INFO] 已加载 {len(icon_to_type)} 个 icon -> cost_type 映射")

    total = 0
    modified = 0

    for path in walk_json_files(data_root):
        total += 1
        if normalize_file(path, icon_to_type):
            modified += 1

    print(f"[INFO] 扫描 JSON 文件 {total} 个，其中修改 {modified} 个。")


if __name__ == "__main__":
    main()

