# 迪奥娜 1102 - 技能 DSL（纯 DSL 脚本）

character 迪奥娜 1102

skill 猎人射术 11021
  type normal_attack
  cost cryo 1 any 2 energy 0
  damage physical 2 opponent_active

skill 猫爪冻冻 11022
  type elemental_skill
  cost cryo 3 energy 0
  damage elemental cryo 2 opponent_active
  add_status cat_paw_shield 2 2 self_active

skill 最烈特调 11023
  type elemental_burst
  cost cryo 3 energy 3
  damage elemental cryo 1 opponent_active
  heal 2 self_active
  summon wine_mist_field 2 1
