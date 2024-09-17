from typing import MutableSequence

from ...constants.element import DamageElement, Element
from ...constants.id import CharacterID
from ...constants.target import TargetType
from ..event._base import BaseEvent
from ..event.damage import DamageEvent


class Character:
    def __init__(self,
                 name: str,
                 max_hp: int,
                 max_energy: int,
                 element: Element,
                 id: CharacterID) -> None:
        self.name = name
        self.max_hp = max_hp
        self.max_energy = max_energy
        self.element = element
        self.id = id

    def _make_damage(self, target: TargetType, element: DamageElement, value: int):
        damage_event = DamageEvent(self.id, target, element, value)
        return damage_event

    def normal_attack(self, events: MutableSequence[BaseEvent]):
        raise NotImplementedError

    def elemental_skill(self, events: MutableSequence[BaseEvent]):
        raise NotImplementedError

    def elemental_burst(self, events: MutableSequence[BaseEvent]):
        raise NotImplementedError

    def use_skill(self, events: MutableSequence[BaseEvent], skill):
        raise NotImplementedError
