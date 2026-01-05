from typing import Dict, List, Optional

from ..constants.element import DiceElement


class DiceState:
    __slots__ = ("_data",)

    def __init__(
            self, init_dict: Optional[Dict[DiceElement, int]] = None) -> None:
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

    def __getitem__(self, key: DiceElement) -> int:
        return self._data[key]

    def __setitem__(self, key: DiceElement, value: int):
        self._data[key] = value

    def total(self) -> int:
        """返回骰子总数"""
        return sum(self._data.values())

    def add(self, element: DiceElement, count: int = 1):
        """添加骰子"""
        self._data[element] += count

    def remove(self, element: DiceElement, count: int = 1) -> bool:
        """移除骰子，成功返回True"""
        if self._data[element] >= count:
            self._data[element] -= count
            return True
        return False

    def clear(self):
        """清空所有骰子"""
        for key in self._data:
            self._data[key] = 0

    def get_non_matching_elements(self, exclude_element: DiceElement) -> List[DiceElement]:
        """获取所有非指定元素的骰子元素类型"""
        return [e for e in DiceElement if e != exclude_element and e != DiceElement.Omni]

    def copy(self) -> 'DiceState':
        """复制骰子状态"""
        new_state = DiceState()
        for key, value in self._data.items():
            new_state[key] = value
        return new_state
