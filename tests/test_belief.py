"""Information-boundary tests for C3 hidden-world sampling."""

from copy import deepcopy
from dataclasses import replace
import random
import unittest

from tragedy_sim import Game
from tragedy_sim.belief import (BeliefParticleFilter, CatalogBeliefSampler,
                                ConstraintBeliefSampler, DarkCardBelief,
                                FactorizedBeliefState,
                                HiddenWorldHypothesis, ParticleReplayer,
                                ObservationParticleAdvancer,
                                PersistentBeliefState, PublicEvidence,
                                PublicSnapshot)
from tragedy_sim.catalog import PLOTS
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import PublicWitness, WitnessStrength
from tragedy_sim.witness_rules.common_public import compile_public_reveals


class FactorizedBeliefTests(unittest.TestCase):
    def test_btx11_public_setup_produces_valid_worlds(self):
        from tragedy_sim.ismcts import PublicStateDeterminizer
        scenario = ScenarioLibrary().get('official-btx-11-neverending-happy-sad-story')
        game = Game(scenario)
        evidence = PublicEvidence.from_view(game.protagonist_team_view())
        self.assertEqual(evidence.setup_fields()['character_options'],
                         scenario['character_options'])
        sampled = FactorizedBeliefState(seed=0).sample(
            evidence, (), 4, rng=random.Random(0))
        self.assertTrue(sampled.worlds)
        for world in sampled.worlds:
            candidate = Game(world.materialize(evidence))
            self.assertEqual(candidate.scenario['character_options'],
                             scenario['character_options'])
            self.assertNotIn('fg', candidate.state.hands['m'])
            self.assertFalse(candidate.state.characters['godly'].present)
        game.dispatch('m', 'next')
        for card, target in [('i1', 'school'), ('p1a', 'girl'), ('h', 'boss')]:
            game.dispatch('m', 'play', card=card, target=target)
        view = game.protagonist_team_view()
        determined = PublicStateDeterminizer().determinize(
            sampled.worlds[0], PublicEvidence.from_view(view), view,
            rng=random.Random(0))
        self.assertIsNotNone(determined)
        self.assertNotIn('fg', determined.state.hands['m'])
        self.assertTrue(all(placement.card != 'fg'
                            for placement in determined.state.pending))

    def test_private_role_answer_constrains_red_final_guess(self):
        game = Game(example_scenario("BTX"))
        view = game.protagonist_team_view()
        target = next(iter(game.roles))
        role = game.roles[target]
        view["protagonist_knowledge"] = {"roles": {target: role}}
        evidence = PublicEvidence.from_view(view)
        self.assertEqual(dict(evidence.known_roles)[target], role)
        solved = FactorizedBeliefState(seed=2).exact_role_map(
            evidence, ())
        self.assertTrue(solved.ranked)
        self.assertTrue(all(dict(world.roles)[target] == role
                            for world, _ in solved.ranked))

    def test_part_timer_query_refers_to_initial_script_assignment(self):
        game = Game({
            "id": "private-part-timer", "title": "Part-Timer query",
            "module": "FS", "days": 3, "loops": 3,
            "main_plot": "avenger", "subplots": ["rumor"],
            "cast": {"doctor": "ordinary", "maiden": "conspiracy",
                     "part_timer": "brain"},
            "incidents": [], "table_talk": False,
            "character_options": {},
        })
        worker = game.state.characters["part_timer"]
        worker.goodwill = worker.paranoia = worker.intrigue = 1
        game.state.phase = "day_end"
        game._queue_day_end_mandatory_batch()
        game._return_phase = "day_end"
        game._drain()
        self.assertFalse(worker.alive)
        game.state.round = 2
        game._prepare_day_start()
        replacement = game.state.characters["part_timer_question"]
        replacement.goodwill = 3
        game.state.phase = "goodwill"
        choices = game.options(game.controller)
        query = next(i for i, choice in enumerate(choices, 1)
                     if choice.get("source") == "part_timer_question"
                     and choice.get("ability") == "reveal_and_help")
        game.dispatch(game.controller, "choose", index=query)
        accept = next(i for i, choice in enumerate(game.options("m"), 1)
                      if choice.get("accept"))
        game.dispatch("m", "choose", index=accept)
        view = game.protagonist_team_view()
        view["known_roles"]["part_timer"] = {"role": "ordinary"}
        self.assertEqual(view["protagonist_knowledge"]["roles"],
                         {"part_timer_question": "brain"})
        evidence = PublicEvidence.from_view(view)
        self.assertEqual(dict(evidence.known_roles)["part_timer"], "brain")
        self.assertNotIn("part_timer_question", evidence.characters)
        public_witnesses = compile_public_reveals(view)
        self.assertFalse(any(witness.kind == "role_is"
                             and witness.subject == "part_timer"
                             for witness in public_witnesses))
        self.assertTrue(any(witness.kind == "role_not_in"
                            and witness.subject == "part_timer"
                            and "ordinary" in witness.value
                            for witness in public_witnesses))
        uninformed = deepcopy(view)
        uninformed["protagonist_knowledge"] = {}
        before_query = FactorizedBeliefState(seed=2).exact_role_map(
            PublicEvidence.from_view(uninformed), public_witnesses)
        self.assertTrue(before_query.ranked)
        self.assertTrue(all(dict(world.roles)["part_timer"] != "ordinary"
                            for world, _ in before_query.ranked))
        solved = FactorizedBeliefState(seed=2).exact_role_map(
            evidence, public_witnesses)
        self.assertTrue(solved.ranked)
        self.assertTrue(all(dict(world.roles)["part_timer"] == "brain"
                            for world, _ in solved.ranked))

    def test_exact_final_map_matches_small_exhaustive_map(self):
        evidence = PublicEvidence.from_view(
            Game(example_scenario("BTX")).protagonist_team_view())
        witnesses = (
            PublicWitness("plot_pressure", "bomb", True, 1, 4,
                          "loop_end", "test", WitnessStrength.SOFT),
            PublicWitness("joint_plot_role_pressure", "bomb",
                          {"role": "witch", "candidates": ("girl",)},
                          1, 4, "loop_end", "test", WitnessStrength.SOFT),
        )
        tracker = FactorizedBeliefState(capacity=100_000, seed=3)
        exhaustive = tracker.role_posterior(evidence, witnesses)
        solved = tracker.exact_role_map(evidence, witnesses)
        expected, expected_weight = max(
            exhaustive,
            key=lambda pair: (pair[1], tuple(sorted(pair[0].roles)),
                              pair[0].main_plot, pair[0].subplots))
        # The old role reservoir can omit otherwise legal identity assignments
        # when its one arbitrary incident composition is invalid.  The final
        # solver deliberately keeps the culprit dimension separate.
        self.assertGreaterEqual(solved.compatible_count, len(exhaustive))
        self.assertEqual(solved.selected.main_plot, expected.main_plot)
        self.assertEqual(solved.selected.subplots, expected.subplots)
        self.assertEqual(solved.selected.roles, expected.roles)
        self.assertEqual(solved.ranked[0][1], expected_weight)
        self.assertEqual(solved.selected.materialize(evidence)["cast"],
                         dict(solved.selected.roles))

    def test_exact_final_map_is_independent_of_action_particle_capacity(self):
        scenario = ScenarioLibrary().get(
            "official-btx-06-secret-that-was-kept")
        evidence = PublicEvidence.from_view(
            Game(scenario).protagonist_team_view())
        witnesses = (
            PublicWitness("plot_pressure", "bomb", True, 1, 7,
                          "loop_end", "test", WitnessStrength.SOFT),
            PublicWitness("joint_plot_role_pressure", "bomb",
                          {"role": "witch", "candidates": ("rich",)},
                          1, 7, "loop_end", "test", WitnessStrength.SOFT),
        )
        tiny = FactorizedBeliefState(capacity=1, seed=1).exact_role_map(
            evidence, witnesses)
        large = FactorizedBeliefState(capacity=512, seed=99).exact_role_map(
            evidence, witnesses)
        self.assertGreater(tiny.compatible_count, 192)
        self.assertEqual(tiny, large)
        self.assertEqual(tiny.selected.main_plot, "bomb")
        self.assertEqual(dict(tiny.selected.roles)["rich"], "witch")

    def test_revealed_culprit_changes_only_incident_dimension(self):
        evidence = PublicEvidence.from_view(Game(example_scenario("FS")).view("a"))
        tracker = FactorizedBeliefState(capacity=512, seed=19)
        first = tracker.sample(evidence, (), 12, rng=random.Random(3))
        self.assertTrue(first.worlds)
        self.assertGreater(first.role_candidates, 512)
        previous_roles = set(tracker._roles)
        day = evidence.schedule[0][0]
        culprit = evidence.characters[0]
        revealed = replace(evidence, known_culprits=((day, culprit),))
        second = tracker.sample(revealed, (), 12, rng=random.Random(4))
        self.assertTrue(second.worlds)
        self.assertTrue(previous_roles.issubset(set(tracker._roles)))
        self.assertEqual(dict(second.culprit_options)[day], 1)
        self.assertTrue(all(next(incident[3] for incident in world.incidents
                                 if incident[0] == day) == culprit
                            for world in second.worlds))

    def test_dark_cards_are_drawn_from_remaining_hand_without_reuse(self):
        pending = ({"actor": "m", "target": "girl", "card": None},
                   {"actor": "m", "target": "student", "card": "m_intrigue_1"})
        selected = DarkCardBelief.sample(
            pending, {"m": ["m_intrigue_1", "m_paranoia_1"]},
            rng=random.Random(1))
        self.assertEqual(selected, (("m", "m_paranoia_1", "girl"),
                                    ("m", "m_intrigue_1", "student")))

    def test_dark_card_history_bias_retains_uniform_exploration(self):
        events = ({"kind": "cards_revealed", "loop": 1, "round": 1,
                   "cards": ({"actor": "m", "card": "v", "target": "girl"},)},)
        weights = DarkCardBelief.historical_weights(events, day=1, loop=2)
        self.assertGreater(weights[("girl", "v")], 0)
        self.assertGreater(DarkCardBelief.historical_weights(
            events, day=2, loop=2)[("girl", "v")], 0)
        rng = random.Random(17)
        cards = [DarkCardBelief.sample(
            ({"actor": "m", "target": "girl", "card": None},),
            {"m": ["v", "i1"]}, rng=rng,
            historical_weights=weights)[0][1] for _ in range(200)]
        self.assertGreater(cards.count("v"), cards.count("i1"))
        self.assertIn("i1", cards)
        forced = DarkCardBelief.sample(
            ({"actor": "m", "target": "girl", "card": None},),
            {"m": ["v", "i1"]}, rng=random.Random(2),
            historical_weights=weights, force_history=True)
        self.assertEqual(forced[0][1], "v")
        posterior = DarkCardBelief.placement_tendencies(
            events, day=1, loop=2, days=4,
            targets=("girl", "student"), cards=("v", "i1"))
        self.assertGreater(posterior[0]["card_probabilities"]["v"],
                           posterior[0]["card_probabilities"]["i1"])
        self.assertGreater(posterior[0]["target_probability"],
                           posterior[1]["target_probability"])
        self.assertAlmostEqual(sum(posterior[0]["card_probabilities"].values()), 1.0)


