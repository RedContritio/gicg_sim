local TARGET_OWN = 1
local TARGET_ENEMY = 2

local _cards = {}
local _next_card_ref = 1

function declare_card(name, ap_cost, opts)
  opts = opts or {}
  local battle_action = opts.battle_action
  if battle_action == nil then battle_action = false end
  local target = opts.target

  local existing = _cards[name]
  if existing then
    if existing.ap_cost ~= ap_cost or existing.battle_action ~= battle_action then
      error("declare_card conflict for '" .. name .. "': params differ", 2)
    end
    return existing.ref
  end

  local ref = _next_card_ref
  _next_card_ref = _next_card_ref + 1

  local target_mode = 0
  if target == "own" then target_mode = TARGET_OWN
  elseif target == "enemy" then target_mode = TARGET_ENEMY
  end

  _cards[name] = { ref = ref, ap_cost = ap_cost, battle_action = battle_action, target_mode = target_mode }

  on_action_check(function(ctx)
    if ctx.action_kind ~= ActionKind.Card then return end
    if ctx.card_ref ~= ref then return end
  end)

  on_action_prepare(function(ctx)
    if ctx.action_kind ~= ActionKind.Card then return end
    if ctx.card_ref ~= ref then return end
    ctx.ap_cost = ap_cost
    ctx.battle_action = battle_action
    if target_mode > 0 then
      ctx.need_target = true
      ctx.target_mode = target_mode
    end
  end)

  return ref
end

on_card_play(100, function(ctx)
  _current_card_target_player = ctx.target_player
  _current_card_target_char = ctx.target_char
end)

function get_card(name)
  local c = _cards[name]
  if not c then error("unknown card: " .. name, 2) end
  return c.ref
end

function add_card(card_ref, zone, player)
  player = player or Player.Own
  _add_card(card_ref, zone, _resolve_p(player))
end
