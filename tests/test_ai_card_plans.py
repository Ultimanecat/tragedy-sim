"""Joint AI execution is equivalent to the retained single-card API."""

import json
import unittest
from unittest.mock import patch

from tragedy_sim import Game
from tragedy_sim.ai_decisions import JointCardDecisionProvider
from tragedy_sim.ismcts import IsmctsProtagonistAgent
from tragedy_sim.joint_mastermind import JointPlanMastermindAgent
from tragedy_sim.oracle_protagonist import (FullCardOracleProtagonistAgent,
                                          HiddenCardOracleProtagonistAgent)
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.search import SearchBudget
from tragedy_sim.service import GameService, ServiceError
from tragedy_sim.scenario import example_scenario
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.replay import dumps as replay_dumps
from tests import test_card_plans as card_tests


class AiCardPlanTests(unittest.TestCase):
    def test_complete_match_and_text_replay_match_single_execution(self):
        scenario = example_scenario('FS')
        scenario['days'] = 1
        scenario['loops'] = 2
        scenario['incidents'] = [item for item in scenario['incidents'] if item['day'] <= 1]

        def run(batch_enabled):
            service = GameService()
            session = service.create_game({'scenario': scenario})
            sid, admin = session['session_id'], session['credentials']['admin']
            budget = SearchBudget(node_limit=2, rollout_depth=3, seed=7)
            black = JointPlanMastermindAgent(budget, reply_nodes=2)
            red = ParticleEnsembleProtagonistAgent(budget, particle_count=4, rng_seed=7)
            batches = 0
            for _ in range(200):
                game = service.unsafe_game(sid)
                if game.winner is not None:
                    return game, batches
                actor = game.controller
                actions = service.get_actions(sid, actor, token=admin)
                policy = black if actor == 'm' else red
                if actor == 'm':
                    offer = policy.choose_game_action(participant=actor,
                        game=game.clone(), offers=actions['actions'])
                else:
                    offer = policy.choose_action(participant='team',
                        view=game.protagonist_team_view(), offers=actions['actions'])
                decision = policy.decision_for_action(offer)
                if batch_enabled and decision.card_plan:
                    service.dispatch_card_plan(sid, {'actor': actor,
                        'expected_revision': actions['revision'],
                        'plays': [play.payload() for play in decision.card_plan]}, token=admin)
                    policy.clear_card_plan()
                    batches += 1
                else:
                    request = {'action_id': offer['id'], 'expected_revision': actions['revision']}
                    if offer.get('arguments') is not None:
                        request['arguments'] = offer['arguments']
                    service.dispatch(sid, request, token=admin)
            self.fail('match did not terminate')

        single, _ = run(False)
        batch, batches = run(True)
        self.assertGreaterEqual(batches, 2)
        self.assertEqual(batch.winner, single.winner)
        self.assertEqual(batch.history, single.history)
        self.assertEqual(batch.view('m'), single.view('m'))
        self.assertEqual(batch.observation_records('team'), single.observation_records('team'))
        self.assertEqual(replay_dumps(batch), replay_dumps(single))

    def test_actual_ai_batch_matches_three_single_decisions(self):
        budget = SearchBudget(node_limit=2, rollout_depth=3, seed=5)
        factories = {
            'joint': lambda: JointPlanMastermindAgent(budget, reply_nodes=2),
            'particle': lambda: ParticleEnsembleProtagonistAgent(
                budget, particle_count=4, rng_seed=5),
            'ismcts': lambda: IsmctsProtagonistAgent(budget, particle_count=4, rng_seed=5),
            'oracle_cards': lambda: FullCardOracleProtagonistAgent(budget, rng_seed=5),
            'oracle_script': lambda: HiddenCardOracleProtagonistAgent(budget, rng_seed=5),
        }
        scenarios = [example_scenario('FS'), example_scenario('BTX')]
        library = ScenarioLibrary()
        scenarios.extend(library.get(item['id']) for item in library.list()
                         if item['source'] == 'library' and item['module'] in {'FS', 'BTX'}
                         and not item['id'].endswith(('-easy', '-very-easy')))
        for scenario in scenarios:
            for mode, factory in factories.items():
                # Exhaustive strategy adapters on examples; production joint
                # planners additionally cover every recorded standard script.
                if scenario not in scenarios[:2] and mode not in {'joint', 'particle'}:
                    continue
                with self.subTest(scenario=scenario['id'], mode=mode):
                    root = Game(scenario)
                    while root.state.phase != 'mastermind':
                        root = root.search_transition(root.search_actions(root.controller)[0])
                    actor = 'm' if mode == 'joint' else 'a'
                    if actor != 'm':
                        draft_service = GameService()
                        draft = draft_service.create_game(game=root)
                        plan = draft_service.get_card_plan(draft['session_id'], 'm',
                            token=draft['credentials']['admin'])
                        for play in card_tests.choose_plays(plan):
                            root.dispatch('m', 'play', card=play['card'], target=play['target'])
                    service = GameService()
                    left = service.create_game(game=root.clone())
                    right = service.create_game(game=root.clone())
                    single, batch = factory(), factory()

                    def choose(agent, session):
                        game = service.unsafe_game(session['session_id'])
                        seat = game.controller
                        offers = service.get_actions(session['session_id'], seat,
                            token=session['credentials']['admin'])['actions']
                        if hasattr(agent, 'choose_game_action'):
                            return agent.choose_game_action(participant=seat, game=game.clone(),
                                offers=offers, **({'public_view': game.protagonist_team_view()}
                                    if actor != 'm' else {}))
                        return agent.choose_action(participant='team',
                            view=game.protagonist_team_view(), offers=offers)

                    first = choose(batch, right)
                    initial_revision = service.get_view(right['session_id'])['revision']
                    decision = batch.decision_for_action(first)
                    self.assertEqual(len(decision.card_plan), 3)
                    invalid = [play.payload() for play in decision.card_plan]
                    invalid[2]['target'] = invalid[0]['target']
                    unchanged = service.unsafe_game(right['session_id'])
                    before_failure = unchanged.clone()
                    with self.assertRaises(ServiceError) as failure:
                        service.dispatch_card_plan(right['session_id'], {
                            'actor': actor, 'expected_revision': initial_revision,
                            'plays': invalid,
                        }, token=right['credentials']['admin'])
                    self.assertEqual(failure.exception.code, 'RULE_VIOLATION')
                    self.assertIs(service.unsafe_game(right['session_id']), unchanged)
                    self.assertEqual(unchanged.history, before_failure.history)
                    self.assertEqual(unchanged.observation_records('team'),
                                     before_failure.observation_records('team'))
                    self.assertEqual(service.get_view(right['session_id'])['revision'],
                                     initial_revision)
                    # Diagnostic traces cannot serve as the execution API.
                    batch.last_trace = None
                    result = service.dispatch_card_plan(right['session_id'], {
                        'actor': actor, 'expected_revision': initial_revision,
                        'plays': [play.payload() for play in decision.card_plan],
                    }, token=right['credentials']['admin'])
                    batch.clear_card_plan()
                    self.assertFalse(batch.remaining_card_commands())
                    for expected in decision.card_plan:
                        selected = choose(single, left)
                        self.assertEqual((selected['actor'], selected['parameters']),
                                         (expected.actor, {'card': expected.card,
                                                           'target': expected.target}))
                        revision = service.get_view(left['session_id'])['revision']
                        service.dispatch(left['session_id'], {'action_id': selected['id'],
                            'expected_revision': revision}, token=left['credentials']['admin'])
                    actual = service.unsafe_game(right['session_id'])
                    reference = service.unsafe_game(left['session_id'])
                    self.assertEqual(result['revision'], initial_revision + 3)
                    self.assertEqual(actual.history, reference.history)
                    self.assertEqual(actual.decisions, reference.decisions)
                    for viewer in ('m', 'a', 'b', 'c', 'spectator', 'team'):
                        if viewer in ('a', 'b', 'c', 'team'):
                            self.assertEqual(actual.observation_records(viewer),
                                             reference.observation_records(viewer))
                        projection = (lambda game: game.protagonist_team_view()) if viewer == 'team' else (
                            lambda game: game.view(viewer))
                        self.assertEqual(projection(actual), projection(reference))
                    # Resolving the cards must also remain equivalent.
                    if actor != 'm':
                        actual.dispatch('m', 'resolve')
                        reference.dispatch('m', 'resolve')
                    self.assertEqual(actual.view('m'), reference.view('m'))

    def test_partial_and_non_card_decisions_stay_single(self):
        class Provider(JointCardDecisionProvider):
            def remaining_card_commands(self):
                return ({'actor': 'b', 'action': 'play', 'card': 'g1', 'target': 'doctor'},)
        provider = Provider()
        self.assertFalse(provider.decision_for_action({'type': 'next'}).card_plan)
        self.assertFalse(provider.decision_for_action({'actor': 'a', 'type': 'play',
            'parameters': {'card': 'g1', 'target': 'girl'}}).card_plan)