class PublicEvidenceTests(unittest.TestCase):
    def test_public_setup_excludes_copycat_source_and_is_detached(self):
        scenario = example_scenario('BTX')
        scenario['cast']['copycat'] = 'ordinary'
        source = next(cid for cid, role in scenario['cast'].items()
                      if cid != 'copycat' and role == 'ordinary')
        scenario['character_options'] = {'copycat': {'role_source': source}}
        game = Game(scenario)
        view = game.view('a')
        self.assertNotIn('copycat', view['public_setup']['character_options'])
        view['public_setup']['special_rules']['disabled_mastermind_cards'] = ['fg']
        self.assertNotIn('disabled_mastermind_cards',
                         game.scenario.get('special_rules', {}))

    def test_evidence_ignores_scenario_identity_and_unrevealed_secrets(self):
        game = Game(example_scenario("BTX"))
        view = game.view("a")
        original = PublicEvidence.from_view(view)

        disguised = dict(view)
        disguised["scenario_id"] = "must-not-be-used"
        disguised["title"] = "must-not-be-used"
        self.assertEqual(PublicEvidence.from_view(disguised), original)
        self.assertFalse(original.known_roles)
        self.assertFalse(original.known_culprits)
        self.assertFalse(original.known_plots)

    def test_catalog_candidates_obey_public_reveals(self):
        game = Game(example_scenario("BTX"))
        view = game.view("a")
        sampler = CatalogBeliefSampler()
        evidence = PublicEvidence.from_view(view)
        candidates = sampler.candidates(evidence)
        self.assertTrue(candidates)
        self.assertIn(game.scenario["id"], {item.scenario_id for item in candidates})

        revealed = dict(view)
        revealed["known_roles"] = {"girl": {"role": "key", "loop": 1, "day": 1}}
        filtered = sampler.candidates(PublicEvidence.from_view(revealed))
        self.assertTrue(filtered)
        self.assertTrue(all(dict(item.roles)["girl"] == "key" for item in filtered))

    def test_sampling_is_seeded_and_empty_sets_do_not_fall_back_to_truth(self):
        view = Game(example_scenario("FS")).view("a")
        sampler = CatalogBeliefSampler()
        evidence = PublicEvidence.from_view(view)
        first = sampler.sample(evidence, 5, rng=random.Random(9))
        second = sampler.sample(evidence, 5, rng=random.Random(9))
        self.assertEqual(first, second)

        impossible = PublicEvidence(
            evidence.module, evidence.days, evidence.loops, evidence.table_talk,
            evidence.characters, evidence.schedule,
            ((evidence.characters[0], "not-a-role"),), (), ())
        self.assertEqual(sampler.sample(impossible, 2, rng=random.Random(1)), ())

    def test_invalid_particle_count_is_rejected(self):
        evidence = PublicEvidence.from_view(Game(example_scenario("FS")).view("a"))
        with self.assertRaises(ValueError):
            CatalogBeliefSampler().sample(evidence, 0, rng=random.Random(1))


