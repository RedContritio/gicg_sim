# 琴 1502 - 技能 DSL（纯 DSL 脚本）

character 琴 1502

skill 西风剑术 15021
  type normal_attack
  cost anemo 1 any 2 energy 0
  damage physical 2 opponent_active

skill 风压剑 15022
  type elemental_skill
  cost anemo 3 energy 0
  damage elemental anemo 3 opponent_active
  switch_opponent next

skill 蒲公英之风 15023
  type elemental_burst
  cost anemo 4 energy 2
  heal 2 all_self
  summon dandelion_field 2 1
