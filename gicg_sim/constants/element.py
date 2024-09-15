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
