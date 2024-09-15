from typing import MutableSequence

from ..constants.element import Element
from .event import BaseEvent


class Character:
    def __init__(self,
                 name: str,
                 max_hp: int,
                 max_energy: int,
                 element: Element) -> None:
        self.name = name
        self.max_hp = max_hp
        self.max_energy = max_energy
        self.element = element

    def normal_attack(self):
        raise NotImplementedError

    def elemental_skill(self):
        raise NotImplementedError

    def elemental_burst(self):
        raise NotImplementedError

    def use_skill(self, events: MutableSequence[BaseEvent], skill):
        raise NotImplementedError


class Khaenriahn(Character):
    '''
    坎瑞亚人（测试用角色）
    '''

    def __init__(self) -> None:
        super().__init__("Khaenriahn", 10, 2, Element.Pyro)

    def normal_attack(self):
        print("Khaenriahn normal attack")

    def elemental_skill(self):
        print("Khaenriahn elemental skill")

    def elemental_burst(self):
        print("Khaenriahn elemental burst")

    def use_skill(self, skill):
        if skill == "normal_attack":
            self.normal_attack()
        elif skill == "elemental_skill":
            self.elemental_skill()
        elif skill == "elemental_burst":
            self.elemental_burst()
        else:
            print("Invalid skill")