class ConstraintBeliefSamplerTests(unittest.TestCase):
    def test_irregular_uses_an_extra_unselected_role_slot(self):
        scenario = ScenarioLibrary().get("official-btx-08-mirror-passcode")
        evidence = PublicEvidence.from_view(
            Game(scenario).protagonist_team_view())
        worlds = ConstraintBeliefSampler().sample(
            evidence, 12, rng=random.Random(18), max_attempts=20_000)
        self.assertEqual(len(worlds), 12)
        for world in worlds:
            selected = {role for plot in (world.main_plot, *world.subplots)
                        for role in PLOTS[plot][2]}
            self.assertNotIn(dict(world.roles)["irregular"], selected)

        posterior = FactorizedBeliefState(seed=18).role_posterior(evidence, ())
        self.assertTrue(posterior)

    def test_generates_multiple_valid_worlds_without_catalog_identity(self):
        game = Game(example_scenario("BTX"))
        evidence = PublicEvidence.from_view(game.view("a"))
        worlds = ConstraintBeliefSampler().sample(
            evidence, 12, rng=random.Random(21))
        self.assertEqual(len(worlds), 12)
        self.assertGreater(len({world.main_plot for world in worlds}), 1)
        self.assertTrue(all(set(dict(world.roles)) == set(evidence.characters)
                            for world in worlds))
        self.assertTrue(all(tuple((day, public) for day, _, public, _ in world.incidents)
                            == evidence.schedule for world in worlds))
        self.assertTrue(all(world.scenario_id.startswith("belief-") for world in worlds))

    def test_public_reveals_are_hard_constraints(self):
        view = Game(example_scenario("BTX")).view("a")
        view["known_roles"] = {"girl": {"role": "key", "loop": 1, "day": 1}}
        view["known_culprits"] = {"2": "doctor"}
        view["known_plots"] = ["rumor"]
        evidence = PublicEvidence.from_view(view)
        worlds = ConstraintBeliefSampler().sample(
            evidence, 8, rng=random.Random(4))
        self.assertEqual(len(worlds), 8)
        for world in worlds:
            self.assertEqual(dict(world.roles)["girl"], "key")
            self.assertIn("rumor", world.subplots)
            self.assertEqual(next(culprit for day, _, _, culprit in world.incidents
                                  if day == 2), "doctor")

    def test_generation_is_seeded_across_all_rulesets(self):
        for module in ("FS", "BTX", "MZ", "MC", "HSA", "WM", "AHR", "LL"):
            with self.subTest(module=module):
                evidence = PublicEvidence.from_view(
                    Game(example_scenario(module)).view("a"))
                first = ConstraintBeliefSampler().sample(
                    evidence, 3, rng=random.Random(7))
                second = ConstraintBeliefSampler().sample(
                    evidence, 3, rng=random.Random(7))
                self.assertEqual(first, second)
                self.assertEqual(len(first), 3)