class AiRoomCardPlanTests(unittest.TestCase):
    def prepare(self, actor='a', count=1):
        card_tests.RoomCardPlanTests.setup_room(self, count)
        if actor != 'm':
            card_tests.RoomCardPlanTests.submit(self, 'm')
        return self.rooms._rooms[self.code]

    def test_room_uses_one_batch_and_records_each_card_once(self):
        budget = SearchBudget(node_limit=2, rollout_depth=3, seed=2)
        for actor, count in (('m', 1), ('m', 3), ('a', 1)):
            with self.subTest(actor=actor, count=count):
                room = self.prepare(actor, count)
                occupant = room.seats[actor]
                occupant.ai = True
                occupant.ai_policy = (JointPlanMastermindAgent(budget, reply_nodes=2)
                    if actor == 'm' else ParticleEnsembleProtagonistAgent(
                        budget, particle_count=4, rng_seed=2))
                before = self.rooms.games.unsafe_game(room.session_id).clone()
                executor_count = len(room.executors)
                with (patch.object(self.rooms.games, 'dispatch_card_plan',
                                   wraps=self.rooms.games.dispatch_card_plan) as batch,
                      patch.object(self.rooms.games, 'dispatch',
                                   wraps=self.rooms.games.dispatch) as single,
                      patch.object(room.changed, 'notify_all') as notify):
                    with room.lock:
                        self.rooms._run_ai_turns(room)
                    batch.assert_called_once()
                    single.assert_not_called()
                    notify.assert_called_once()
                plays = batch.call_args.args[1]['plays']
                for play in plays:
                    before.dispatch(play['actor'], 'play', card=play['card'], target=play['target'])
                actual = self.rooms.games.unsafe_game(room.session_id)
                self.assertEqual(actual.view('m'), before.view('m'))
                self.assertEqual(actual.history, before.history)
                recorded = room.executors[executor_count:]
                self.assertEqual(len(recorded), 3)
                self.assertEqual([record['actor'] for record in recorded],
                                 [play['actor'] for play in plays])
                self.assertTrue(all(record['participant'] == actor for record in recorded))
                self.assertEqual(len(room.ai_debug_traces), 1)
                self.assertFalse(occupant.ai_policy.remaining_card_commands())
                # Snapshot reload reproduces the exact underlying command history.
                snapshot = self.rooms.games.get_snapshot(room.session_id,
                    token=room.game_admin)['snapshot']
                reloaded = GameService().create_game({'snapshot': snapshot})
                self.assertEqual(reloaded['view']['state'],
                                 json.loads(json.dumps(actual.view('spectator'))))

    def test_stale_batch_replans_and_invalid_batch_does_not_fall_back(self):
        for code in ('STALE_REVISION', 'RULE_VIOLATION'):
            with self.subTest(code=code):
                room = self.prepare()
                occupant = room.seats['a']
                occupant.ai = True
                policy = ParticleEnsembleProtagonistAgent(
                    SearchBudget(node_limit=2, rollout_depth=3), particle_count=4)
                occupant.ai_policy = policy
                original = self.rooms.games.dispatch_card_plan
                before = self.rooms.games.unsafe_game(room.session_id).clone()
                executor_count = len(room.executors)
                attempts = []

                def reject_once(*args, **kwargs):
                    attempts.append(args[1])
                    if len(attempts) == 1:
                        raise ServiceError(code, 'test failure', status=409)
                    return original(*args, **kwargs)

                with (patch.object(self.rooms.games, 'dispatch_card_plan', side_effect=reject_once),
                      patch.object(policy, 'choose_action', wraps=policy.choose_action) as choose,
                      patch.object(self.rooms.games, 'dispatch') as single,
                      patch.object(room.changed, 'notify_all') as notify):
                    with room.lock:
                        if code == 'STALE_REVISION':
                            self.rooms._run_ai_turns(room)
                            self.assertEqual(choose.call_count, 2)
                            notify.assert_called_once()
                            self.assertEqual(len(room.executors), executor_count + 3)
                        else:
                            with self.assertRaises(ServiceError):
                                self.rooms._run_ai_turns(room)
                            notify.assert_not_called()
                            self.assertEqual(len(room.executors), executor_count)
                            self.assertEqual(self.rooms.games.unsafe_game(room.session_id).history,
                                             before.history)
                    single.assert_not_called()
                self.assertFalse(policy.remaining_card_commands())

    def test_multiplayer_protagonists_keep_single_submission(self):
        for count in (2, 3):
            with self.subTest(count=count):
                room = self.prepare(count=count)
                # A provider must not grant authority over teammates.
                class SeatPolicy(JointCardDecisionProvider):
                    controls_protagonist_team = False

                    def remaining_card_commands(self):
                        return ({'actor': 'b', 'action': 'play', 'card': 'g1', 'target': 'doctor'},
                                {'actor': 'c', 'action': 'play', 'card': 'g1', 'target': 'maiden'})

                    def choose_action(self, *, participant, view, offers):
                        self.view = view
                        return offers[0]

                policy = SeatPolicy()
                room.seats['a'].ai = True
                room.seats['a'].ai_policy = policy
                with (patch.object(self.rooms.games, 'dispatch_card_plan') as batch,
                      patch.object(self.rooms.games, 'dispatch',
                                   wraps=self.rooms.games.dispatch) as single):
                    with room.lock:
                        self.rooms._run_ai_turns(room)
                    batch.assert_not_called()
                    single.assert_called_once()
                self.assertNotIn('team_hands', policy.view)
