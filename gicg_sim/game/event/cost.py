from typing import Dict

from ...constants.element import Element
from ._base import BaseEvent


class CostEvent(BaseEvent):
    def __init__(self) -> None:
        super().__init__()
        self.dice: Dict[Element, int] = {}
