from collections import deque

from ...constants.element import DamageElement
from ..cost import Cost
from ..event._base import BaseEvent


class BaseSkill:
    def __init__(self, name: str, element: DamageElement, cost: Cost) -> None:
        self.name = name
        self.element = element
        self.cost = cost

    def apply(self, event_queue: deque[BaseEvent]) -> None:
        raise NotImplementedError()
