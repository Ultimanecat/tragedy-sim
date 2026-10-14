"""Fast joint card projection and hypothesis-conditioned tactical ordering.

The projection uses sampled/explicitly authorized worlds. Tactical risk is an
ordering heuristic, not a survival certificate: optional abilities and their
interaction are still decided by the real engine for shortlisted plans.
"""

from collections import OrderedDict
from dataclasses import dataclass

from .cards import COORDS, deck
from .catalog import CHARACTERS, REFUSAL


BOARDS = tuple(COORDS)
BOARD_ID = {b: i for i, b in enumerate(BOARDS)}


@dataclass(frozen=True)
class CardProjection:
    locations: tuple[int, ...]
    paranoia: tuple[int, ...]
    goodwill: tuple[int, ...]
    intrigue: tuple[int, ...]
    roles: tuple[str, ...]
    uncertain_follow: bool = False


class CardProjectionModel:
    """Precompute local card effects, then compose three distinct targets."""

    def __init__(self, world, space):
        if world.module not in {"FS", "BTX"}:
            raise ValueError("FS/BTX projection required")
        self.ids = tuple(world.state.characters)
        self.n = len(self.ids)
        self.index = {cid: i for i, cid in enumerate((*self.ids, *BOARDS))}
        self.roles = tuple(world.roles[cid] for cid in self.ids)
        self.live = tuple(i for i, cid in enumerate(self.ids)
                          if world.state.characters[cid].alive and world.state.characters[cid].present)
        self.base_location = tuple(BOARD_ID[world.state.characters[cid].location] for cid in self.ids)
        self.start_p = tuple(world.state.characters[cid].paranoia for cid in self.ids)
        self.virus = "virus" in world.scenario["subplots"]
        self.prefix = tuple((p.card, p.target) for p in world.state.pending if p.actor != "m")
        self.cancel_fi = sum(card == "fi" for card, _ in self.prefix) >= 2
        self.ignore = {BOARD_ID[b] for b in world._ignore_intrigue}
        self.cultists = tuple(i for i in self.live if self.roles[i] == "cultist"
                              and world._available_key(f"cultist:{self.ids[i]}"))
        self.extra_areas = tuple(
            (15 if world.scenario.get("special_rules", {}).get("all_locations_count_as")
             == world.scenario.get("character_options", {}).get("boss", {}).get("territory") else
             1 << BOARD_ID[world.scenario["character_options"]["boss"]["territory"]])
            if cid == "boss" else 0 for cid in self.ids)
        self.servant = self.index.get("servant")
        self.follow_targets = tuple(self.index[cid] for cid in {"rich", "boss", *world._servant_targets}
                                    if cid in self.index and self.index[cid] in self.live)
        by_target = {}
        for p in world.state.pending:
            by_target.setdefault(p.target, []).append(world._deck(p.actor)[p.card])
        self.table = {}
        self.root_rows = []
        for target, i in self.index.items():
            character = world.state.characters.get(target)
            original = ((self.base_location[i], character.paranoia, character.goodwill, character.intrigue)
                        if character is not None else (BOARD_ID[target], 0, 0, world.state.locations[target]))
            original_cards = tuple(by_target.get(target, ()))
            possible = {None} | {p.card for domain in space.domains for p in domain if p.target == target}
            for red in possible:
                cards = original_cards + ((deck("a")[red],) if red is not None else ())
                effects = {c.effect for c in cards}
                location = original[0]
                if character is not None and "forbid_movement" not in effects:
                    x, y = COORDS[character.location]
                    for movement in ("horizontal", "vertical", "diagonal"):
                        if movement in effects:
                            dx, dy = {"horizontal": (1, 0), "vertical": (0, 1), "diagonal": (1, 1)}[movement]
                            x, y = x ^ dx, y ^ dy
                    destination = next(b for b, point in COORDS.items() if point == (x, y))
                    if destination not in character.forbidden and world._movement_destination_allowed(target, destination):
                        location = BOARD_ID[destination]
                values = [location]
                peak_p, changed = original[1], False
                for offset, counter in enumerate(("paranoia", "goodwill", "intrigue"), 1):
                    value = original[offset]
                    changes = [c.amount for c in cards if c.effect == counter] if character is not None or counter == "intrigue" else []
                    blocked = f"forbid_{counter}" in effects
                    if counter == "intrigue":
                        blocked = blocked and not self.cancel_fi
                    if counter == "goodwill" and character is not None and world._has(target, "time_traveler"):
                        blocked = False
                    # Ignore Intrigue is applied below, after all locations
                    # and potential cultist areas have been composed.
                    positive, negative = sum(x for x in changes if x > 0), sum(x for x in changes if x < 0)
                    raw = max(0, value + positive)
                    if counter == "paranoia" and not blocked:
                        peak_p = max(peak_p, raw)
                    raw = max(0, raw + negative)
                    if not blocked and (positive or negative):
                        changed = True
                    values.append(value if blocked else raw)
                    if counter == "intrigue":
                        raw_i = raw
                        blocked_i_changed = bool(blocked and (positive or negative))
                self.table[(target, red)] = (tuple(values), raw_i, peak_p, changed, blocked_i_changed)
            self.root_rows.append(self.table[(target, None)])

    def areas(self, i, locations):
        return (1 << locations[i]) | self.extra_areas[i]

    def project(self, plan, *, adversarial_cultists=True):
        rows = list(self.root_rows)
        for p in plan:
            rows[self.index[p.target]] = self.table[(p.target, p.card)]
        locations = [r[0][0] for r in rows]
        uncertain = False
        if self.servant in self.live:
            destinations = {locations[i] for i in self.follow_targets
                            if self.base_location[i] == self.base_location[self.servant]
                            and locations[i] != self.base_location[i]}
            if destinations:
                locations[self.servant] = min(destinations)
                uncertain = len(destinations) > 1
        ignore = set(self.ignore)
        if adversarial_cultists:
            # At most one effective FI target: a cultist can choose its area.
            for i in self.cultists:
                mask = self.areas(i, locations)
                ignore.update(b for b in range(4) if mask & (1 << b))
        p = tuple(r[0][1] for r in rows)
        g = tuple(r[0][2] for r in rows)
        intrigue = tuple(r[1] if locations[i] in ignore else r[0][3] for i, r in enumerate(rows))
        changed = any(r[3] or (r[4] and locations[i] in ignore) for i, r in enumerate(rows))
        roles = self.roles
        if self.virus and changed:
            roles = tuple("serial" if i in self.live and role == "ordinary" and rows[i][2] >= 3 else role
                          for i, role in enumerate(roles))
        return CardProjection(tuple(locations), p, g, intrigue, roles, uncertain)


