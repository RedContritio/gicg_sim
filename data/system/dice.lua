-- system/dice.lua — elemental dice mechanic
--
-- Each round, each player rolls DICE_ROLL_COUNT dice. Each dice is
-- independently sampled uniformly over 8 colors (7 elements + omni).
-- Unused dice are discarded at round end.
--
-- Dice are stored as 8 PerPlayer counters tagged Tag.Dice. The
-- counter names (dice_fire..dice_omni) are resolved by the Go engine
-- into Ruleset.DiceCounterIDs for fast access from RollDice / cost
-- affordability checks.
--
-- Counter names MUST match interp.DiceCounterNames — any rename here
-- requires a matching change there.

local DICE_ROLL_COUNT = 8

local dice_fire    = declare_counter("dice_fire",    Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_ice     = declare_counter("dice_ice",     Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_water   = declare_counter("dice_water",   Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_electro = declare_counter("dice_electro", Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_geo     = declare_counter("dice_geo",     Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_anemo   = declare_counter("dice_anemo",   Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_dendro  = declare_counter("dice_dendro",  Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })
local dice_omni    = declare_counter("dice_omni",    Scope.PerPlayer, 0, { min = 0, max = 16, tag = Tag.Dice })

-- Roll fresh dice at round start, for each player.
on_round_start(function(ctx)
  roll_dice(context_player(), DICE_ROLL_COUNT)
end)

-- Discard unused dice at round end.
on_round_end(function(ctx)
  clear_dice_pool(context_player())
end)
