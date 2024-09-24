
from ..cost import Cost
from ._base import BaseEvent


class CostEvent(BaseEvent):
    def __init__(self, cost: Cost) -> None:
        super().__init__()
        self._cost = cost
