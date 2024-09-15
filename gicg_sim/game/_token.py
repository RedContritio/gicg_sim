class _BaseToken():
    def __init__(self, name):
        self.name = name


class StandaloneToken(_BaseToken):
    def __init__(self, name, life, type):
        super().__init__(name)
        self.life = life
