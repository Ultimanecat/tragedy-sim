"""Base decks checked against resources/data.xml and the implemented ruleset sheets."""

from dataclasses import dataclass

PROTAGONISTS = ("a", "b", "c")
ACTORS = ("m", *PROTAGONISTS)
ACTOR_NAMES = {"m": "剧作家", "a": "主人公 A", "b": "主人公 B", "c": "主人公 C"}
LOCATIONS = {"hospital": "医院", "shrine": "神社", "city": "都市", "school": "学校"}
COORDS = {"hospital": (0, 0), "shrine": (1, 0), "city": (0, 1), "school": (1, 1)}
MOVES = {"horizontal": (1, 0), "vertical": (0, 1), "diagonal": (1, 1)}
COUNTER_NAMES = {"paranoia": "不安", "goodwill": "友好", "intrigue": "密谋",
                 "hope": "希望", "despair": "绝望"}
STANDARD_COUNTERS = ("paranoia", "goodwill", "intrigue")


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

AHR_MASTER_CARDS = (
    Card("ahr_g1", "友好 +1", "goodwill", 1),
    Card("ahr_d1", "绝望 +1（第1轮回）", "despair", 1, True),
)
AHR_HERO_CARDS = (Card("ahr_p2", "不安 +2", "paranoia", 2, True),
                  Card("ahr_h1", "希望 +1", "hope", 1, True))


def deck(actor: str, module: str | None = None) -> dict[str, Card]:
    if actor not in ACTORS:
        raise ValueError("玩家必须是 m / a / b / c")
    cards = MASTER_CARDS if actor == "m" else HERO_CARDS
    if module == "AHR":
        cards += AHR_MASTER_CARDS if actor == "m" else AHR_HERO_CARDS
    elif module == "LL":
        cards += ((AHR_MASTER_CARDS[1],) if actor == "m" else (AHR_HERO_CARDS[1],))
    return {card.id: card for card in cards}
