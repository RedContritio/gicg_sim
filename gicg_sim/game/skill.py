from typing import Mapping, MutableSequence

from ..constants.element import CostElement, DamageElement
from ..constants.skill import SkillType
from .cost import Cost
from .event._base import BaseEvent
from .event.cost import CostEvent
from .event.skill import SkillEvent
from .state import State


class BaseSkill():
    def __init__(self,
                 name: str,
                 element: DamageElement,
                 cost: Cost,
                 skill_type: SkillType = SkillType.Undefined,
                 damage_count: int | None = None) -> None:
        self.name = name
        self.element = element
        self.cost = cost
        self.skill_type = skill_type
        self.damage_count: int | None = damage_count

    def apply(self, state: State,
              event_queue: MutableSequence[BaseEvent]) -> None:
        # 先花掉骰子，再结算技能
        event_queue.append(
            CostEvent(self.cost)
        )
        event_queue.append(
            SkillEvent(
                self.name,
                SkillType.Normal_Attack,
                state.current_character)
        )


class Skill_NormalAttack(BaseSkill):
    def __init__(self,
                 name: str,
                 element: DamageElement,
                 cost: Cost,
                 damage_count: int | None = None) -> None:
        super().__init__(name, element, cost,
                         skill_type=SkillType.Normal_Attack,
                         damage_count=damage_count,)


class Skill_ElementalSkill(BaseSkill):
    def __init__(self,
                 name: str,
                 element: DamageElement,
                 cost: Cost,
                 damage_count: int | None = None) -> None:
        super().__init__(name, element, cost,
                         skill_type=SkillType.Elemental_Skill,
                         damage_count=damage_count,)


class Skill_ElementalBurst(BaseSkill):
    def __init__(self,
                 name: str,
                 element: DamageElement,
                 cost: Cost,
                 damage_count: int | None = None) -> None:
        super().__init__(name, element, cost,
                         skill_type=SkillType.Elemental_Burst,
                         damage_count=damage_count,)


def make_standard_dices_cost(element: CostElement | None, element_dice_count: int,
                             matching_dice_count: int, any_dice_count: int) -> Mapping[CostElement, int]:
    if element is None:
        if element_dice_count != 0:
            raise ValueError("element_dice_count must be 0 if element is None")
        return {
            CostElement.Matching: matching_dice_count,
            CostElement.Any: any_dice_count,
        }

    return {
        element: element_dice_count,
        CostElement.Matching: matching_dice_count,
        CostElement.Any: any_dice_count,
    }


def make_standard_cost(element: CostElement | None, element_dice_count: int,
                       match_dice_count: int, any_dice_count: int, energy: int | None = None) -> Cost:

    dices = make_standard_dices_cost(
        element,
        element_dice_count,
        match_dice_count,
        any_dice_count)
    if energy is None or energy == 0:
        return Cost(dices)
    return Cost(dices, energy)


def make_normal_attack_cost(element: CostElement | None = None,
                            element_dice_count: int = 1, any_dice_count: int = 2) -> Cost:
    return make_standard_cost(element, element_dice_count, 0, any_dice_count)


def make_elemental_skill_cost(element: CostElement,
                              element_dice_count: int = 3) -> Cost:
    return make_standard_cost(element, element_dice_count, 0, 0)


def make_elemental_burst_cost(
        element: CostElement, element_dice_count: int = 3, energy: int | None = 2) -> Cost:
    return make_standard_cost(element, element_dice_count, 0, 0, energy=energy)
