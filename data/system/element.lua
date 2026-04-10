-- system/element.lua

local attached_fire    = declare_counter("attached_fire",    Scope.PerChar, 0, { min = 0, max = 1 })
local attached_water   = declare_counter("attached_water",   Scope.PerChar, 0, { min = 0, max = 1 })
local attached_ice     = declare_counter("attached_ice",     Scope.PerChar, 0, { min = 0, max = 1 })
local attached_electro = declare_counter("attached_electro", Scope.PerChar, 0, { min = 0, max = 1 })
local frozen           = declare_counter("frozen",           Scope.PerChar, 0, { min = 0, max = 10 })
