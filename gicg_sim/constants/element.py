from enum import Enum


class Element(Enum):
    Pyro = "Pyro"        # 火
    Hydro = "Hydro"      # 水
    Anemo = "Anemo"      # 风
    Electro = "Electro"  # 雷
    Dendro = "Dendro"    # 草
    Cryo = "Cryo"        # 冰
    Geo = "Geo"          # 岩


class DiceElement(Enum):
    Pyro = "Pyro"        # 火
    Hydro = "Hydro"      # 水
    Anemo = "Anemo"      # 风
    Electro = "Electro"  # 雷
    Dendro = "Dendro"    # 草
    Cryo = "Cryo"        # 冰
    Geo = "Geo"          # 岩
    Omni = "Omni"        # 万能


class CostElement(Enum):
    Pyro = "Pyro"        # 火
    Hydro = "Hydro"      # 水
    Anemo = "Anemo"      # 风
    Electro = "Electro"  # 雷
    Dendro = "Dendro"    # 草
    Cryo = "Cryo"        # 冰
    Geo = "Geo"          # 岩
    Matching = "Matching"  # 匹配
    Any = "Any"            # 任意


_element_aux_backward_dict = {v: k for k, v in Element.__members__.items()}
_dice_element_aux_backward_dict = {v: k for k, v in DiceElement.__members__.items()}
_cost_element_aux_backward_dict = {v: k for k, v in CostElement.__members__.items()}


def element2cost(element: Element) -> CostElement:
    name = _element_aux_backward_dict.get(element)
    return CostElement(name)


def element2dice(element: Element) -> DiceElement:
    name = _element_aux_backward_dict.get(element)
    return DiceElement(name)


class DamageElement(Enum):
    Pyro = "Pyro"        # 火
    Hydro = "Hydro"      # 水
    Anemo = "Anemo"      # 风
    Electro = "Electro"  # 雷
    Dendro = "Dendro"    # 草
    Cryo = "Cryo"        # 冰
    Geo = "Geo"          # 岩
    Physical = "Physical"  # 物理
    Piercing = "Piercing"  # 穿透
