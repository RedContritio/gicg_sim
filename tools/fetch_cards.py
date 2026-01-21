import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime


API_URL = "https://hk4e-api-static.mihoyo.com/event/e20221207cardlanding/v2/card_config?lang=zh-cn"


def build_request_body(card_type: int, page: int, page_size: int) -> bytes:
    """
    构造请求体。

    card_type: 0 = 角色牌, 1 = 行动牌
    """
    body = {
        "page": page,
        "page_size": page_size,
        "card_type": card_type,
        "role_search": {
            "element_type": "",
            "weapon": "",
            "belong": "",
        },
        "action_search": {
            "action_card_type": "",
            "cost_num": "",
            "is_other_cost": False,
        },
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def fetch_page(card_type: int, page: int, page_size: int) -> dict:
    """抓取一页数据并返回解析后的 JSON。"""
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://webstatic.mihoyo.com",
        "referer": "https://webstatic.mihoyo.com/",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        ),
        "cache-control": "no-cache",
        "pragma": "no-cache",
    }

    data = build_request_body(card_type=card_type, page=page, page_size=page_size)
    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_cards(cards: list[dict], out_dir: str, prefix: str) -> None:
    """
    将一批卡牌保存为独立 JSON 文件。

    文件名规则：
      {prefix}_{id}_{slugified_name}.json
    其中 prefix 为 'role' 或 'action'。

    如果文件已存在：
    - 内容一致：跳过保存
    - 内容不一致：备份旧文件（添加时间戳后缀），然后保存新内容
    """

    def slugify(s: str) -> str:
        # 只保留常见安全字符，其他全部替换为下划线
        return "".join(ch if ch.isalnum() else "_" for ch in s).strip("_") or "noname"

    for card in cards:
        cid = card.get("id", "unknown")
        name = card.get("name", "noname")
        filename = f"{prefix}_{cid}_{slugify(name)}.json"
        path = os.path.join(out_dir, filename)

        # 检查文件是否存在
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing_card = json.load(f)
                # 比较内容（忽略顺序差异）
                if json.dumps(
                    existing_card, sort_keys=True, ensure_ascii=False
                ) == json.dumps(card, sort_keys=True, ensure_ascii=False):
                    # 内容一致，跳过
                    continue
                # 内容不一致，备份旧文件
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = (
                    f"{prefix}_{cid}_{slugify(name)}.backup.{timestamp}.json"
                )
                backup_path = os.path.join(out_dir, backup_filename)
                os.rename(path, backup_path)
                print(
                    f"[INFO] 卡牌 {filename} 内容已更新，旧文件已备份为 {backup_filename}"
                )
            except (json.JSONDecodeError, OSError) as e:
                # 如果读取失败，也备份并继续保存
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_filename = (
                    f"{prefix}_{cid}_{slugify(name)}.backup.{timestamp}.json"
                )
                backup_path = os.path.join(out_dir, backup_filename)
                try:
                    os.rename(path, backup_path)
                    print(f"[WARN] 卡牌 {filename} 读取失败，已备份旧文件: {e}")
                except OSError:
                    print(f"[WARN] 卡牌 {filename} 备份失败，将覆盖: {e}")

        # 保存新内容
        with open(path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)


def download_cards(
    card_type: int,
    max_pages: int | None,
    page_size: int,
    out_root: str,
    sleep_sec: float = 0.2,
) -> None:
    """
    分页下载卡牌数据。

    - card_type: 0 角色牌, 1 行动牌
    - max_pages: 限制最多抓取多少页（None 表示抓完所有页）
    - page_size: 每页大小
    - out_root: 输出根目录（会在其中创建 role / action 子目录）
    """
    subdir = "role" if card_type == 0 else "action"
    out_dir = os.path.join(out_root, subdir)
    ensure_dir(out_dir)

    page = 1
    total_page = None

    while True:
        if max_pages is not None and page > max_pages:
            break

        try:
            resp = fetch_page(card_type=card_type, page=page, page_size=page_size)
        except urllib.error.HTTPError as e:
            print(f"[ERROR] HTTP {e.code} on page {page}", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] request failed on page {page}: {e}", file=sys.stderr)
            break

        if resp.get("retcode") != 0:
            print(f"[ERROR] retcode != 0 on page {page}: {resp}", file=sys.stderr)
            break

        data = resp.get("data") or {}
        total_page = data.get("total_page") or total_page
        role_infos = data.get("role_card_infos") or []
        action_infos = data.get("action_card_infos") or []

        cards = role_infos if card_type == 0 else action_infos

        if not cards:
            print(f"[INFO] no cards on page {page}, stop.")
            break

        print(
            f"[INFO] page {page} fetched, {len(cards)} cards, "
            f"total_page={total_page}",
            flush=True,
        )
        save_cards(cards=cards, out_dir=out_dir, prefix=subdir)

        if total_page is not None and page >= total_page:
            break

        page += 1
        time.sleep(sleep_sec)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从米哈游接口抓取七圣召唤卡牌配置（角色/行动）并保存为独立 JSON。",
    )
    parser.add_argument(
        "--card-type",
        choices=["role", "action", "both"],
        default="both",
        help="抓取的卡牌类型：role=角色牌, action=行动牌, both=全部（默认）",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="每种 card_type 最多抓取多少页（默认 None，抓取全部页；设置为正整数可限制页数）",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=20,
        help="每页数量（接口默认 10，这里可配置，建议不要太大）",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="data",
        help="输出根目录，相对项目根目录（默认 data）",
    )

    args = parser.parse_args()

    out_root = os.path.abspath(args.out_dir)
    ensure_dir(out_root)

    if args.card_type in ("role", "both"):
        download_cards(
            card_type=0,
            max_pages=args.max_pages,
            page_size=args.page_size,
            out_root=out_root,
        )

    if args.card_type in ("action", "both"):
        download_cards(
            card_type=1,
            max_pages=args.max_pages,
            page_size=args.page_size,
            out_root=out_root,
        )


if __name__ == "__main__":
    main()