class ParticleReplayTests(unittest.TestCase):
    def test_public_snapshot_ignores_identity_labels_and_localized_messages(self):
        view = Game(example_scenario("BTX")).view("a")
        original = PublicSnapshot.from_view(view)
        changed = dict(view)
        changed["scenario_id"] = "not-evidence"
        changed["title"] = "not-evidence"
        changed["language"] = "en"
        changed["labels"] = {"not": "evidence"}
        changed["events"] = [dict(event, message="translated", timepoint="translated")
                             for event in view["events"]]
        self.assertEqual(PublicSnapshot.from_view(changed), original)
        self.assertEqual(PublicSnapshot.from_view(
            Game(example_scenario("BTX")).view("a", language="en")), original)
        self.assertEqual(len(original.digest), 16)

        changed_counter = deepcopy(view)
        changed_counter["characters"]["girl"]["intrigue"] += 1
        self.assertNotEqual(PublicSnapshot.from_view(changed_counter), original)

    def test_actual_particle_replays_to_the_same_public_snapshot(self):
        initial = Game(example_scenario("FS"))
        game = initial
        for _ in range(8):
            action = game.search_actions(game.controller)[0]
            game = game.transition(action).game
        evidence = PublicEvidence.from_view(initial.view("a"))
        hypothesis = HiddenWorldHypothesis.from_scenario(initial.scenario)
        result = ParticleReplayer().replay(
            hypothesis, evidence, game.history, viewer="a",
            expected=PublicSnapshot.from_view(game.view("a")))
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(result.decisions, len(game.history))
        self.assertEqual(PublicSnapshot.from_view(result.game.view("a")),
                         PublicSnapshot.from_view(game.view("a")))

    def test_illegal_public_command_and_mismatched_phenomenon_reject_particle(self):
        initial = Game(example_scenario("BTX"))
        evidence = PublicEvidence.from_view(initial.view("a"))
        hypothesis = HiddenWorldHypothesis.from_scenario(initial.scenario)
        illegal = ParticleReplayer().replay(
            hypothesis, evidence,
            [{"actor": "a", "action": "next"}], viewer="a")
        self.assertFalse(illegal.accepted)
        self.assertEqual(illegal.reason, "public_command_illegal")

        impossible_view = deepcopy(initial.view("a"))
        impossible_view["locations"]["school"] = 9
        mismatch = ParticleReplayer().replay(
            hypothesis, evidence, (), viewer="a",
            expected=PublicSnapshot.from_view(impossible_view))
        self.assertFalse(mismatch.accepted)
        self.assertEqual(mismatch.reason, "public_snapshot_mismatch")


