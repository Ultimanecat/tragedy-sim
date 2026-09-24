"""Three-placement mastermind search against a coordinated protagonist reply.

The engine still accepts one placement at a time.  This planner searches a
complete legal day plan and caches its remaining two placements; no hero
decision occurs between those three placements.
"""

from __future__ import annotations

import random
import math
from time import perf_counter
from typing import Any, Sequence

from .ai import RiskAwareProtagonistAgent
from .catalog import MODULES, PLOTS
from .optimized_mcts import _command_key
from .particle_ensemble import ParticleEnsembleProtagonistAgent
from .oracle_protagonist import (OracleProtagonistAgent,
                                 FullCardOracleProtagonistAgent,
                                 HiddenCardOracleProtagonistAgent)
from .search import RootActionStats, SearchBudget, SearchGame, SearchTrace
from .strategic_mcts import StrategicMctsMastermindAgent
from .witness import FsbtxWitnessCompiler
from .witness_types import WitnessStrength


def _certain_red_knowledge(events: Sequence[dict[str, Any]],
                           roles: dict[str, str]) -> dict[str, Any]:
    """Reconstruct only private answers implied by completed public queries.

    The event announces the query and its result type, never the answer.
    The mastermind knows the script's initial roles. Older untyped events and
    same-role-group queries need more history and remain deliberately unknown.
    """
    learned = {
        cid: roles[cid]
        for event in events
        if event.get("kind") == "private_information_gained"
        and event.get("information_kind") == "role"
        and isinstance((cid := event.get("character")), str)
        and cid in roles
    }
    return {"roles": learned} if learned else {}


class _PublicReplyEvaluator(OracleProtagonistAgent):
    """Day cutoff scored from the public red view, including final guesses."""

    def __init__(self, budget: SearchBudget, seed: int, *,
                 root_view: dict[str, Any] | None = None,
                 information_weight: float = 0.0):
        super().__init__(reveal_cards=False, budget=budget, rng_seed=seed,
                         script_aware_rollout=False)
        self.root_view = root_view
        self.information_weight = information_weight
        self._compiler = FsbtxWitnessCompiler()
        self._root_entropy: float | None = None

    def _horizon_reached(self, world: SearchGame, event_cursor: int,
                         start_loop: int, start_day: int) -> bool:
        return (world.state.phase == "final_guess"
                or super()._horizon_reached(
                    world, event_cursor, start_loop, start_day))

    def _public_cutoff_view(self, world: SearchGame,
                            rollout_events: Sequence[dict[str, Any]]
                            ) -> dict[str, Any]:
        view = world.protagonist_team_view()
        if self.root_view is not None:
            view["events"] = [*self.root_view.get("events", ()),
                              *rollout_events]
        view["protagonist_knowledge"] = _certain_red_knowledge(
            view.get("events", ()), world.roles)
        return view

    def _role_entropy(self, view: dict[str, Any]) -> float:
        """Cheap, conservative hard-role domain entropy at a day cutoff.

        Full joint posterior reconstruction is unbounded in late-game witness
        histories and must not consume the per-decision search deadline.
        Soft witnesses affect actual red guesses at the terminal boundary.
        """
        module = view.get("module")
        if module not in MODULES:
            return 0.0
        roles = {"ordinary", *(role for plot in MODULES[module].plots
                               for role in PLOTS[plot][2])}
        if len(roles) < 2:
            return 0.0
        domains = {str(cid): set(roles) for cid in view.get("characters", ())}
        for cid, fact in view.get("known_roles", {}).items():
            if cid in domains and isinstance(fact, dict):
                role = fact.get("role")
                if role in roles:
                    domains[cid].intersection_update({role})
        for cid, role in view.get("protagonist_knowledge", {}).get(
                "roles", {}).items():
            if cid in domains and role in roles:
                domains[cid].intersection_update({role})
        for witness in self._compiler.compile(view):
            if witness.strength != WitnessStrength.HARD:
                continue
            cid = ("part_timer" if witness.subject == "part_timer_question"
                   else witness.subject)
            if cid not in domains:
                continue
            if witness.kind == "role_is":
                allowed = {str(witness.value)}
                if witness.value == "serial" and module == "BTX":
                    allowed.add("ordinary")  # Virus may convert Ordinary.
                domains[cid].intersection_update(allowed)
            elif witness.kind == "role_in":
                domains[cid].intersection_update(map(str, witness.value))
            elif witness.kind == "role_not_in":
                domains[cid].difference_update(map(str, witness.value))
        if not domains:
            return 0.0
        return sum(math.log(max(1, len(domain))) for domain in domains.values()
                   ) / (len(domains) * math.log(len(roles)))

    def _cutoff_value_with_events(self, world: SearchGame, start_day: int,
                                  rollout_events: Sequence[dict[str, Any]]) -> float:
        if world.state.phase == "final_guess":
            view = self._public_cutoff_view(world, rollout_events)
            actions = world.search_actions(world.controller)
            offers = [self._offer(action, world) for action in actions]
            model = ParticleEnsembleProtagonistAgent(
                SearchBudget(node_limit=1, rollout_depth=6, seed=self.rng_seed),
                particle_count=2, rng_seed=self.rng_seed)
            chosen = model.choose_action(
                participant="team", view=view, offers=offers)
            guesses = chosen.get("arguments", {}).get("guesses", {})
            return (1.0 if all(guesses.get(cid) == role
                               for cid, role in world.roles.items())
                    else -1.0)
        score = super()._cutoff_value(world, start_day)
        if (self.information_weight <= 0 or self.root_view is None
                or world.winner is not None):
            return score
        if self._root_entropy is None:
            self._root_entropy = self._role_entropy(self.root_view)
        entropy = self._role_entropy(
            self._public_cutoff_view(world, rollout_events))
        return max(-0.99, min(0.99, score - self.information_weight
                              * (entropy - self._root_entropy)))


