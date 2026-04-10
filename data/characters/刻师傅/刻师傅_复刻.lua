local ref = declare_card("复刻", 3, { battle_action = true })
local 刻师傅 = get_char("刻师傅")
local 复刻_mode = get_counter("复刻_mode", Scope.Self)
local 复刻_in_hand = get_counter("复刻_in_hand", Scope.PerPlayer)
local 刻印 = get_skill(刻师傅, "刻印")
local frozen = get_counter("frozen", Scope.PerChar)

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if not 刻师傅:alive() then
    ctx.playable = false
    return
  end
  if frozen:get_at(刻师傅:owner_player(), 刻师傅:owner_char()) > 0 then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  复刻_in_hand:set(0)
  set_active_char(Player.Own, 刻师傅:owner_char())
  复刻_mode:set(1)
  invoke_skill(刻印)
end)
