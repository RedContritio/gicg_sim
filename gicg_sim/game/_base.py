class BaseToken():
    def __init__(self, name):
        self.name = name


class StandaloneToken(BaseToken):
    def __init__(self, name, life, type):
        super().__init__(name)
        self.life = life
