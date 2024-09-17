from typing import Dict, Mapping

from ..constants.element import (CostElement, DiceElement, Element,
                                 element2cost, element2dice)
from .dice import DiceState


class Cost:
    def __init__(self, dices: Mapping[CostElement, int], energy: int | None = None) -> None:
        self.dices: Mapping[CostElement, int] = dices
        self.energy: int | None = energy

    def check(self, dices: DiceState, energy: int | None = None) -> bool:
        if energy is not None:
            if self.energy is not None and self.energy < energy:
                return False

        remaining_dices: Dict[DiceElement, int] = {}

        omni_count: int = dices[DiceElement.Omni]

        for element in Element:
            dice_element = element2dice(element)
            cost_element = element2cost(element)

            need_count = self.dices.get(cost_element, 0)
            have_count = dices[dice_element]

            if need_count > have_count + omni_count:
                return False
            elif need_count > have_count:
                omni_count -= need_count - have_count
            elif need_count == have_count:
                pass
            else:
                remaining_dices[dice_element] = have_count - need_count

        matching_cost = self.dices.get(CostElement.Matching, 0)
        for dice_element, count in remaining_dices.items():
            if count >= matching_cost:
                remaining_dices[dice_element] -= matching_cost
                matching_cost = 0
                break
            elif count + omni_count >= matching_cost:
                omni_count -= matching_cost - count
                remaining_dices[dice_element] = 0
                matching_cost = 0
                break

        if matching_cost > 0:
            return False

        any_cost = self.dices.get(CostElement.Any, 0)

        for dice_element, count in remaining_dices.items():
            if count >= any_cost:
                any_cost = 0
                break
            elif count + omni_count >= any_cost:
                omni_count -= any_cost - count
                any_cost = 0
                break

        if any_cost > 0:
            return False

        return True
