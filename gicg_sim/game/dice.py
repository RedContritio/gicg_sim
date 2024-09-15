from typing import Dict, Optional

from ..constants.element import DiceElement


class DiceState:
    __slots__ = ("_data",)

    def __init__(self, init_dict: Optional[Dict[DiceElement, int]] = None) -> None:
        self._data: Dict[DiceElement, int] = {
            DiceElement.Pyro: 0,
            DiceElement.Hydro: 0,
            DiceElement.Anemo: 0,
            DiceElement.Electro: 0,
            DiceElement.Dendro: 0,
            DiceElement.Cryo: 0,
            DiceElement.Geo: 0,
            DiceElement.Omni: 0
        }

        if init_dict is not None:
            for key, value in init_dict.items():
                self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value
