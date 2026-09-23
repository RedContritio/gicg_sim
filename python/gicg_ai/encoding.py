from collections.abc import Iterable

import numpy as np

PHASES = ["select_active", "redraw", "roll", "action", "finished"]
ELEMENTS = [
    "physical",
    "cryo",
    "hydro",
    "pyro",
    "electro",
    "anemo",
    "geo",
    "dendro",
    "piercing",
]
REACTIONS = [
    "vaporize",
    "melt",
    "overloaded",
    "superconduct",
    "electro_charged",
    "frozen",
    "swirl",
    "crystallize",
    "burning",
    "bloom",
    "quicken",
    "shatter",
]
ACTION_KINDS = ["choose", "redraw", "reroll", "skill", "switch", "card", "tune", "end"]
DICE = ["cryo", "hydro", "pyro", "electro", "anemo", "geo", "dendro", "omni"]


class ObservationEncoder:
    def __init__(self, rules: dict, team_size: int, deck_size: int):
        self.team_size = team_size
        self.deck_size = deck_size
        self.characters = [value["id"] for value in rules["characters"]]
        self.cards = [value["id"] for value in rules["cards"]]
        self.modifiers = [value["id"] for value in rules["modifiers"]]
        self.character_index = index_by_id(self.characters)
        self.card_index = index_by_id(self.cards)
        self.modifier_index = index_by_id(self.modifiers)
        self.character_definitions = definitions_by_id(rules["characters"])
        self.modifier_definitions = definitions_by_id(rules["modifiers"])
        self.character_counters = maximum_counter_count(rules["characters"])
        self.modifier_counters = maximum_counter_count(rules["modifiers"])
        self.modifier_width = 1 + self.modifier_counters
        self.modifier_size = len(self.modifiers) * self.modifier_width
        self.character_size = (
            len(self.characters) + self.character_counters + len(ELEMENTS) + 1 + self.modifier_size
        )
        self.player_size = (
            team_size
            + len(DICE)
            + 5
            + 3 * len(self.cards)
            + team_size * self.character_size
            + 3 * self.modifier_size
        )
        self.size = len(PHASES) + 4 + len(REACTIONS) + 2 * self.player_size

    def encode(self, state: dict, viewer: int) -> np.ndarray:
        values = one_hot(PHASES, state["phase"])
        values.extend(
            [
                clipped(state["round"], 20),
                float(state["turn"] == viewer),
                float(state["turn"] != viewer),
                clipped(len(state["decision"]["options"]) if state["decision"] else 0, 8),
            ]
        )
        reaction = state["last_reaction"]
        values.extend(one_hot(REACTIONS, reaction["kind"] if reaction else None))
        for player in (viewer, 1 - viewer):
            values.extend(self._player(state["players"][player], player == viewer))
        observation = np.asarray(values, dtype=np.float32)
        if observation.shape != (self.size,):
            raise RuntimeError(f"observation shape {observation.shape} does not match {self.size}")
        return observation

    def _player(self, player: dict, visible_hand: bool) -> list[float]:
        values = one_hot(range(self.team_size), player["active"])
        values.extend(clipped(value, 16) for value in player["dice"])
        values.extend(
            [
                clipped(player["rerolls"], 4),
                clipped(len(player["deck"]), self.deck_size),
                clipped(len(player["hand"]), self.deck_size),
                clipped(len(player["discard"]), self.deck_size),
                float(player["ended"]),
            ]
        )
        values.extend(self._cards(player["deck"] if visible_hand else []))
        values.extend(self._cards(player["hand"] if visible_hand else []))
        values.extend(self._cards(player["discard"]))
        for character in player["characters"]:
            values.extend(self._character(character))
        for zone in ("combat", "summons", "supports"):
            values.extend(self._modifier_vector(player[zone]))
        return values

    def _cards(self, cards: Iterable[str]) -> list[float]:
        values = [0.0] * len(self.cards)
        for card in cards:
            values[self.card_index[card]] += 1 / self.deck_size
        return values

    def _character(self, character: dict) -> list[float]:
        values = one_hot(self.characters, character["definition"])
        definition = self.character_definitions[character["definition"]]
        values.extend(
            normalized_counters(character["counters"], definition, self.character_counters)
        )
        auras = set(character["auras"])
        values.extend(float(element in auras) for element in ELEMENTS)
        values.append(float(character["satiated"]))
        values.extend(self._modifier_vector(character["modifiers"]))
        return values

    def _modifier_vector(self, modifiers: list[dict]) -> list[float]:
        values = [0.0] * self.modifier_size
        for modifier in modifiers:
            definition = self.modifier_definitions[modifier["definition"]]
            start = self.modifier_index[modifier["definition"]] * self.modifier_width
            values[start] = min(1.0, values[start] + 0.25)
            counters = normalized_counters(modifier["counters"], definition, self.modifier_counters)
            for index, value in enumerate(counters, start + 1):
                values[index] = max(values[index], value)
        return values