class TacticalWorldModel:
    """Soft day/near-future threats after projected cards and black abilities."""

    def __init__(self, world, space):
        self.cards = CardProjectionModel(world, space)
        c = self.cards
        self.main = world.scenario["main_plot"]
        self.subplots = tuple(world.scenario["subplots"])
        self.last_day = world.state.round == world.scenario["days"]
        self.remaining_days = world.scenario["days"] - world.state.round
        self.loop = world.state.loop
        self.protected = world.protected
        self.guards = tuple(world.guards.get(cid, 0) for cid in c.ids)
        self.ai_extra = tuple(world.state.characters[cid].hope + world.state.characters[cid].despair for cid in c.ids)
        self.brains_available = tuple(world._available_key(f"brain:{cid}") for cid in c.ids)
        self.rumor_available = "rumor" in self.subplots and world._available_key("plot:rumor", True)
        self.today = next((x for x in world.scenario["incidents"] if x["day"] == world.state.round), None)
        if (self.today and self.today["culprit"] == "part_timer" and "part_timer_question" in c.index
                and not world.state.characters["part_timer"].alive
                and world.state.characters["part_timer_question"].present):
            self.today = {**self.today, "culprit": "part_timer_question"}
        self.prevention = self.today is not None and self.today["culprit"] in world._prevented_incident_culprits
        self.initial_boards = tuple(BOARD_ID[world._loop_initial_locations[cid]] for cid in c.ids)
        self.abilities = tuple(tuple(a for a in CHARACTERS[cid].abilities
                                     if self.loop >= a.min_loop
                                     and f"goodwill:{cid}:{a.id}" not in world.public_day_used
                                     and (not a.once or f"goodwill:{cid}:{a.id}" not in world.public_loop_used)) for cid in c.ids)
        self.base_g = tuple(world.state.characters[cid].goodwill for cid in c.ids)

    def score(self, plan):
        c = self.cards
        s = c.project(plan)
        live, loc, p, g, intrigue, roles = c.live, s.locations, s.paranoia, s.goodwill, s.intrigue, s.roles
        def has(i, role):
            return roles[i] == role or (roles[i] == "factor" and
                   ((role == "key" and intrigue[c.n + BOARD_ID["city"]] >= 2)
                    or (role == "conspiracy" and intrigue[c.n + BOARD_ID["school"]] >= 2)))
        critical = {i for i in live if has(i, "key") or roles[i] == "friend"}
        brains = [i for i in live if has(i, "brain") and self.brains_available[i]]
        conspirators = [i for i in live if has(i, "conspiracy")]
        brain_masks = [c.areas(i, loc) for i in brains]
        conspiracy_masks = [c.areas(i, loc) for i in conspirators]
        i_pressure = [intrigue[i] + sum(bool(mask & (1 << loc[i])) for mask in brain_masks)
                      for i in range(c.n + 4)]
        p_pressure = [p[i] + sum(bool(mask & (1 << loc[i])) for mask in conspiracy_masks) for i in range(c.n)]
        doctor = c.index.get("doctor")
        if doctor in live and roles[doctor] in REFUSAL and g[doctor] >= 2:
            for i in live:
                if i != doctor and loc[i] == loc[doctor]:
                    p_pressure[i] += 1
        for b in range(4):
            i_pressure[c.n + b] += int(self.rumor_available)
        ready = [(i, ability) for i in live for ability in self.abilities[i]
                 if g[i] >= ability.threshold and (ability.unrefusable or roles[i] not in REFUSAL)]
        def scoped(source, ability, target):
            scope = ability.scope
            if target >= c.n and scope != "same_or_location":
                return False
            if scope == "self":
                return target == source
            if scope in {"any_other", "panicked_any_other"}:
                same = target != source
            else:
                same = bool(c.areas(source, loc) & (1 << loc[target]))
            if scope in {"other", "other_student", "panicked_other", "any_other", "rich"}:
                same = same and target != source
            if scope in {"student", "other_student"}:
                same = same and target < c.n and "student" in CHARACTERS[c.ids[target]].traits
            if scope == "rich":
                same = same and loc[source] in (BOARD_ID["school"], BOARD_ID["city"])
            if scope in {"panicked_other", "panicked_any_other"}:
                same = same and p_pressure[target] >= CHARACTERS[c.ids[target]].limit
            return same
        def relief(target, counter):
            return sum(1 for i, a in ready if
                       ((a.kind == "adjust" and counter == "paranoia")
                        or (a.kind == "counter" and a.counter == counter and a.amount < 0))
                       and scoped(i, a, target))
        def death_fails(target):
            if target not in critical or has(target, "time_traveler") or self.guards[target]:
                return False
            servant = c.servant
            if servant in live and target in c.follow_targets and loc[servant] == loc[target]:
                return servant in critical and not self.guards[servant]
            return True
        hero_protection = self.protected or any(a.kind == "protect" for _, a in ready)
        risk = 0
        serials = [i for i in live if has(i, "serial")]
        serial_victims = set()
        forced_serial_victims = set()
        for serial in serials:
            possible_victims = set()
            for b in range(4):
                if c.areas(serial, loc) & (1 << b):
                    others = [i for i in live if i != serial and loc[i] == b]
                    if len(others) == 1:
                        serial_victims.add(others[0])
                        possible_victims.add(others[0])
            if len(possible_victims) == 1:
                forced_serial_victims.update(possible_victims)
        risk += sum(3 if has(i, "key") else 1 for i in serial_victims if death_fails(i))
        for killer in (i for i in live if has(i, "killer")):
            can_kill = any(a.kind == "kill" and scoped(source, a, killer) for source, a in ready)
            if (killer in forced_serial_victims and not self.guards[killer]) or can_kill:
                continue
            if i_pressure[killer] - relief(killer, "intrigue") >= 4 and not hero_protection:
                risk += 4
            for target in critical:
                # Match the current engine's literal Key target predicate.
                if roles[target] == "key" and target != killer and c.areas(killer, loc) & (1 << loc[target]):
                    if i_pressure[target] - relief(target, "intrigue") >= 2 and death_fails(target):
                        risk += 3
        for i in live:
            if roles[i] == "lover" and p_pressure[i] - relief(i, "paranoia") >= 3 and i_pressure[i] >= 1 and not hero_protection:
                risk += 4
            if self.last_day and has(i, "time_traveler") and g[i] <= 2:
                risk += 4
        if self.today and not self.prevention:
            culprit = c.index[self.today["culprit"]]
            score = p_pressure[culprit] - relief(culprit, "paranoia")
            if c.ids[culprit] == "ai":
                score += g[culprit] + i_pressure[culprit] + self.guards[culprit] + self.ai_extra[culprit]
            prevented = any(a.kind == "prevent_incident" and source == culprit for source, a in ready)
            if culprit in live and score >= CHARACTERS[c.ids[culprit]].limit and not prevented:
                kind = self.today["kind"]
                if kind == "suicide":
                    risk += 3 * int(death_fails(culprit))
                if kind in {"murder", "faraway"}:
                    risk += 3 * int(any(death_fails(i) for i in critical if i != culprit and
                                          (loc[i] == loc[culprit] if kind == "murder" else i_pressure[i] >= 2)))
                if kind == "hospital":
                    hospital = i_pressure[c.n + BOARD_ID["hospital"]]
                    risk += 4 * int(hospital >= 2 and not hero_protection)
                    risk += 3 * int(hospital >= 1 and any(death_fails(i) and loc[i] == BOARD_ID["hospital"] for i in critical))
                if self.main == "change" and kind == "butterfly":
                    risk += 2
        plot_boards = []
        if self.main in {"protect", "sealed"}:
            plot_boards.append(BOARD_ID["school" if self.main == "protect" else "shrine"])
        if self.main in {"avenger", "bomb"}:
            plot_boards.extend(self.initial_boards[i] for i, role in enumerate(roles)
                               if role == ("brain" if self.main == "avenger" else "witch"))
        plot_pressure = 0
        for b in set(plot_boards):
            after = i_pressure[c.n + b]
            after -= sum(1 for i, a in ready if a.kind == "purify" and loc[i] == BOARD_ID["shrine"] == b)
            after -= relief(c.n + b, "intrigue")
            plot_pressure += max(0, after)
            if self.last_day and after >= 2:
                risk += 4
        if self.last_day and self.main == "sign":
            risk += 3 * int(any(roles[i] == "key" and i_pressure[i] - relief(i, "intrigue") >= 2 for i in live))
        pressure = (0.12 * plot_pressure + 0.035 * sum(i_pressure[i] for i in live if has(i, "key") or has(i, "killer")))
        preparation = 0.0
        for i in live:
            for a in self.abilities[i]:
                if a.kind not in {"counter", "adjust", "guard", "protect", "relocate", "kill", "purify"}:
                    continue
                # Positive counter abilities may be useful in a particular
                # plan, but are not unconditional defensive preparation.
                # Journalist has two positive abilities; rewarding both
                # previously crowded out genuine defensive setup.
                if a.kind == "counter" and (a.amount >= 0 or a.counter not in {"paranoia", "intrigue"}):
                    continue
                if roles[i] in REFUSAL and not a.unrefusable:
                    continue
                if g[i] < a.threshold and g[i] + 2 * self.remaining_days < a.threshold:
                    continue
                preparation += 0.025 * (min(g[i], a.threshold) - min(self.base_g[i], a.threshold)) / max(1, a.threshold)
        return risk, preparation - pressure


class JointThreatRanker:
    """Common-scenario joint ordering; cached by effects, not owning seat.

    Resource cost remains outside the cache. Neither samples nor identity
    probabilities are modified by this tactical ordering.
    """

    def __init__(self, worlds, space, *, cache_limit=32768):
        self.models = tuple(TacticalWorldModel(w, space) for w in worlds)
        if not self.models:
            raise ValueError("joint ranking requires common worlds")
        self.cache = OrderedDict()
        self.cache_limit = cache_limit
        self.projections = 0

    def __call__(self, plan):
        signature = tuple(sorted(p.effect for p in plan))
        row = self.cache.get(signature)
        if row is None:
            outcomes = [model.score(plan) for model in self.models]
            self.projections += len(outcomes)
            row = (sum(risk == 0 for risk, _ in outcomes) / len(outcomes),
                   -max(risk for risk, _ in outcomes), sum(value for _, value in outcomes) / len(outcomes))
            self.cache[signature] = row
            if len(self.cache) > self.cache_limit:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(signature)
        scarce = sum(p.card in {"fm", "g2", "p-1"} for p in plan)
        return row[0], row[1], row[2] - 0.025 * scarce
