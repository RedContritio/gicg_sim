local ref = declare_card("复刻", { dices = { electro = 3 } }, { battle_action = true })
local 刻师傅 = get_char("刻师傅")
local my_player = 刻师傅:owner_player()
local my_char = 刻师傅:owner_char()

local 刻印 = get_skill(刻师傅, "刻印")
local frozen = get_counter("冻结", Scope.PerChar)

on_action_check(function(ctx)
  if ctx.actor_player ~= my_player then return end
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if not 刻师傅:alive() then
    ctx.playable = false
    return
  end
  if frozen:get_at(my_player, my_char) > 0 then
    ctx.playable = false
  end
end)

-- 刻印使用后生成复刻手牌（如果手牌中还没有，且不是复刻触发的）
on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 刻印 then return end
  if ctx.source == Source.Card then return end
  if not has_card_in_own_hand(ref) then
    add_card(ref, Zone.Hand)
  end
end)

on_card_play(function(ctx)
  if ctx.actor_player ~= my_player then return end
  if ctx.card_ref ~= ref then return end
  set_active_char(Player.Own, my_char)
  invoke_skill(刻印)
end)
