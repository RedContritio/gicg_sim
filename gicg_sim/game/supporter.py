from ._token import StandaloneToken


class SupporterToken(StandaloneToken):
    def __init__(self, name, life):
        super().__init__(name, life, "supporter")
