# 甘雨 1101 - 技能 DSL（纯 DSL 脚本）

character 甘雨 1101

skill 流天射术 11011
  type normal_attack
  cost cryo 1 any 2 energy 0
  damage physical 2 opponent_active

skill 山泽麟迹 11012
  type elemental_skill
  cost cryo 3 energy 0
  damage elemental cryo 1 opponent_active
  summon ice_lotus 2 1

skill 霜华矢 11013
  type normal_attack
  cost cryo 5 energy 0
  damage elemental cryo 2 opponent_active
  damage piercing 2 all_opponent_backend

skill 降众天华 11014
  type elemental_burst
  cost cryo 3 energy 3
  damage elemental cryo 2 opponent_active
  damage piercing 1 all_opponent_backend
  summon ice_orb 2 1
