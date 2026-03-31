#!/usr/bin/env python3
"""
七圣召唤卡牌数据获取工具 (并发版本)
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import urllib.request

BASE_URL = "https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://baike.mihoyo.com",
    "Referer": "https://baike.mihoyo.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

CHANNELS = {
    "character": 233,   # 角色牌
    "action": 234,      # 行动牌
    "monster": 235,     # 魔物牌
}


def fetch_json(url: str, headers: dict | None = None) -> dict[str, Any]:
    req_headers = HEADERS.copy()
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_content_list(channel_id: int) -> list[dict]:
    url = f"{BASE_URL}/home/content/list?app_sn=ys_obc&channel_id={channel_id}"
    resp = fetch_json(url)
    if resp.get("retcode") != 0:
        raise ValueError(f"API Error: {resp.get('message')}")
    data = resp.get("data", {})
    items = data.get("list", [])
    if items and "list" in items[0]:
        return items[0]["list"]
    return []


def get_entry_page(content_id: int) -> dict[str, Any]:
    url = (
        "https://act-api-takumi-static.mihoyo.com/"
        f"hoyowiki/genshin/wapi/entry_page?"
        f"app_sn=ys_obc&entry_page_id={content_id}&lang=zh-cn"
    )
    headers = {"x-rpc-wiki_app": "genshin"}
    resp = fetch_json(url, headers)
    if resp.get("retcode") != 0:
        raise ValueError(f"API Error: {resp.get('message')}")
    return resp.get("data", {}).get("page", {})


def save_json(data: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download_card(args: tuple) -> dict:
    card_info, output_dir = args
    content_id = card_info["content_id"]
    title = card_info["title"]
    
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in title)
    filename = f"{content_id}_{safe_name}.json"
    filepath = output_dir / filename
    
    if filepath.exists():
        return {"status": "skip", "title": title, "id": content_id}
    
    try:
        data = get_entry_page(content_id)
        save_json(data, filepath)
        return {"status": "success", "title": title, "id": content_id}
    except Exception as e:
        return {"status": "error", "title": title, "id": content_id, "error": str(e)}


def download_cards_concurrent(
    cards: list[dict], output_dir: Path, max_workers: int = 10
) -> tuple[int, int, list[dict]]:
    success = 0
    failed = 0
    errors = []
    
    args_list = [(card, output_dir) for card in cards]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(download_card, args): args[0] for args in args_list}
        
        for future in as_completed(futures):
            result = future.result()
            card_info = futures[future]
            idx = args_list.index((card_info, output_dir)) + 1
            total = len(args_list)
            
            if result["status"] == "success":
                success += 1
                print(f"[{idx}/{total}] ✓ {result['title']}")
            elif result["status"] == "skip":
                success += 1
                print(f"[{idx}/{total}] ⊘ {result['title']} (cached)")
            else:
                failed += 1
                errors.append(result)
                print(f"[{idx}/{total}] ✗ {result['title']}: {result.get('error', 'unknown')}")
    
    return success, failed, errors


def main():
    parser = argparse.ArgumentParser(description="获取七圣召唤卡牌数据")
    parser.add_argument(
        "--type",
        choices=["character", "action", "monster", "all"],
        default="all",
        help="卡牌类型: character=角色牌, action=行动牌, monster=魔物牌, all=全部",
    )
    parser.add_argument("--output", "-o", default="data/raw", help="输出目录")
    parser.add_argument("--workers", "-w", type=int, default=10, help="并发数")
    parser.add_argument("--limit", "-l", type=int, default=None, help="限制数量")
    
    args = parser.parse_args()
    
    output_base = Path(args.output)
    output_base.mkdir(parents=True, exist_ok=True)
    
    types_to_fetch = []
    if args.type == "all":
        types_to_fetch = ["character", "action", "monster"]
    else:
        types_to_fetch = [args.type]
    
    total_success = 0
    total_fail = 0
    all_errors = []
    start_time = time.time()
    
    for card_type in types_to_fetch:
        channel_id = CHANNELS[card_type]
        output_dir = output_base / card_type
        output_dir.mkdir(exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"获取 {card_type.upper()} 数据 (Channel: {channel_id})")
        print(f"{'='*60}")
        
        print("获取列表...")
        try:
            cards = get_content_list(channel_id)
        except Exception as e:
            print(f"获取列表失败: {e}", file=sys.stderr)
            continue
        
        print(f"找到 {len(cards)} 张卡牌")
        
        if args.limit:
            cards = cards[:args.limit]
            print(f"限制处理前 {args.limit} 张")
        
        print(f"\n开始下载 (并发: {args.workers})")
        success, failed, errors = download_cards_concurrent(
            cards, output_dir, args.workers
        )
        
        total_success += success
        total_fail += failed
        all_errors.extend(errors)
        
        # 保存索引
        index_file = output_dir / "_index.json"
        index_data = [
            {"content_id": c["content_id"], "title": c["title"], "icon": c.get("icon", "")}
            for c in cards
        ]
        save_json(index_data, index_file)
        print(f"\n索引已保存: {index_file}")
        
        # 重试失败项
        if errors:
            print(f"\n{len(errors)} 个失败，3秒后重试...")
            time.sleep(3)
            for error_info in errors:
                card_info = next(
                    (c for c in cards if c["content_id"] == error_info["id"]), None
                )
                if card_info:
                    result = download_card((card_info, output_dir))
                    if result["status"] == "success":
                        total_success += 1
                        total_fail -= 1
                        print(f"  重试成功: {result['title']}")
                    else:
                        print(f"  重试失败: {result['title']}")
                    time.sleep(0.5)
    
    elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"完成! 成功: {total_success}, 失败: {total_fail}")
    print(f"耗时: {elapsed:.1f} 秒")
    if elapsed > 0:
        print(f"速度: {total_success/elapsed:.1f} 张/秒")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