class ObservationParticleAdvancerTests(unittest.TestCase):
    def test_public_reveal_can_bridge_unseen_dark_card_particle(self):
        actual = Game(example_scenario("FS"))
        while actual.state.phase != "reveal":
            command = actual.search_actions(actual.controller)[0]
            actual = actual.search_transition(command)
        particle = deepcopy(actual)
        dark = next(item for item in particle.state.pending
                    if item.actor == "m")
        alternate = next(card for card in particle.state.hands["m"]
                         if card != dark.card)
        particle.state.hands["m"].remove(alternate)
        particle.state.hands["m"].append(dark.card)
        particle.state.pending = [
            type(item)(item.actor, alternate if item is dark else item.card,
                       item.target)
            for item in particle.state.pending]
        disclosed = [{"actor": item.actor, "card": item.card,
                      "target": item.target} for item in actual.state.pending]
        bridged = PersistentBeliefState._condition_reveal(particle, disclosed)
        self.assertIsNotNone(bridged)
        self.assertEqual([(item.actor, item.card, item.target)
                          for item in bridged.state.pending],
                         [(item.actor, item.card, item.target)
                          for item in actual.state.pending])
        self.assertEqual(particle.state.pending[0].card, alternate)

    def test_first_loop_incident_can_branch_hidden_culprit(self):
        game = Game(example_scenario("FS"))
        game.state.phase = "incident"
        game.state.round = game.scenario["incidents"][0]["day"]
        original = next(item["culprit"] for item in game.scenario["incidents"]
                        if item["day"] == game.state.round)
        evidence = PublicEvidence.from_view(game.view("a"))
        variants = PersistentBeliefState._incident_variants(
            game, evidence, True)
        self.assertEqual(len(variants), len(evidence.characters))
        self.assertEqual(next(item["culprit"] for item in game.scenario["incidents"]
                              if item["day"] == game.state.round), original)
        self.assertEqual({next(item["culprit"] for item in world.scenario["incidents"]
                               if item["day"] == world.state.round)
                          for world in variants}, set(evidence.characters))

    def test_hidden_action_is_inferred_from_public_consequence(self):
        game = Game(example_scenario("BTX"))
        command = game.search_actions("m")[0]
        actual = game.transition(command).game
        result = ObservationParticleAdvancer().advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")))
        self.assertEqual(result.tested_actions, 1)
        self.assertEqual(len(result.successors), 1)
        self.assertEqual(PublicSnapshot.from_view(result.successors[0].view("a")),
                         PublicSnapshot.from_view(actual.view("a")))

    def test_unrevealed_card_keeps_all_observationally_equivalent_actions(self):
        game = Game(example_scenario("BTX"))
        game = game.transition(game.search_actions("m")[0]).game
        actual_command = game.search_actions("m")[17]
        actual = game.transition(actual_command).game
        result = ObservationParticleAdvancer().advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")))
        self.assertGreater(result.tested_actions, 20)
        self.assertGreater(len(result.successors), 1)
        self.assertTrue(all(PublicSnapshot.from_view(item.view("a")) ==
                            PublicSnapshot.from_view(actual.view("a"))
                            for item in result.successors))

    def test_public_command_restricts_branch_and_limits_are_validated(self):
        game = Game(example_scenario("FS"))
        command = game.search_actions("m")[0]
        actual = game.transition(command).game
        advancer = ObservationParticleAdvancer()
        result = advancer.advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")),
            public_command=command)
        self.assertEqual((result.tested_actions, len(result.successors)), (1, 1))
        rejected = advancer.advance(
            game, viewer="a", observed=PublicSnapshot.from_view(actual.view("a")),
            public_command={"actor": "a", "action": "next"})
        self.assertEqual((rejected.tested_actions, rejected.successors), (0, ()))
        with self.assertRaises(ValueError):
            advancer.advance(game, viewer="a",
                             observed=PublicSnapshot.from_view(game.view("a")),
                             max_successors=0)


