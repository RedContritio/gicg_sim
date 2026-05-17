#!/usr/bin/env python3
"""七圣召唤卡牌数据获取工具(并发 + 重试 + 限流版本)。

抓取 mihoyo HoYoLAB wiki 的 entry_page 接口,按 channel 拆 character /
action / monster 三类,默认输出到 ``data/raw/<type>/``。已存在的
``<id>_<title>.json`` 跳过(幂等)。

典型用法(从 repo root)::

    .venv/bin/python -m tools.cards.fetch --type all
    .venv/bin/python -m tools.cards.fetch --type action --workers 8
    .venv/bin/python -m tools.cards.fetch --type all --rate-limit 5 --max-retries 5

新增于 ADR-0011 落地后:为正式版卡池录入提供 raw 数据来源,与
``data/pools/<id>/`` 的版本化 DSL 是上下游关系(此工具拉 JSON,
后续 raw → DSL 转换由独立工具负责)。
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

BASE_URL = 'https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1'
ENTRY_PAGE_URL = 'https://act-api-takumi-static.mihoyo.com/hoyowiki/genshin/wapi/entry_page'

HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://baike.mihoyo.com',
    'Referer': 'https://baike.mihoyo.com/',
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
}

CHANNELS = {
    'character': 233,
    'action': 234,
    'monster': 235,
}


class RateLimiter:
    """Global request-rate cap shared across worker threads. min_interval
    is computed once; ``acquire`` blocks until at least that gap has
    passed since the previous call. requests_per_second <= 0 disables
    the limiter (no waiting). Used to stay polite to the upstream API
    when --workers is large."""

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


def fetch_json(url: str, headers: dict | None, timeout: float) -> dict[str, Any]:
    req_headers = HEADERS.copy()
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_with_retry(
    url: str,
    headers: dict | None,
    timeout: float,
    max_retries: int,
    limiter: RateLimiter,
) -> dict[str, Any]:
    """fetch_json + 指数 backoff(1s, 2s, 4s, ...)。重试 URLError /
    HTTPError / timeout / JSON decode 错误。mihoyo API 在并发下偶发
    429/5xx,旧版"重试一次 sleep 3s"曾掉 ~5%(workers=10)。"""
    last_err: Exception | None = None
    for attempt in range(max_retries):
        limiter.acquire()
        try:
            return fetch_json(url, headers, timeout)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
    assert last_err is not None
    raise last_err


class FetchContext:
    """Carries per-run knobs (timeout / retries / rate limit / output
    paths) so worker callables don't need 6 positional args."""

    def __init__(self, timeout: float, max_retries: int, limiter: RateLimiter, output_dir: Path):
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = limiter
        self.output_dir = output_dir


def get_content_list(channel_id: int, ctx: FetchContext) -> list[dict]:
    url = f'{BASE_URL}/home/content/list?app_sn=ys_obc&channel_id={channel_id}'
    resp = fetch_with_retry(url, None, ctx.timeout, ctx.max_retries, ctx.limiter)
    if resp.get('retcode') != 0:
        raise ValueError(f'API Error: {resp.get("message")}')
    items = resp.get('data', {}).get('list', [])
    if items and 'list' in items[0]:
        return items[0]['list']
    return []


def get_entry_page(content_id: int, ctx: FetchContext) -> dict[str, Any]:
    url = f'{ENTRY_PAGE_URL}?app_sn=ys_obc&entry_page_id={content_id}&lang=zh-cn'
    headers = {'x-rpc-wiki_app': 'genshin'}
    resp = fetch_with_retry(url, headers, ctx.timeout, ctx.max_retries, ctx.limiter)
    if resp.get('retcode') != 0:
        raise ValueError(f'API Error: {resp.get("message")}')
    return resp.get('data', {}).get('page', {})


def save_json(data: dict | list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download_card(card_info: dict, ctx: FetchContext) -> dict:
    content_id = card_info['content_id']
    title = card_info['title']
    safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in title)
    filepath = ctx.output_dir / f'{content_id}_{safe_name}.json'
    if filepath.exists():
        return {'status': 'skip', 'title': title, 'id': content_id}
    try:
        data = get_entry_page(content_id, ctx)
        save_json(data, filepath)
        return {'status': 'success', 'title': title, 'id': content_id}
    except Exception as e:
        return {'status': 'error', 'title': title, 'id': content_id, 'error': str(e)}


