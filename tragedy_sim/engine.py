"""Deterministic action phase only. No role, goodwill ability, incident or AI rules."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field

from .cards import ACTORS, ACTOR_NAMES, COORDS, COUNTER_NAMES, LOCATIONS, MOVES, PROTAGONISTS, deck


class RuleError(ValueError):
    """An illegal operation; validation occurs before any state changes."""


@dataclass
class Character:
    id: str
    name: str
    location: str
    forbidden: tuple[str, ...] = ()
    paranoia: int = 0
    goodwill: int = 0
    intrigue: int = 0
    alive: bool = True


@dataclass(frozen=True)
class Placement:
    actor: str
    card: str
    target: str


@dataclass
class State:
    characters: dict[str, Character]
    leader: str = "a"
    loop: int = 1
    round: int = 1
    phase: str = "mastermind"
    locations: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LOCATIONS, 0))
    pending: list[Placement] = field(default_factory=list)
    face_up: bool = False
    hands: dict[str, list[str]] = field(default_factory=lambda: {a: list(deck(a)) for a in ACTORS})
    discarded: dict[str, list[str]] = field(default_factory=lambda: {a: [] for a in ACTORS})
    events: list[dict] = field(default_factory=list)


def practice_characters() -> list[Character]:
    # Only initial positions / forbidden locations, not character abilities.
    return [Character("student", "男学生", "school"), Character("doctor", "医生", "hospital"),
            Character("maiden", "巫女", "shrine", ("city",)),
            Character("worker", "职员", "city", ("school",)),
            Character("patient", "住院患者", "hospital", ("shrine", "city", "school"))]


class ActionGame:
    def __init__(self, characters: list[Character] | None = None, *, leader: str = "a", module: str = "FS"):
        if module not in ("FS", "BTX"):
            raise RuleError("第一阶段只支持 FS / BTX 共用的基础行动牌")
        if leader not in PROTAGONISTS:
            raise RuleError("领队必须是 a / b / c")
        characters = practice_characters() if characters is None else deepcopy(characters)
        ids = set()
        for char in characters:
            if not isinstance(char, Character):
                raise RuleError("棋盘需要 Character 对象")
            if not isinstance(char.id, str) or not char.id.isidentifier() or char.id in ids or char.id in LOCATIONS:
                raise RuleError("角色 id 必须唯一，且不能与地点重复")
            if not isinstance(char.name, str) or not char.name:
                raise RuleError("角色需要非空名字")
            if char.location not in LOCATIONS or any(loc not in LOCATIONS for loc in char.forbidden):
                raise RuleError("未知地点")
            if char.location in char.forbidden:
                raise RuleError("初始位置不能是禁行区域")
            if type(char.alive) is not bool or any(type(getattr(char, c)) is not int or getattr(char, c) < 0
                                                 for c in COUNTER_NAMES):
                raise RuleError("计数物必须是非负整数，alive 必须是布尔值")
            ids.add(char.id)
        self.module = module
        self._initial = deepcopy({c.id: c for c in characters})
        self.state = State(characters=deepcopy(self._initial), leader=leader)

    @property
    def next_actor(self) -> str | None:
        s = self.state
        if s.phase == "mastermind":
            return "m"
        if s.phase == "protagonists":
            already_played = sum(p.actor != "m" for p in s.pending)
            return PROTAGONISTS[(PROTAGONISTS.index(s.leader) + already_played) % 3]
        return None

    def _event(self, kind: str, message: str, **data) -> None:
        s = self.state
        s.events.append(dict(loop=s.loop, round=s.round, kind=kind, message=message, **data))

    def name(self, target: str) -> str:
        return self.state.characters[target].name if target in self.state.characters else LOCATIONS.get(target, target)

    def play(self, actor: str, card_id: str, target: str) -> None:
        s = self.state
        if actor not in ACTORS or actor != self.next_actor:
            raise RuleError(f"当前应由 {self.next_actor or '无人'} 出牌")
        if card_id not in s.hands[actor]:
            raise RuleError("手中没有这张牌：检查牌名、所属玩家或本轮使用次数")
        if target not in s.characters and target not in LOCATIONS:
            raise RuleError("目标不存在")
        if target in s.characters and not s.characters[target].alive:
            raise RuleError("不能向尸体放置行动牌")
        if any((p.actor == "m") == (actor == "m") and p.target == target for p in s.pending):
            raise RuleError("同阵营不能在同一角色或地点上重复出牌")
        # All action cards may legally target locations, including ineffective bluffs.
        s.hands[actor].remove(card_id)
        s.pending.append(Placement(actor, card_id, target))
        self._event("card_placed", f"{ACTOR_NAMES[actor]}在{self.name(target)}放置了一张暗牌。",
                    actor=actor, target=target)
        if len(s.pending) == 3:
            s.phase = "protagonists"
        elif len(s.pending) == 6:
            s.phase = "reveal"

    def resolve(self) -> None:
        self._reveal_and_move()
        self._resolve_counters()

    def _reveal_and_move(self) -> None:
        s = self.state
        if s.phase != "reveal":
            raise RuleError("必须完成剧作家三张、每名主人公各一张出牌后，才能揭示")
        self._event("cards_revealed", "同时揭示六张行动牌。", cards=[asdict(p) for p in s.pending])
        s.face_up = True
        by_target = {}
        for p in s.pending:
            by_target.setdefault(p.target, []).append(deck(p.actor)[p.card])

        # 1. Forbid movement; 2. all movements. Cards on characters travel with them.
        for target, cards in by_target.items():
            if target not in s.characters:
                continue
            char = s.characters[target]
            effects = {card.effect for card in cards}
            moves = effects & MOVES.keys()
            if not moves:
                continue
            if "forbid_movement" in effects:
                self._event("movement_blocked", f"{char.name}：移动被禁止。")
                continue
            x, y = COORDS[char.location]
            # Same direction twice is ONE move, not zero. Different directions combine.
            for move in sorted(moves):
                dx, dy = MOVES[move]
                x, y = x ^ dx, y ^ dy
            destination = next(loc for loc, coords in COORDS.items() if coords == (x, y))
            if destination in char.forbidden:
                self._event("movement_blocked", f"{char.name}：最终目的地是禁行区域，留在原地。")
            else:
                char.location = destination
                self._event("character_moved", f"{char.name} 移动到{LOCATIONS[destination]}。",
                            character=target, location=destination)

        s.phase = "action_counters"

    def _ignore_forbid(self, counter: str, target: str) -> bool:
        return False

    def _counter_mutated(self, target: str, counter: str) -> None:
        """Hook for mandatory constant effects in a complete game."""

    def _resolve_counters(self) -> None:
        s = self.state
        if s.phase != "action_counters":
            raise RuleError("尚未揭示并结算移动")
        by_target = {}
        for p in s.pending:
            by_target.setdefault(p.target, []).append(deck(p.actor)[p.card])

        # 3. Other forbids: multiple Forbid Intrigue cards cancel GLOBALLY, even bluffs.
        intrigue_forbids = sum(deck(p.actor)[p.card].effect == "forbid_intrigue" for p in s.pending)
        if intrigue_forbids >= 2:
            self._event("forbids_cancelled", "本次打出了多张禁止密谋牌，所有禁止密谋牌失效。")
        # 4. Remaining counters. Add before remove; never below zero.
        for target, cards in by_target.items():
            effects = {card.effect for card in cards}
            if target in LOCATIONS:
                for card in cards:
                    if card.effect not in ("intrigue", "forbid_intrigue"):
                        self._event("location_bluff", f"{LOCATIONS[target]}上的「{card.name}」没有效果（地点佯攻牌）。")
            counters = COUNTER_NAMES if target in s.characters else ("intrigue",)
            for counter in counters:
                changes = [c.amount for c in cards if c.effect == counter]
                if not changes:
                    continue
                blocked = f"forbid_{counter}" in effects
                if counter == "intrigue":
                    blocked = blocked and intrigue_forbids == 1
                blocked = blocked and not self._ignore_forbid(counter, target)
                if blocked:
                    self._event("counter_blocked", f"{self.name(target)}：{COUNTER_NAMES[counter]}变更被禁止。")
                    continue
                before = getattr(s.characters[target], counter) if target in s.characters else s.locations[target]
                after = before
                steps = [before]
                for delta in (sum(v for v in changes if v > 0), sum(v for v in changes if v < 0)):
                    if not delta:
                        continue
                    after = max(0, after + delta)
                    if target in s.characters:
                        setattr(s.characters[target], counter, after)
                    else:
                        s.locations[target] = after
                    self._counter_mutated(target, counter)
                    steps.append(after)
                if len(steps) == 1:
                    steps.append(after)
                progression = " → ".join(str(value) for value in steps)
                self._event("counter_changed", f"{self.name(target)}：{COUNTER_NAMES[counter]} {progression}。",
                            target=target, counter=counter, before=before, after=after, steps=steps)

        # Return ordinary cards NOW. Limited cards are public discards even if blocked.
        for p in s.pending:
            if deck(p.actor)[p.card].once_per_loop:
                s.discarded[p.actor].append(p.card)
            else:
                s.hands[p.actor].append(p.card)
        s.pending.clear()
        s.face_up = False
        s.phase = "resolved"
        self._event("actions_resolved", "行动结算完成；普通牌收回，限次牌公开留置。此处暂停。")

    def next_round(self) -> None:
        """Practice control: skip all NOT IMPLEMENTED later phases and rotate leader."""
        if self.state.phase != "resolved":
            raise RuleError("当前出牌尚未结算")
        s = self.state
        s.round += 1
        s.leader = PROTAGONISTS[(PROTAGONISTS.index(s.leader) + 1) % 3]
        s.phase = "mastermind"
        self._event("practice_advanced", "练习控制：进入下一次出牌（未模拟能力、事件、胜负）。")

    def reset_loop(self) -> None:
        """Practice control only; no loop-end rules or victory adjudication."""
        if self.state.phase != "resolved":
            raise RuleError("请先结算当前出牌，再重置练习轮回")
        old = self.state
        self.state = State(characters=deepcopy(self._initial), leader=old.leader,
                           loop=old.loop + 1, events=old.events)
        self._event("practice_reset", "练习控制：还原初始棋盘，收回所有限次牌；不判定胜负。")

    def view(self, viewer: str = "spectator") -> dict:
        """Detached projection; only the owner can see their unexposed cards."""
        if viewer not in (*ACTORS, "spectator"):
            raise RuleError("视角必须是 m / a / b / c / spectator")
        s = self.state
        return deepcopy({"module": self.module, "loop": s.loop, "round": s.round,
                         "phase": s.phase, "leader": s.leader, "next_actor": self.next_actor,
                         "characters": {cid: asdict(c) for cid, c in s.characters.items()},
                         "locations": s.locations, "discarded": s.discarded,
                         "hand": [cid for cid in deck(viewer) if cid in s.hands[viewer]] if viewer in ACTORS else [],
                         "pending": [{"actor": p.actor, "target": p.target,
                                      "card": p.card if p.actor == viewer or s.face_up else None} for p in s.pending],
                         "events": s.events})
