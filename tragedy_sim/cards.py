"""Base decks checked against resources/data.xml and the implemented ruleset sheets."""

from dataclasses import dataclass

PROTAGONISTS = ("a", "b", "c")
ACTORS = ("m", *PROTAGONISTS)
ACTOR_NAMES = {"m": "剧作家", "a": "主人公 A", "b": "主人公 B", "c": "主人公 C"}
LOCATIONS = {"hospital": "医院", "shrine": "神社", "city": "都市", "school": "学校"}
COORDS = {"hospital": (0, 0), "shrine": (1, 0), "city": (0, 1), "school": (1, 1)}
MOVES = {"horizontal": (1, 0), "vertical": (0, 1), "diagonal": (1, 1)}
COUNTER_NAMES = {"paranoia": "不安", "goodwill": "友好", "intrigue": "密谋"}


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    effect: str
    amount: int = 0
    once_per_loop: bool = False


MASTER_CARDS = (
    Card("p1a", "不安 +1（第1张）", "paranoia", 1),
    Card("p1b", "不安 +1（第2张）", "paranoia", 1),
    Card("p-1", "不安 -1", "paranoia", -1),
    Card("fp", "禁止不安", "forbid_paranoia"),
    Card("fg", "禁止友好", "forbid_goodwill"),
    Card("i1", "密谋 +1", "intrigue", 1),
    Card("i2", "密谋 +2", "intrigue", 2, True),
    Card("h", "横向移动", "horizontal"),
    Card("v", "纵向移动", "vertical"),
    Card("d", "斜向移动", "diagonal", once_per_loop=True),
)
HERO_CARDS = (
    Card("p1", "不安 +1", "paranoia", 1),
    Card("p-1", "不安 -1", "paranoia", -1, True),
    Card("g1", "友好 +1", "goodwill", 1),
    Card("g2", "友好 +2", "goodwill", 2, True),
    Card("fi", "禁止密谋", "forbid_intrigue"),
    Card("h", "横向移动", "horizontal"),
    Card("v", "纵向移动", "vertical"),
    Card("fm", "禁止移动", "forbid_movement", once_per_loop=True),
)


def deck(actor: str) -> dict[str, Card]:
    if actor not in ACTORS:
        raise ValueError("玩家必须是 m / a / b / c")
    return {card.id: card for card in (MASTER_CARDS if actor == "m" else HERO_CARDS)}