class ObservationCheckpointTests(unittest.TestCase):
    def test_real_dispatch_records_only_public_snapshot_digests(self):
        game = Game(example_scenario("BTX"))
        initial = game.observation_checkpoints("a")
        self.assertEqual(len(initial), 1)
        self.assertEqual(initial[0],
                         (0, PublicSnapshot.from_view(game.view("a")).digest))
        action = game.search_actions("m")[0]
        game.dispatch("m", action["action"])
        checkpoints = game.observation_checkpoints("a")
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[-1],
                         (1, PublicSnapshot.from_view(game.view("a")).digest))
        self.assertNotIn("next", repr(checkpoints))

    def test_simulation_does_not_append_real_observation_history(self):
        game = Game(example_scenario("FS"))
        action = game.action_offers("m")[0]
        successor = game.transition(action).game
        self.assertEqual(len(game.observation_checkpoints("a")), 1)
        self.assertEqual(len(successor.observation_checkpoints("a")), 1)

    def test_checkpoint_digest_can_drive_hidden_particle_advance(self):
        game = Game(example_scenario("BTX"))
        action = game.search_actions("m")[0]
        game.dispatch("m", action["action"])
        observed_digest = game.observation_checkpoints("a")[-1][1]
        initial = Game(example_scenario("BTX"))
        result = ObservationParticleAdvancer().advance(
            initial, viewer="a", observed=observed_digest)
        self.assertEqual(len(result.successors), 1)

    def test_visible_command_records_never_expose_an_opponents_dark_card(self):
        game = Game(example_scenario("BTX"))
        while game.controller == "m":
            command = game.search_actions("m")[0]
            game.dispatch(command["actor"], command["action"],
                          **{key: value for key, value in command.items()
                             if key not in {"actor", "action"}})
        self.assertTrue(all(
            item["card"] is None
            for item in game.protagonist_team_view()["pending"]
            if item["actor"] == "m"))
        own = game.search_actions(game.controller)[0]
        owner = own["actor"]
        game.dispatch(owner, own["action"],
                      **{key: value for key, value in own.items()
                         if key not in {"actor", "action"}})
        owner_record = game.observation_records(owner)[-1][2]
        other = next(seat for seat in ("a", "b", "c") if seat != owner)
        other_record = game.observation_records(other)[-1][2]
        self.assertEqual(owner_record.visibility, "public")
        self.assertEqual(owner_record.pattern["card"], own["card"])
        self.assertEqual(other_record.visibility, "partial")
        self.assertIn("card", other_record.hidden_fields)
        self.assertNotIn("card", other_record.pattern)
        self.assertEqual(other_record.pattern["target"], own["target"])
        hidden = [record for _, _, record in game.observation_records(owner)
                  if record is not None and record.visibility == "hidden"]
        self.assertTrue(hidden)
        self.assertTrue(all(record.pattern is None for record in hidden))

        teammate = game.search_actions(game.controller)[0]
        game.dispatch(teammate["actor"], teammate["action"],
                      **{key: value for key, value in teammate.items()
                         if key not in {"actor", "action"}})
        team_record = game.observation_records("team")[-1][2]
        seat_record = game.observation_records(owner)[-1][2]
        self.assertEqual(team_record.visibility, "public")
        self.assertEqual(team_record.pattern["card"], teammate["card"])
        self.assertEqual(seat_record.visibility, "partial")
        pending = {item["actor"]: item for item in game.protagonist_team_view()["pending"]}
        self.assertEqual(pending[teammate["actor"]]["card"], teammate["card"])


