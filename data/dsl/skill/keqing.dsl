# 刻晴 1403 - 技能 DSL（纯 DSL 脚本）

character 刻晴 1403

skill 云来剑法 14031
  type normal_attack
  cost electro 1 any 2 energy 0
  damage physical 2 opponent_active

skill 星斗归位 14032
  type elemental_skill
  cost electro 3 energy 0
  damage elemental electro 3 opponent_active
  add_card_to_hand lightning_stiletto 1

skill 天街巡游 14033
  type elemental_burst
  cost electro 4 energy 3
  damage elemental electro 4 opponent_active
  damage piercing 3 all_opponent_backend
