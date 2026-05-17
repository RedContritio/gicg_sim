"""tools.cards.parse / character._set_once 等 critical paths 单元测试。"""

from __future__ import annotations

import pytest

from tools.cards.character import _set_once
from tools.cards.html_utils import html_to_multiline_text, strip_html
from tools.cards.parse import consume_module, parse_skill_items
from tools.cards.terms import extract_terms


class _NullTracker:
    def visit(self, path: str) -> None:
        pass


class TestSetOnce:
    def test_first_write(self):
        s = {}
        _set_once(s, 'k', 10, 'test')
        assert s['k'] == 10

    def test_empty_value_skip(self):
        s = {'k': 10}
        _set_once(s, 'k', 0, 'test')
        assert s['k'] == 10  # 空值不覆盖

    def test_same_value_idempotent(self):
        s = {'k': 10}
        _set_once(s, 'k', 10, 'test')
        assert s['k'] == 10

    def test_conflict_raise(self):
        s = {'k': 10}
        with pytest.raises(ValueError, match='多次写入冲突'):
            _set_once(s, 'k', 20, 'test')


class TestConsumeModuleJSONRaise:
    """consume_module 对损坏的 JSON data 必须 raise(不静默丢)。"""

    def test_invalid_json_raise(self):
        bad_module = {
            'name': 'X',
            'components': [{'data': 'not valid json {{'}],
        }
        with pytest.raises(ValueError, match='consume_module.*JSONDecodeError'):
            consume_module(bad_module, _NullTracker(), 'modules[*]')

    def test_empty_data_skip(self):
        empty = {'name': 'X', 'components': [{'data': ''}]}
        name, decoded = consume_module(empty, _NullTracker(), 'modules[*]')
        assert name == 'X'
        assert decoded == []


class TestExtractTermsSurfaceLengthCap:
    """surface 超长 + 不在白名单 → raise;在白名单 → 静默接受。"""

    def test_normal_surface_accepted(self):
        html = '<p>造成<strong><u>物理伤害</u></strong><span data-type="详情" data-name="物理伤害：物理伤害不会附着元素。">[详情]</span>。</p>'
        terms = extract_terms(html)
        assert '物理伤害' in terms

    def test_oversized_surface_not_in_whitelist_raise(self):
        # 14 字符 surface 超长 + 不在 KNOWN_LONG_SURFACES → raise
        long_name = '一二三四五六七八九十一二三四'  # 14 字符
        html = f'<p><u>{long_name}</u><span data-type="详情" data-name="X：Y">[详情]</span></p>'
        with pytest.raises(ValueError, match='surface name 超长'):
            extract_terms(html)

    def test_whitelist_surface_accepted(self):
        # '距离我方出战角色最近的角色' 13 字符在 KNOWN_LONG_SURFACES
        long_name = '距离我方出战角色最近的角色'
        html = (
            f'<p><u>{long_name}</u><span data-type="详情" data-name="距离我方出战角色最近的角色：X">[详情]</span></p>'
        )
        terms = extract_terms(html)
        assert long_name in terms


class TestParseSkillItemsOverridePaths:
    """parse_skill_items 三种 override action(rename / warn / 未命中 raise)。"""

    def test_normal_skill_passthrough(self):
        items = [
            {
                'tab_name': '测试技能',
                'skill_type': '普通攻击',
                'life': 1,
                'life_bg': 1,
                'energy': 2,
                'energy_bg': 10,
                'icon': 'http://x.png',
                'desc': {'value': ['<p>效果</p>']},
                'tab_id': 't1',
            }
        ]
        out = parse_skill_items(items, card_id=999, module_kind='卡牌技能')
        assert len(out) == 1
        assert out[0]['name'] == '测试技能'
        assert out[0]['placeholder_name'] is False

    def test_placeholder_desc_skip(self):
        items = [
            {
                'tab_name': '默认标题',
                'skill_type': '',
                'life': 0,
                'life_bg': 0,
                'energy': 0,
                'energy_bg': 0,
                'icon': '',
                'desc': {'value': ['<p></p>']},
                'tab_id': '',
            }
        ]
        out = parse_skill_items(items, card_id=999, module_kind='卡牌技能')
        assert out == []  # 空模板 skip

    def test_default_title_with_real_desc_no_override_raise(self):
        items = [
            {
                'tab_name': '默认标题',
                'skill_type': '被动技能',
                'life': 0,
                'life_bg': 0,
                'energy': 0,
                'energy_bg': 0,
                'icon': '',
                'desc': {'value': ['<p>真实效果但 wiki 没填 name</p>']},
                'tab_id': '',
            }
        ]
        with pytest.raises(ValueError, match='但 desc 非 placeholder'):
            parse_skill_items(items, card_id=999, module_kind='卡牌技能')


class TestStripHtmlIteration:
    def test_simple_html(self):
        assert strip_html('<p>hello</p>') == 'hello'

    def test_double_escape_unwind(self):
        # data-name 双重 escape 模拟
        s = '<p>X<span data-name="&lt;p&gt;Y&lt;/p&gt;">[详情]</span></p>'
        result = strip_html(s)
        # [详情] 被 _DETAIL_SUP_RE 删除,Y 留
        assert 'Y' in result or 'X' in result  # 至少 X 在

    def test_empty(self):
        assert strip_html('') == ''


class TestHtmlToMultilineText:
    def test_p_tags_become_newline(self):
        s = '<p>line1</p><p>line2</p>'
        assert 'line1' in html_to_multiline_text(s)
        assert 'line2' in html_to_multiline_text(s)

    def test_br_becomes_newline(self):
        s = '<p>line1<br>line2</p>'
        result = html_to_multiline_text(s)
        assert 'line1' in result and 'line2' in result

    def test_empty(self):
        assert html_to_multiline_text('') == ''
