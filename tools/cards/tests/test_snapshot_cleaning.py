"""Keep tooltip markup out of rules and bind conversion to the selected snapshot."""

import html
import json

import pytest

from tools.cards.html_utils import html_to_multiline_text, strip_html
from tools.cards.list_ext import load_list_ext_index
from tools.cards.terms import extract_terms


@pytest.mark.parametrize('clean', [strip_html, html_to_multiline_text])
def test_quoted_tooltip_does_not_become_effect_text(clean):
    tooltip = '<p><span style="color: red">火元素伤害：</span>说明不能混进正文</p>'
    fragment = (
        '<p>造成3点<u>火元素伤害</u><span data-type="详情" data-name="'
        + html.escape(tooltip, quote=True)
        + '" class="wiki-note-text"><sup>[详情]</sup></span>，召唤奥兹。</p>'
    )
    assert clean(fragment) == '造成3点火元素伤害，召唤奥兹。'
    assert '说明不能混进正文' in extract_terms(fragment)['火元素伤害']
    assert clean(html.escape(html.escape('<p>造成3点伤害。</p>'))) == '造成3点伤害。'


def test_explicit_snapshot_index_does_not_use_default(tmp_path):
    for kind in ('character', 'action', 'monster'):
        rows = [{'content_id': 987654, 'title': '新快照独有牌'}] if kind == 'action' else []
        (tmp_path / f'{kind}.json').write_text(json.dumps(rows))
    index = load_list_ext_index(tmp_path)
    assert set(index) == {987654}
    assert index[987654]['title'] == '新快照独有牌'
    (tmp_path / 'character.json').unlink()
    with pytest.raises(FileNotFoundError):
        load_list_ext_index(tmp_path)
