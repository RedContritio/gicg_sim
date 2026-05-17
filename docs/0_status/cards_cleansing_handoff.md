---
status: DONE — cleansing 全 raw 706 张 (507 action + 138 char + 61 monster) 已 cleansed
last_updated: 2026-04-30
---

# 卡牌全量 cleansing 交接

## 最终结果(2026-04-30)

- raw 总:706 张(507 action + 138 character + 61 monster);全量 cleansed,pending=0
- cleaned 目录:518 + 138 + 61 = 717(action 多 11 张是 spike 时期老数据,不影响)
- glossary:501 个术语统一字典 → `data/cleaned/_glossary.yaml`

`.venv/bin/python -m tools.cards.check_list_sync` ✓ 三类同步;
`.venv/bin/python -m tools.list_pending_cards` ✓ pending=0。

## 后续 patch workflow(新游戏版本 / list-only 补抓)

每波:

1. `.venv/bin/python -m tools.cards.check_list_sync`,看是否有 list-only IDs
2. 缺则 `.venv/bin/python -m tools.cards.fetch --type <kind> --output ~/Documents/gicg_sim/data/raw --ids <id1,id2>`
3. `.venv/bin/python -m tools.list_pending_cards --batch-size 4`
4. fire sonnet subagent(可 N 路并发,每路 1 batch),按 `tools/cleansing_subagent_prompt.md` 模板,输出 `data/full/<type>/<id>_<name>.yaml`
5. `.venv/bin/python -m tools.apply_cost_judgement` + `.venv/bin/python -m tools.strip_card_yaml --in data/full --out data/cleaned --merge-glossary`

## 关键工具与文件

| 路径 | 作用 |
|---|---|
| `tools/cleansing_subagent_prompt.md` | sonnet subagent 通用 prompt 模板 |
| `tools/cards/fetch.py` | 拉 raw entry_page(按 id/name 过滤) |
| `tools/cards/check_list_sync.py` | 对账 list_ext vs raw entry_page |
| `tools/list_pending_cards.py` | 列 raw - cleaned 差集 + 切 batch |
| `tools/apply_cost_judgement.py` | 应用 user cost icon 判定到 full yaml |
| `tools/strip_card_yaml.py` | full → cleaned + 重建 glossary |
| `data/cost_icons/_judgement.yaml` | user 38 hash → cost type 判定(权威) |
