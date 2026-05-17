# Sonnet subagent 卡牌 cleansing 任务模板

## 输入

调用方在 prompt 末尾给出 raw 路径列表(每行 1 条 absolute path)。**你的工作 = 把每个 raw 转成 full YAML 写入 `data/full/<type>/<id>_<name>.yaml`。**

## Schema 权威参考

完整 schema:`docs/3_plans/cards/cleansing_schema.md`(必读)。
最佳范例(必读,严格按布局):
- character → `data/full/character/500194_迪希雅.yaml`(标准三技能 + 召唤物 + 天赋)
- character variants → `data/full/character/5359_凝光.yaml`(自行巧局模式)
- action → `data/full/action/500023_老章.yaml`(支援牌)
- monster → `data/full/monster/501447_歼灭特化型机关.yaml`(准备技能)

## 关键规则

1. **raw JSON 结构**:`modules[]` → 每个 module 的 `components[].data` 是 JSON-encoded 字符串,要二次 `json.loads`。
2. **基础信息 module** 给顶层 attr / hp / energy / 攻击。
3. **卡牌技能 module** → skills(普通攻击/元素战技/元素爆发);**召唤物 module** → summons;**天赋牌 module** → talent。
4. **cost 推断**(raw 没显式 cost,从 effect_text + skill 类型常识):
   - 普通攻击:`{<元素>: 1, 无色: 2}`
   - 元素战技:`{<元素>: 3}`
   - 元素爆发:`{<元素>: 3-4}`,具体读 raw_energy 推 energy_delta 负值
   - **行动牌**(七圣召唤多种 cost 结构,raw 不直接区分 same vs any,需按 sub_class + 游戏知识推):
     - 0 cost → `{any: 0}`(简洁,等价 `{same: 0}`)
     - **元素共鸣 N>0 cost** → `{<对应元素>: N}`(如「愈疗之水」=`{水: 1}`)— 元素共鸣的 cost 即对应元素 specific
     - **武器装备牌(标签:武器,N>0)** → `{same: N}`(几乎所有武器都是同色)
     - **圣遗物装备牌(标签:圣遗物,N>0)** → `{same: N}`(全是同色)
     - **角色天赋牌** → 从关联角色元素推:`{<角色元素>: N}`
     - **特技装备牌的 cost**(attached_special / specials 内) → 通常 `{void: N}` 或夜魂值
     - **事件牌 / 支援牌(伙伴/场地/道具)的 N>0 cost** → **不能默认!** 七圣事件牌既有 `{any: N}`(如「最好的伙伴」any:2、「送你一程」any:2)也有 `{same: N}`(如「护法之誓」same:4、「深渊的呼唤」same:2)。
       - **如果 raw 仅给 `["N"]` 没线索**:写 `{any: N}` + `cost_unsure: "事件牌/支援牌 raw 仅 N,无法区分 any/same,默认 any,待 review"`
       - 若 effect / 牌名能推断(如要求"同元素骰")就写 same。
     - 老 monster 等 raw 无显式花费且描述也无线索:用最佳估计 + `cost_unsure`。
   - **`cost_bg_icon_url` 字段**(必填,用于人工 review):从 raw `fe_ext` 字段中提取 `costBgIcon.list[0]` URL(JSON-encoded 字符串,unescape 后是普通 URL),写到 yaml 顶层字段:
     ```yaml
     cost_bg_icon_url: https://uploadstatic.mihoyo.com/...
     ```
     找不到就空字符串。这个字段用于事后人工视觉判定 same vs any。
5. **energy_delta**:普通攻击/战技 `+1`,元素爆发 `-energy`(取消整数,如 `-3`)。
6. **cost 元素 key 用中文**(`风/火/雷/冰/水/草/岩`)+ `无色`/`same`/`any`/`void`。
7. **cost 不确定时**(自行巧局子模式 / 老 monster 不规则):**填一个最佳估计 + 在外层加 `cost_unsure: "<原因>"`**(quote 起来)。**禁止**写 `cost: { unsure: "..." }`(让下游解析失败)。
8. **HTML 完整保留**:`effect_html` 字段 = raw 里那串完整 HTML;`effect_text` = strip 标签 + unescape 后的纯文本(用 `|` block scalar)。
9. **terms 字典**:扫所有 `<span data-type="详情" data-name="...">`,**双重 unescape**(HTML 实体 → HTML → 文本),取冒号前作 key。同名取最长解释。
10. **YAML escape**:含中文 `:` 的字符串值必须 quote 或用 `|` block scalar。
11. **不发明字段**:schema 没列的不加;不确定就 `<field>_unsure: "<原因>"`(兄弟字段,quote)。
12. **禁止 yaml 行内注释 `# ...`**。所有需要保留的备注、推断依据、wiki 笔误说明、未展开 tooltip 等,都用专门字段:
    - 不确定的字段 → `<field>_unsure: "<原因>"`
    - 推断来源/依据 → `<field>_inferred_from: "<依据>"`
    - 数据噪声/wiki 错误 → `<field>_note: "<说明>"`
    - 通用注释 → `_note: "..."` 或 `_notes: ["...", "..."]`
    YAML 注释 `# ...` 在我们的 apply / strip pipeline 中走 yaml.safe_load + safe_dump 会被无声丢失,**任何信息丢失都会重现 cost icon 错配那种 debug 噩梦**。
12. **保留所有 raw 信息**:icon / icon_url / version / header_img_url / desc / raw_life / raw_energy 全保。

## attr 分号拆分

raw 的 attr value 形如 `["：须弥；镀金旅团"]`(开头冒号 + 中间分号),拆分后:`阵营: [须弥, 镀金旅团]`。

## skill type 映射

- 普通攻击 → `type: 普通攻击`
- 元素战技 → `type: 元素战技`
- 元素爆发 → `type: 元素爆发`
- 准备技能(如焚落踢) → `type: 普通攻击`,加 `sub_type: 准备技能`
- 被动 → `type: 被动`

## variants(多模式)

仅当 raw 中 tab_id 切换确实给出**实际不同**的技能/数值时才用 `variants[]`(如自行巧局 + 攻击力倍数伤害的凝光、HP 不同的诺艾尔)。**raw tab 是空模板时**(无 life/energy/技能数据,如迪奥娜 / 柯莱):用 `variants: [{mode: 自行巧局, unsure: "raw 中为空模板"}]` 或干脆 omit。

## 写入位置

每张 1 个 YAML:`data/full/<type>/<id>_<name>.yaml`(filename 与 raw 同名,扩展名换 yaml)。

## 完成后

打印一行:`OK: <N> 个文件写入 data/full/`。
若有任何 raw 解析失败,打印 `FAIL: <id> <reason>` 并跳过那张(不阻塞其它)。

不写测试,不 commit,不改 cleaned/(那是 Python 工具的活)。
