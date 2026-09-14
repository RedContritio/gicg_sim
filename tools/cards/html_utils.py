"""HTML 解析公共工具 — 用 lxml.html (C extension,容错好) 处理 wiki HTML fragment。

从 parse.py 拆出。strip_html / html_to_multiline_text 是其他模块(extractors,
character_builders, terms)的基础依赖。
"""

from __future__ import annotations

import html
import re

import lxml.etree
import lxml.html

_DETAIL_SUP_RE = re.compile(r'\[详情\]')


def _parse_fragment(html_str: str) -> lxml.etree._Element | None:
    """把 HTML fragment 包成 <root> 后用 lxml.html 解析,返回 root element。"""
    if not html_str:
        return None
    return lxml.html.fragment_fromstring('<root>' + html_str + '</root>')


def _next_after_u(u: lxml.etree._Element) -> lxml.etree._Element | None:
    """找 ``<u>...</u>`` 关闭后第一个 element。

    打断条件:
    - u.tail 含非空文本 → 打断(surface 与 tooltip 之间不应有非空 text)
    - 跨祖先时,任一祖先的 .tail 含非空文本 → 打断
    - 跨祖先时,任一祖先未到 root 仍有非空 sibling.text 内容 → 打断

    返回 u 之后第一个 element,与 u 之间仅夹 close tags。否则 None。
    """
    if u.tail and u.tail.strip():
        return None
    cur = u
    while cur is not None:
        nxt = cur.getnext()
        if nxt is not None:
            return nxt
        cur = cur.getparent()
        if cur is None or cur.tag == 'root':
            return None
        if cur.tail and cur.tail.strip():
            return None
    return None


def strip_html(html_str: str) -> str:
    """删 HTML tag + unescape entities + 删尾随 ``[详情]``。

    先解析标签再解码文本，避免把 data-name 属性里的转义引号/HTML
    提前展开成正文。整体转义的片段逐层解码直到稳定。
    """
    if not html_str:
        return ''
    text = html_str
    for _ in range(64):
        prev = text
        if '<' not in text:
            text = html.unescape(text)
        if '<' in text:
            tree = _parse_fragment(text)
            if tree is not None:
                text = tree.text_content()
        if text == prev:
            break
    else:
        raise RuntimeError('strip_html: 64 轮 unescape 仍未稳定,wiki 数据深度异常')
    text = _DETAIL_SUP_RE.sub('', text)
    return text.strip()


def html_to_multiline_text(html_str: str) -> str:
    """strip HTML 但 ``<p>``/``<br>`` 替换成换行(保留段落结构)。

    全 lxml-based:遍历 element 把 <p>.text 前补 \\n、<br>.tail 前补 \\n,然后 text_content。
    迭代处理 wiki data-name 内嵌 escape;最多 64 轮。
    """
    if not html_str:
        return ''
    text = html_str
    for _ in range(64):
        prev = text
        if '<' not in text:
            text = html.unescape(text)
        if '<' not in text:
            if text == prev:
                break
            continue
        tree = _parse_fragment(text)
        if tree is None:
            break
        for br in tree.iter('br'):
            tail = br.tail or ''
            br.tail = '\n' + tail
        for p in tree.iter('p'):
            p.text = (
                ('\n' + (p.text or '')) if p.getprevious() is not None or p.getparent() is not tree else (p.text or '')
            )
        text = tree.text_content()
        if text == prev:
            break
    else:
        raise RuntimeError(f'html_to_multiline_text: 64 轮迭代仍未稳定;input[:200]={html_str[:200]!r}')
    text = _DETAIL_SUP_RE.sub('', text)
    return text.strip()
