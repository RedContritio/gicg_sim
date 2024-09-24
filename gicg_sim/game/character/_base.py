from typing import List, MutableSequence

from ...constants.element import DamageElement, Element
from ...constants.id import CharacterID
from ...constants.target import TargetType
from ..event._base import BaseEvent
from ..event.damage import DamageEvent
from ..skill import BaseSkill
from ..state import State


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

    def _set_skills(self, skills: List[BaseSkill]):
        self.skills = skills

    def _make_damage(self, target: TargetType,
                     element: DamageElement, value: int):
        damage_event = DamageEvent(self.id, target, element, value)
        return damage_event

    def use_skill(self, state: State,
                  events: MutableSequence[BaseEvent], skill_name: str) -> None:
        for skill in self.skills:
            if skill.name == skill_name:
                return skill.apply(state, events)
        raise ValueError(
            f"Skill {skill_name} not found in character {
                self.name}")
