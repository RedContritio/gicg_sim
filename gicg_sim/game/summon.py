from ._base import StandaloneToken


class SummonToken(StandaloneToken):
    def __init__(self, name, life):
        super().__init__(name, life, "summon")