class JointPlanMastermindAgent(StrategicMctsMastermindAgent):
    """Budgeted joint-day candidates, each tested against a three-card reply.

    By default the reply policy sees only the protagonist team's public view.
    Script-aware hidden/full-card replies remain diagnostic ablations.
    Non-placement mastermind decisions retain the strategic MCTS baseline.
    """

    def __init__(self, budget: SearchBudget | None = None, *,
                 reply_nodes: int = 12, reply_model: str = "public",
                 information_weight: float = 0.02):
        super().__init__(budget)
        if reply_nodes < 1:
            raise ValueError("reply_nodes must be positive")
        if reply_model not in {"public", "belief", "hidden", "full"}:
            raise ValueError("reply_model must be public, belief, hidden or full")
        if not 0 <= information_weight <= 0.1:
            raise ValueError("information_weight must be between 0 and 0.1")
        self.reply_nodes = reply_nodes
        self.reply_model = reply_model
        self.information_weight = information_weight
        self._plan: list[dict[str, Any]] = []
        self._plan_day: tuple[int, int] | None = None

    @property
    def plan_name(self) -> str:
        return ("joint_belief_root_mcts" if self.reply_model == "belief"
                else "joint_day_mastermind")

    @staticmethod
    def _placement_phase(game: SearchGame) -> bool:
        return (game.scenario.get("module") in {"FS", "BTX"}
                and game.state.phase == "mastermind"
                and any(action.get("action") == "play"
                        for action in game.search_actions("m")))

    def _candidate(self, game: SearchGame, index: int,
                   rng: random.Random) -> tuple[dict[str, Any], ...]:
        world = game
        bundle: list[dict[str, Any]] = []
        route = self._routes(game)
        preferred = route[index] if index < len(route) else ()
        for slot in range(3 - sum(item.actor == "m" for item in game.state.pending)):
            actions = [action for action in world.search_actions("m")
                       if action.get("action") == "play"]
            if not actions:
                break
            rng.shuffle(actions)
            actions.sort(key=lambda item: self._priority(world, item), reverse=True)
            scripted = preferred[slot] if slot < len(preferred) else None
            matched = next((action for action in actions
                            if scripted is not None
                            and (action["card"], action["target"]) == scripted), None)
            if matched is not None:
                selected = matched
            elif index == 0:
                selected = actions[0]
            else:
                # Both the top route and less obvious counterplay must enter
                # the candidate set; a pure priority beam repeats one combo.
                width = min(len(actions), 5 + 3 * (index % 5))
                selected = actions[rng.randrange(width)]
            bundle.append(selected)
            world = world.search_transition(selected)
        return tuple(bundle)

    @classmethod
    def _routes(cls, game: SearchGame) -> tuple[tuple[tuple[str, str], ...], ...]:
        """Generic FS pressure routes, instantiated from private script facts."""
        plot = cls._plot_target(game)
        key = cls._role_holder(game, "key")
        killer = cls._role_holder(game, "killer")
        serial = cls._role_holder(game, "serial")
        incidents = sorted(
            (item for item in game.scenario.get("incidents", ())
             if item["day"] >= game.state.round),
            key=lambda item: item["day"])
        culprit = incidents[0]["culprit"] if incidents else None
        hospital = ("hospital" if any(item["kind"] == "hospital"
                                     for item in incidents) else None)
        routes: list[tuple[tuple[str, str], ...]] = []
        # The serial-killer route can end the loop without any intrigue.
        # Keep it in the joint candidate set even when a conventional
        # killer/key intrigue route also exists, as in FS01.
        serial_state = game.state.characters.get(serial) if serial else None
        if serial_state is not None and serial_state.alive and serial_state.present:
            company = [character for character in game.state.characters.values()
                       if character.present and character.alive
                       and character.location == serial_state.location]
            if len(company) == 1:
                for victim in (cid for cid, role in game.roles.items()
                               if role in {"key", "friend"}):
                    state = game.state.characters.get(victim)
                    if state is None or not state.alive or not state.present:
                        continue
                    for move in ("h", "v", "d"):
                        if cls._destination(state.location, move) != serial_state.location:
                            continue
                        for pressure in (killer, victim):
                            if pressure is not None:
                                routes.append(((move, victim), ("i2", pressure),
                                               ("p1a", culprit or victim)))
        if plot and hospital:
            for first, second in (("i2", "i1"), ("i1", "i2")):
                for third in (culprit, key):
                    routes.append(((first, plot), (second, hospital),
                                   ("p1a", third)))
                    routes.append(((first, hospital), (second, plot),
                                   ("p1a", third)))
            routes.extend((
                (("i2", plot), ("i1", hospital), ("fp", key)),
                (("i2", plot), ("p1a", culprit), ("i1", hospital)),
            ))
        elif key and killer:
            for first, second in (("i2", "i1"), ("i1", "i2")):
                routes.extend((
                    ((first, killer), (second, key), ("p1a", culprit)),
                    ((first, key), (second, killer), ("p1a", culprit)),
                    ((first, killer), (second, key), ("v", key)),
                    ((first, key), (second, killer), ("h", killer)),
                ))
        return tuple(routes)

    def _evaluate(self, game: SearchGame,
                  bundle: tuple[dict[str, Any], ...], seed: int, *,
                  reply_nodes: int | None = None,
                  scenario_count: int = 1,
                  deadline: float | None = None) -> float:
        world = game.search_clone()
        observed_events = list(game.protagonist_team_view().get("events", ()))

        def advance(command: dict[str, Any]) -> None:
            nonlocal world
            previous = world.state.events[-1] if world.state.events else None
            world = world.search_transition(command)
            inherited = int(previous is not None and world.state.events
                            and world.state.events[0] == previous)
            observed_events.extend(world.state.events[inherited:])

        for command in bundle:
            advance(command)
        if world.winner is not None:
            return self.evaluator(world)
        if world.state.phase != "protagonists":
            return self.evaluator(world)
        remaining_ms = (None if deadline is None else
                        max(1, int((deadline - perf_counter()) * 1000)))
        reply_limit = reply_nodes or self.reply_nodes
        if remaining_ms is not None:
            # One oracle candidate is indivisible, so a deadline alone can
            # still overshoot. Shrink the reply search as the shared budget
            # runs down instead of always starting a full 12/24-node search.
            reply_limit = min(reply_limit, max(1, remaining_ms // 150))
        reply_budget = SearchBudget(node_limit=reply_limit,
                                    rollout_depth=12, seed=seed,
                                    time_limit_ms=remaining_ms)
        if self.reply_model in {"public", "belief"}:
            evaluator = _PublicReplyEvaluator(
                reply_budget, seed,
                root_view=self._red_reply_view(game, world, observed_events),
                information_weight=(self.information_weight
                                    if self.reply_model == "belief" else 0.0))
            if evaluator.information_weight:
                initial_view = self._red_reply_view(
                    game, game, game.protagonist_team_view().get("events", ()))
                evaluator._root_entropy = evaluator._role_entropy(initial_view)
            policy = (ParticleEnsembleProtagonistAgent(
                SearchBudget(node_limit=min(reply_limit, 8), rollout_depth=6,
                             time_limit_ms=remaining_ms, seed=seed),
                particle_count=max(2, min(4, reply_limit // 2)),
                rng_seed=seed, mastermind_policy_samples=1)
                if self.reply_model == "belief" else
                RiskAwareProtagonistAgent(random.Random(self.budget.seed)))
            while world.state.phase == "protagonists":
                actions = world.search_actions(world.controller)
                if not actions:
                    break
                offers = [evaluator._offer(action) for action in actions]
                view = self._red_reply_view(game, world, observed_events)
                chosen = policy.choose_action(
                    participant="team", view=view, offers=offers)
                selected = actions[next(i for i, offer in enumerate(offers)
                                        if offer["id"] == chosen["id"])]
                advance(selected)
            evaluator.root_view = self._red_reply_view(
                game, world, observed_events)
            hero_score, _ = evaluator._day_score(
                world, game.state.loop, game.state.round)
            return -hero_score
        oracle = (HiddenCardOracleProtagonistAgent(
            reply_budget, scenario_count=scenario_count, rng_seed=seed)
            if self.reply_model == "hidden" else
            FullCardOracleProtagonistAgent(reply_budget, rng_seed=seed))
        actions = world.search_actions(world.controller)
        offers = [oracle._offer(action) for action in actions]
        public_view = world.protagonist_team_view()
        if self.reply_model == "hidden":
            # search_clone retains only recent engine events.  Restore the
            # real, publicly observable history for card-history sampling.
            prior = game.protagonist_team_view().get("events", ())
            recent = public_view.get("events", ())
            public_view["events"] = [*prior, *recent]
        oracle.choose_game_action(participant="team", game=world,
                                  offers=offers,
                                  public_view=public_view)
        reply = oracle.last_trace.selected_bundle if oracle.last_trace else ()
        for command in reply:
            legal = {_command_key(action): action
                     for action in world.search_actions(world.controller)}
            selected = legal.get(_command_key(command))
            if selected is None:
                break
            world = world.search_transition(selected)
        hero_score, _ = oracle._day_score(
            world, game.state.loop, game.state.round)
        return -hero_score

    @staticmethod
    def _red_reply_view(game: SearchGame, world: SearchGame,
                        observed_events: Sequence[dict[str, Any]] | None = None
                        ) -> dict[str, Any]:
        """Red observation with only answers black can infer from events."""
        view = world.protagonist_team_view()
        if observed_events is not None:
            view["events"] = list(observed_events)
        else:
            prior = game.protagonist_team_view().get("events", ())
            recent = view.get("events", ())
            if prior and recent and prior[-1] == recent[0]:
                recent = recent[1:]
            view["events"] = [*prior, *recent]
        view["protagonist_knowledge"] = _certain_red_knowledge(
            view["events"], world.roles)
        return view

    def search(self, game: SearchGame) -> Any:
        if game.controller != "m":
            raise ValueError("joint mastermind requires a mastermind decision")
        if not self._placement_phase(game):
            self._plan.clear()
            self._plan_day = None
            return super().search(game)
        started = perf_counter()
        root_hash = SearchTrace.hash_state_key(game.state_key("m"))
        typed = list(game.action_offers("m"))
        raw = list(game.search_actions("m"))
        offered = {_command_key(action): offer for action, offer in zip(raw, typed)}
        position = (game.state.loop, game.state.round)
        if self._plan_day == position and self._plan:
            selected = offered.get(_command_key(self._plan[0]))
            if selected is not None:
                self._plan.pop(0)
                self.last_trace = SearchTrace(
                    strategy=self.plan_name, seed=self.budget.seed,
                    root_key_hash=root_hash, node_limit=self.budget.node_limit,
                    rollout_depth=self.budget.rollout_depth,
                    time_limit_ms=self.budget.time_limit_ms, nodes=0,
                    iterations=0, max_depth=0,
                    elapsed_ms=(perf_counter() - started) * 1000,
                    stop_reason="joint_plan_followup",
                    selected_action_id=selected.id)
                return selected
        self._plan.clear()
        self._plan_day = position
        self._retained_root = None
        if self.reply_model == "belief":
            return self._search_belief(game, started, root_hash, offered)
        rng = random.Random(f"{self.budget.seed}:{root_hash}:joint")
        seen: set[tuple[str, ...]] = set()
        evaluations: list[tuple[float, tuple[dict[str, Any], ...]]] = []
        validation_limit = min(4, self.budget.node_limit // 5)
        candidate_limit = max(1, self.budget.node_limit - validation_limit)
        attempts = 0
        deadline = (None if self.budget.time_limit_ms is None else
                    started + self.budget.time_limit_ms / 1000)
        while len(evaluations) < candidate_limit and attempts < self.budget.node_limit * 8:
            if deadline is not None and perf_counter() >= deadline and evaluations:
                break
            bundle = self._candidate(game, attempts, rng)
            attempts += 1
            signature = tuple(sorted(_command_key(item) for item in bundle))
            if not bundle or signature in seen:
                continue
            seen.add(signature)
            score = self._evaluate(game, bundle, self.budget.seed + attempts,
                                   deadline=deadline)
            evaluations.append((score, bundle))
        if not evaluations:
            return super().search(game)
        validated = []
        if deadline is None or perf_counter() < deadline:
            for index, (_, bundle) in enumerate(
                    sorted(evaluations, key=lambda item: item[0], reverse=True)
                    [:validation_limit]):
                if deadline is not None and perf_counter() >= deadline:
                    break
                score = self._evaluate(
                    game, bundle, self.budget.seed + 1000 + index,
                    reply_nodes=max(24, self.reply_nodes), scenario_count=3,
                    deadline=deadline)
                validated.append((score, bundle))
        _, best = max(validated or evaluations, key=lambda item: item[0])
        self._plan = list(best[1:])
        selected = offered[_command_key(best[0])]
        first_stats = {}
        for score, bundle in (*evaluations, *validated):
            key = _command_key(bundle[0])
            values = first_stats.setdefault(key, [])
            values.append(score)
        stats = tuple(RootActionStats(
            action_id=offer.id, actor=offer.actor, kind=offer.kind,
            parameters=dict(offer.parameters), visits=len(first_stats.get(key, ())),
            mean_value=(sum(first_stats[key]) / len(first_stats[key])
                        if key in first_stats else 0.0))
            for key, offer in offered.items())
        self.last_trace = SearchTrace(
            strategy=self.plan_name, seed=self.budget.seed,
            root_key_hash=root_hash, node_limit=self.budget.node_limit,
            rollout_depth=self.budget.rollout_depth,
            time_limit_ms=self.budget.time_limit_ms,
            nodes=len(evaluations) + len(validated),
            iterations=len(evaluations) + len(validated), max_depth=3,
            elapsed_ms=(perf_counter() - started) * 1000,
            stop_reason=("time_limit" if len(evaluations) + len(validated)
                         < self.budget.node_limit
                         else "node_limit"), selected_action_id=selected.id,
            root_actions=stats, candidate_actions=attempts,
            expanded_actions=len(evaluations))
        return selected

    def _search_belief(self, game: SearchGame, started: float,
                       root_hash: str, offered: dict[str, Any]) -> Any:
        """Root-bandit search over plans with fresh public-belief red replies."""
        deadline = (None if self.budget.time_limit_ms is None else
                    started + self.budget.time_limit_ms / 1000)
        rng = random.Random(f"{self.budget.seed}:{root_hash}:belief")
        candidate_limit = min(8, max(1, self.budget.node_limit // 2))
        plans: list[tuple[dict[str, Any], ...]] = []
        scores: list[list[float]] = []
        seen: set[tuple[str, ...]] = set()
        attempts = 0
        while (len(plans) < candidate_limit
               and attempts < self.budget.node_limit * 8):
            if deadline is not None and perf_counter() >= deadline and plans:
                break
            bundle = self._candidate(game, attempts, rng)
            attempts += 1
            signature = tuple(sorted(_command_key(item) for item in bundle))
            if not bundle or signature in seen:
                continue
            seen.add(signature)
            score = self._evaluate(game, bundle, self.budget.seed + 1,
                                   deadline=deadline)
            plans.append(bundle)
            scores.append([score])
        if not plans:
            return super().search(game)
        samples = len(plans)
        while samples < self.budget.node_limit:
            if deadline is not None and perf_counter() >= deadline:
                break
            index = max(range(len(plans)), key=lambda i: (
                sum(scores[i]) / len(scores[i])
                + self.budget.exploration
                * math.sqrt(math.log(samples + 1) / len(scores[i]))))
            score = self._evaluate(
                game, plans[index], self.budget.seed + 1000 + samples,
                deadline=deadline)
            scores[index].append(score)
            samples += 1
        best_index = max(range(len(plans)),
                         key=lambda i: sum(scores[i]) / len(scores[i]))
        best = plans[best_index]
        self._plan = list(best[1:])
        selected = offered[_command_key(best[0])]
        first_stats: dict[str, list[float]] = {}
        for bundle, values in zip(plans, scores):
            first_stats.setdefault(_command_key(bundle[0]), []).extend(values)
        stats = tuple(RootActionStats(
            action_id=offer.id, actor=offer.actor, kind=offer.kind,
            parameters=dict(offer.parameters),
            visits=len(first_stats.get(key, ())),
            mean_value=(sum(first_stats[key]) / len(first_stats[key])
                        if key in first_stats else 0.0))
            for key, offer in offered.items())
        self.last_trace = SearchTrace(
            strategy=self.plan_name, seed=self.budget.seed,
            root_key_hash=root_hash, node_limit=self.budget.node_limit,
            rollout_depth=self.budget.rollout_depth,
            time_limit_ms=self.budget.time_limit_ms,
            nodes=samples, iterations=samples, max_depth=3,
            elapsed_ms=(perf_counter() - started) * 1000,
            stop_reason=("time_limit" if samples < self.budget.node_limit
                         else "node_limit"), selected_action_id=selected.id,
            root_actions=stats, candidate_actions=attempts,
            expanded_actions=len(plans))
        return selected