class ActionEncoder:
    def __init__(self, rules: dict):
        self.characters = [value["id"] for value in rules["characters"]]
        self.cards = [value["id"] for value in rules["cards"]]
        self.skills = [
            (character["id"], action["id"])
            for character in rules["characters"]
            for action in character["actions"]
        ]
        self.character_index = index_by_id(self.characters)
        self.card_index = index_by_id(self.cards)
        self.skill_index = {value: index for index, value in enumerate(self.skills)}
        self.kind_start = 0
        self.skill_start = len(ACTION_KINDS)
        self.card_start = self.skill_start + len(self.skills)
        self.character_start = self.card_start + len(self.cards)
        self.die_start = self.character_start + len(self.characters)
        self.payment_start = self.die_start + len(DICE)
        self.scalar_start = self.payment_start + len(DICE)
        self.size = self.scalar_start + 3

    def encode(self, action: dict, state: dict) -> np.ndarray:
        values = np.zeros(self.size, dtype=np.float32)
        kind = action["kind"]
        values[self.kind_start + ACTION_KINDS.index(kind)] = 1
        controller = state["decision"]["player"] if state["decision"] else state["turn"]
        player = state["players"][controller]
        self._encode_subject(values, action, state, player)
        payment = action.get("payment", [0] * len(DICE))
        values[self.payment_start : self.payment_start + len(DICE)] = np.asarray(payment) / 16
        self._encode_scalars(values, action, state, player)
        return values

    def _encode_subject(self, values: np.ndarray, action: dict, state: dict, player: dict) -> None:
        kind = action["kind"]
        if kind == "skill":
            character = player["characters"][player["active"]]["definition"]
            values[self.skill_start + self.skill_index[(character, action["action"])]] = 1
        if kind in {"card", "tune"}:
            card = player["hand"][action["hand"]]
            values[self.card_start + self.card_index[card]] = 1
        if kind == "switch":
            character = player["characters"][action["slot"]]["definition"]
            values[self.character_start + self.character_index[character]] = 1
        if kind == "choose":
            self._encode_choice(values, action, state)
        if kind == "tune":
            values[self.die_start + DICE.index(action["die"])] = 1

    def _encode_choice(self, values: np.ndarray, action: dict, state: dict) -> None:
        decision = state["decision"]
        option = decision["options"][action["option"]]["id"]
        parts = option.split(":")
        slot = (
            int(parts[-1]) if parts[0] == "character" else int(option) if option.isdigit() else None
        )
        if slot is None or slot >= len(state["players"][decision["player"]]["characters"]):
            return
        character = state["players"][decision["player"]]["characters"][slot]["definition"]
        values[self.character_start + self.character_index[character]] = 1

    def _encode_scalars(self, values: np.ndarray, action: dict, state: dict, player: dict) -> None:
        kind = action["kind"]
        if kind == "choose":
            values[self.scalar_start] = clipped(action["option"], len(state["decision"]["options"]))
        elif kind == "redraw":
            values[self.scalar_start] = clipped(len(action["selected"]), len(player["hand"]))
        elif kind in {"card", "tune"}:
            values[self.scalar_start] = clipped(action["hand"], len(player["hand"]))
        elif kind == "switch":
            values[self.scalar_start] = clipped(action["slot"], len(player["characters"]))
        values[self.scalar_start + 1] = clipped(sum(action.get("payment", [])), 16)
        values[self.scalar_start + 2] = float(kind in {"skill", "switch", "card"})


def normalized_counters(values: list[int], definition: dict, width: int) -> list[float]:
    output = [0.0] * width
    fields = definition["counters"]["fields"]
    for index, (value, field) in enumerate(zip(values, fields, strict=True)):
        span = field["max"] - field["min"]
        output[index] = (value - field["min"]) / span if span else 0.0
    return output


def definitions_by_id(values: list[dict]) -> dict[str, dict]:
    return {value["id"]: value for value in values}


def index_by_id(values: list[str]) -> dict[str, int]:
    return {value: index for index, value in enumerate(values)}


def maximum_counter_count(values: list[dict]) -> int:
    return max((len(value["counters"]["fields"]) for value in values), default=0)


def one_hot(values: Iterable, selected: object) -> list[float]:
    return [float(value == selected) for value in values]


def clipped(value: int, maximum: int) -> float:
    return min(value / max(maximum, 1), 1.0)
