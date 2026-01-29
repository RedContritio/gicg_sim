# 迪卢克 1301 - 技能 DSL（纯 DSL 脚本）
# 逆焰之刃：每回合第三次使用本技能时伤害+2（token 计数 + hook 改伤）

character 迪卢克 1301

skill 淬炼之剑 13011
  type normal_attack
  cost pyro 1 any 2 energy 0
  damage physical 2 opponent_active

skill 逆焰之刃 13012
  type elemental_skill
  cost pyro 3 energy 0
  damage elemental pyro 3 opponent_active
  on_use: token_inc self diluc_skill_use_count ttl round
  hook on damage elemental_skill pyro:
    if token_value self diluc_skill_use_count == 3:
      modify damage +2
      remove self diluc_skill_use_count

skill 黎明 13013
  type elemental_burst
  cost pyro 4 energy 3
  damage elemental pyro 8 opponent_active
  add_status pyro_infusion 0 2 self_active