class PersistentBeliefStateTests(unittest.TestCase):
    def test_particles_advance_across_all_public_checkpoints(self):
        game = Game(example_scenario("BTX"))
        for _ in range(2):
            command = game.search_actions("m")[0]
            game.dispatch(command["actor"], command["action"],
                          **{key: value for key, value in command.items()
                             if key not in {"actor", "action"}})
        evidence = PublicEvidence.from_view(game.view("a"))
        tracker = PersistentBeliefState(max_particles=4, seed=91)
        result = tracker.sync(
            evidence, viewer="a", observations=game.observation_records("a"))
        self.assertTrue(result.initialized)
        self.assertEqual(result.processed, 2)
        self.assertTrue(result.particles)
        expected = game.observation_checkpoints("a")[-1][1]
        self.assertTrue(all(
            PublicSnapshot.from_view(item.view("a")).digest == expected
            for item in result.particles))

        unchanged = tracker.sync(
            evidence, viewer="a", observations=game.observation_records("a"))
        self.assertFalse(unchanged.initialized)
        self.assertEqual(unchanged.processed, 0)


class BeliefParticleFilterTests(unittest.TestCase):
    @staticmethod
    def initial_particles():
        source = Game(example_scenario("BTX"))
        evidence = PublicEvidence.from_view(source.view("a"))
        hypotheses = ConstraintBeliefSampler().sample(
            evidence, 4, rng=random.Random(31))
        particles = BeliefParticleFilter.materialize(hypotheses, evidence)
        return source, particles

    def test_hidden_wide_branch_is_bounded_without_collapsing_to_one_answer(self):
        source, particles = self.initial_particles()
        first = source.search_actions("m")[0]
        source = source.transition(first).game
        filterer = BeliefParticleFilter(max_particles=12, rng=random.Random(5))
        setup = filterer.advance(
            particles, viewer="a",
            observed=PublicSnapshot.from_view(source.view("a")))
        self.assertEqual(len(setup.particles), len(particles))

        hidden = source.search_actions("m")[23]
        observed_game = source.transition(hidden).game
        result = filterer.advance(
            setup.particles, viewer="a",
            observed=PublicSnapshot.from_view(observed_game.view("a")))
        self.assertEqual(result.input_particles, len(particles))
        self.assertGreater(result.matching_successors, 20)
        self.assertGreater(result.unique_successors, 12)
        self.assertEqual(len(result.particles), 12)
        self.assertGreater(len({item.state_key("m") for item in result.particles}), 1)
        expected = PublicSnapshot.from_view(observed_game.view("a"))
        self.assertTrue(all(PublicSnapshot.from_view(item.view("a")) == expected
                            for item in result.particles))

    def test_resampling_is_seeded_and_contradictions_eliminate_all_particles(self):
        source, particles = self.initial_particles()
        source = source.transition(source.search_actions("m")[0]).game
        particles = BeliefParticleFilter(max_particles=16).advance(
            particles, viewer="a",
            observed=PublicSnapshot.from_view(source.view("a"))).particles
        observed = PublicSnapshot.from_view(
            source.transition(source.search_actions("m")[7]).game.view("a"))

        def keys():
            result = BeliefParticleFilter(
                max_particles=7, rng=random.Random(18)).advance(
                    particles, viewer="a", observed=observed)
            return tuple(item.state_key("m") for item in result.particles)

        sampled = keys()
        self.assertEqual(sampled, keys())
        self.assertEqual(len(sampled), 7)
        impossible = "0" * 16
        rejected = BeliefParticleFilter(max_particles=7).advance(
            particles, viewer="a", observed=impossible)
        self.assertFalse(rejected.particles)
        self.assertEqual(rejected.matching_successors, 0)

    def test_particle_limit_is_validated(self):
        with self.assertRaises(ValueError):
            BeliefParticleFilter(max_particles=0)


if __name__ == "__main__":
    unittest.main()
