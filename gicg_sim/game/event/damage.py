from ...constants.element import DamageElement
from ...constants.id import CharacterID
from ...constants.target import TargetType
from ._base import BaseEvent


class DamageEvent(BaseEvent):
    def __init__(self, source: CharacterID,
                 target: TargetType, type: DamageElement, value: int):
        self.source = source
        self.target = target
        self.type = type
        self.value = value
