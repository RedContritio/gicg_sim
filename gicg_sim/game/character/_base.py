from typing import List, MutableSequence, Optional

from ...constants.element import DamageElement, Element
from ...constants.id import CharacterID
from ...constants.skill import SkillType
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
        # 运行时状态
        self.current_hp = max_hp
        self.current_energy = 0

    def take_damage(self, damage: int) -> int:
        """受到伤害，返回实际受到的伤害值"""
        actual_damage = min(damage, self.current_hp)
        self.current_hp -= actual_damage
        return actual_damage

    def is_defeated(self) -> bool:
        """是否被击败"""
        return self.current_hp <= 0

    def _set_skills(self, skills: List[BaseSkill]):
        self.skills = skills

    @property
    def normal_attack(self) -> Optional[BaseSkill]:
        """获取普通攻击技能"""
        for skill in self.skills:
            if skill.skill_type == SkillType.Normal_Attack:
                return skill
        return None

    def get_skill_by_name(self, name: str) -> Optional[BaseSkill]:
        """通过名称获取技能"""
        for skill in self.skills:
            if skill.name == name:
                return skill
        return None

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
