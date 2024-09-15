from enum import Enum


class TargetDescType(Enum):
    # normal 常规
    active = "active"       # 站场角色
    active_next = "active_next"  # 下一个站场角色
    active_prev = "active_prev"  # 上一个站场角色
    inactive = "inactive"   # 所有非站场角色
    # select directly 直接选中
    selected = "selected"   # 选中角色
    # special 特殊规则
    all = "all"             # 所有角色
    none = "none"           # 无


class SideDescType(Enum):
    mine = "mine"           # 己方
    enemy = "enemy"         # 敌方


class TargetType():
    __slots__ = ("target", "side")

    def __init__(self, target: TargetDescType,
                 side: SideDescType = SideDescType.enemy) -> None:
        self.target = target
        self.side = side
