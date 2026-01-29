# 魔偶剑鬼 2501 - 技能 DSL（纯 DSL 脚本）
# 双属性示例：风 + 冰（孤风刀势 / 霜驰影突 分属不同元素消耗）

character 魔偶剑鬼 2501

skill 一文字 25011
  type normal_attack
  cost anemo 1 any 2 energy 0
  damage physical 2 opponent_active

skill 孤风刀势 25012
  type elemental_skill
  cost anemo 3 energy 0
  summon sword_shadow_wind 2 1

skill 霜驰影突 25013
  type elemental_skill
  cost cryo 3 energy 0
  summon sword_shadow_frost 2 1

skill 机巧伪天狗抄 25014
  type elemental_burst
  cost anemo 3 energy 3
  damage elemental anemo 4 opponent_active
  trigger_all sword_shadow