def download_cards_concurrent(
    cards: list[dict],
    ctx: FetchContext,
    max_workers: int,
) -> tuple[int, int, list[dict]]:
    success = 0
    failed = 0
    errors: list[dict] = []
    total = len(cards)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # enumerate gives O(1) progress index per future; replaces the
        # previous O(n²) args_list.index() lookup that scaled badly past
        # ~200 cards.
        futures = {executor.submit(download_card, card, ctx): idx for idx, card in enumerate(cards, start=1)}
        for future in as_completed(futures):
            idx = futures[future]
            result = future.result()
            if result['status'] in ('success', 'skip'):
                success += 1
                marker = '✓' if result['status'] == 'success' else '⊘'
                print(f'[{idx}/{total}] {marker} {result["title"]}')
            else:
                failed += 1
                errors.append(result)
                print(f'[{idx}/{total}] ✗ {result["title"]}: {result.get("error", "unknown")}')
    return success, failed, errors


def write_error_log(errors: list[dict], path: Path) -> None:
    """Append errors as JSON lines for postmortem; multi-type runs
    accumulate. Caller is responsible for truncating first if they
    want a fresh log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        for e in errors:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description='获取七圣召唤卡牌数据')
    parser.add_argument(
        '--type',
        choices=['character', 'action', 'monster', 'all'],
        default='all',
        help='卡牌类型: character=角色牌, action=行动牌, monster=魔物牌, all=全部',
    )
    parser.add_argument('--output', '-o', default='data/raw', help='输出目录')
    parser.add_argument('--workers', '-w', type=int, default=10, help='并发数')
    parser.add_argument('--limit', '-l', type=int, default=None, help='限制前 N 张(调试用)')
    parser.add_argument('--ids', default=None, help='只拉这些 content_id(逗号分隔)。与 --names 是 OR')
    parser.add_argument('--names', default=None, help='只拉标题含这些子串的卡(逗号分隔)。与 --ids 是 OR')
    parser.add_argument('--timeout', type=float, default=30.0, help='单请求超时秒数')
    parser.add_argument('--max-retries', type=int, default=3, help='单请求最大重试次数(指数 backoff)')
    parser.add_argument(
        '--rate-limit',
        type=float,
        default=0.0,
        help='全局每秒请求上限,0 = 不限速。workers 大时建议设 5-10',
    )
    parser.add_argument(
        '--error-log',
        default=None,
        help='错误日志路径(JSONL,append 模式);留空 = 不写文件,仅 stdout 打印',
    )
    args = parser.parse_args()

    output_base = Path(args.output)
    output_base.mkdir(parents=True, exist_ok=True)
    types_to_fetch = ['character', 'action', 'monster'] if args.type == 'all' else [args.type]
    limiter = RateLimiter(args.rate_limit)
    error_log_path = Path(args.error_log) if args.error_log else None
    id_filter = {int(x) for x in args.ids.split(',') if x.strip()} if args.ids else None
    name_filter = [x.strip() for x in args.names.split(',') if x.strip()] if args.names else None

    total_success = 0
    total_fail = 0
    start_time = time.time()

    for card_type in types_to_fetch:
        channel_id = CHANNELS[card_type]
        output_dir = output_base / card_type
        output_dir.mkdir(exist_ok=True)
        ctx = FetchContext(
            timeout=args.timeout,
            max_retries=args.max_retries,
            limiter=limiter,
            output_dir=output_dir,
        )

        print(f'\n{"=" * 60}')
        print(f'获取 {card_type.upper()} 数据 (Channel: {channel_id})')
        print(f'{"=" * 60}')

        try:
            cards = get_content_list(channel_id, ctx)
        except Exception as e:
            print(f'获取列表失败: {e}', file=sys.stderr)
            continue

        print(f'找到 {len(cards)} 张卡牌')
        if id_filter or name_filter:
            before = len(cards)
            cards = [
                c
                for c in cards
                if (id_filter and c['content_id'] in id_filter)
                or (name_filter and any(n in c['title'] for n in name_filter))
            ]
            print(f'过滤后 {len(cards)} 张(从 {before} 筛 ids={args.ids} names={args.names})')
        if args.limit:
            cards = cards[: args.limit]
            print(f'限制处理前 {args.limit} 张')

        print(f'\n开始下载 (并发={args.workers}, 重试={args.max_retries}, 限流={args.rate_limit or "off"} req/s)')
        success, failed, errors = download_cards_concurrent(cards, ctx, args.workers)
        total_success += success
        total_fail += failed

        index_data = [{'content_id': c['content_id'], 'title': c['title'], 'icon': c.get('icon', '')} for c in cards]
        save_json(index_data, output_dir / '_index.json')
        print(f'索引已保存: {output_dir / "_index.json"}')

        if errors and error_log_path:
            write_error_log(errors, error_log_path)
            print(f'错误日志写入: {error_log_path} (+{len(errors)} 条)')

    elapsed = time.time() - start_time
    print(f'\n{"=" * 60}')
    print(f'完成! 成功: {total_success}, 失败: {total_fail}')
    print(f'耗时: {elapsed:.1f} 秒')
    if elapsed > 0 and total_success > 0:
        print(f'速度: {total_success / elapsed:.1f} 张/秒')
    print(f'{"=" * 60}')
    return 1 if total_fail > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
