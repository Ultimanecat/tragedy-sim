"""Architecture fitness tests for ruleset extension points introduced in R1."""

from dataclasses import dataclass, field, replace
import json
import unittest

from tragedy_sim import Game, Observation, TimingId, Visibility
from tragedy_sim.domain import (
    ActionOffer, Activation, ActivationMode, ComponentStore, CORE_PHASES,
    CounterChange, CustomEffect, FlowPlan, LegacyEffect, PhaseKey,
    ResolutionTrace, RuleContext, RuleSource, SourcedEffect, StateComponent,
    TimingResolver, normalize_effect,
)
from tragedy_sim.effects.vocabulary import op, option
from tragedy_sim.phases.base import PhaseResolver


@dataclass
class AhrWorldState(StateComponent):
    component_key = "ahr.world"
    hidden: bool = False
    pending_shift: bool = False


@dataclass
class HsaCurseState(StateComponent):
    component_key = "hsa.board_curses"
    boards: dict[str, list[str]] = field(default_factory=dict)


class DomainContractTests(unittest.TestCase):
    def test_mandatory_window_freezes_triggers_before_optional_requery(self):
        state = {"enabled": True}
        context = RuleContext(state, {}, "test", CORE_PHASES["day_end"],
                              TimingId.DAY_END, ComponentStore())

        class ExampleRule:
            def activations(self, current):
                if not current.state["enabled"]:
                    return ()
                return (
                    Activation(RuleSource("test.first"), current.timing,
                               ActivationMode.MANDATORY, "m",
                               (CounterChange("student", "paranoia", 1),)),
                    Activation(RuleSource("test.second"), current.timing,
                               ActivationMode.MANDATORY, "m",
                               (CounterChange("girl", "paranoia", 1),)),
                    Activation(RuleSource("test.optional"), current.timing,
                               ActivationMode.OPTIONAL, "m"),
                )

        resolver = TimingResolver()
        window = resolver.begin(context, (ExampleRule(),))
        state["enabled"] = False  # Mandatory triggers and context were fixed together.
        self.assertTrue(window.context.state["enabled"])
        self.assertEqual([item.source.value for item in window.ordered((1, 0))],
                         ["test.second", "test.first"])
        self.assertEqual([effect.target for effect in window.effects((1, 0))],
                         ["girl", "student"])
        with self.assertRaises(RuntimeError):
            resolver.optional(window, context, (ExampleRule(),))
        window.start()
        window.finish_mandatory()
        self.assertEqual(resolver.optional(window, context, (ExampleRule(),)), ())
        window.close()
        with self.assertRaises(ValueError):
            window.ordered((0, 0))

    def test_namespaced_keys_and_replaceable_flow(self):
        with self.assertRaises(ValueError):
            PhaseKey("day_end")
        standard = FlowPlan((CORE_PHASES["loop_end"], CORE_PHASES["final_guess"],
                             CORE_PHASES["game_over"]))
        ll_battle = PhaseKey("ll.final_battle")
        replaced = standard.replace(CORE_PHASES["final_guess"], ll_battle)
        self.assertEqual(replaced.phases,
                         (CORE_PHASES["loop_end"], ll_battle, CORE_PHASES["game_over"]))
        self.assertEqual(standard.phases[1], CORE_PHASES["final_guess"])

    def test_action_offer_has_stable_text_independent_identity(self):
        command = {"actor": "a", "action": "play", "card": "move_h", "target": "girl"}
        first = ActionOffer.from_command(command, timing=TimingId.PROTAGONIST_ACTION,
                                         label="移动")
        translated = ActionOffer.from_command(command, timing=TimingId.PROTAGONIST_ACTION,
                                              label="Movement")
        changed = ActionOffer.from_command({**command, "target": "doctor"},
                                           timing=TimingId.PROTAGONIST_ACTION)
        self.assertEqual(first.id, translated.id)
        self.assertNotEqual(first.id, changed.id)
        self.assertEqual(first.command, command)
        json.dumps(first.to_dict(), ensure_ascii=False)

    def test_game_exposes_typed_offers_without_changing_legacy_commands(self):
        game = Game()
        command = game.legal_actions("m")[0]
        offer = game.action_offers("m")[0]
        self.assertEqual(offer.command, command)
        successor = game.simulate(**offer.command)
        self.assertNotEqual(successor.game.state_key("m"), game.state_key("m"))

    def test_typed_effects_cross_the_legacy_resolver_boundary(self):
        game = Game()
        before = game.state.characters["student"].goodwill
        game._queue = [CounterChange("student", "goodwill", 1)]
        game._return_phase = game.state.phase
        game._drain()
        self.assertEqual(game.state.characters["student"].goodwill, before + 1)
        self.assertEqual(normalize_effect(LegacyEffect("kill", {"target": "girl"})),
                         {"kind": "kill", "target": "girl"})

    def test_sourced_effect_creates_private_causal_trace_only(self):
        game = Game()
        game._queue = [SourcedEffect(CounterChange("student", "goodwill", 1),
                                     RuleSource("test.goodwill"))]
        game._return_phase = game.state.phase
        game._drain()
        trace = game.resolution_traces[-1]
        self.assertEqual(trace.source.value, "test.goodwill")
        self.assertEqual(trace.observations[0].kind, "counter_changed")
        public_json = json.dumps(game.view("spectator"), ensure_ascii=False)
        self.assertNotIn("test.goodwill", public_json)
        self.assertNotIn("resolution_traces", game.view("m"))

    def test_effect_source_survives_a_human_target_choice(self):
        game = Game()
        game._return_phase = game.state.phase
        game._queue = [SourcedEffect(
            LegacyEffect("choice", {"prompt": "test", "options": [
                option("change", [op("counter", target="student", counter="goodwill", amount=1)])
            ]}), RuleSource("test.choice"))]
        game._drain()
        game._choose("m", 1)
        self.assertEqual(game.resolution_traces[-1].source.value, "test.choice")
        self.assertEqual(game.resolution_traces[-1].observations[0].kind, "counter_changed")
        self.assertNotIn("activation_history", game.view("m"))

    def test_runtime_window_records_mandatory_before_optional(self):
        game = Game()
        game.state.phase = "master_abilities"
        game._return_phase = "master_abilities"
        game._open_timing_window(TimingId.MASTERMIND_ABILITY, [],
                                 "test.mandatory_window")
        self.assertEqual(game.activation_history[-1].mode, ActivationMode.MANDATORY)
        self.assertTrue(game._timing_optional_ready())
        selected = {"key": "test:optional", "effects": [
            op("counter", target="student", counter="goodwill", amount=1)
        ]}
        game._queue = game._optional_effects(selected, "m")
        game._drain()
        self.assertEqual(game.activation_history[-1].mode, ActivationMode.OPTIONAL)

    def test_namespaced_phase_can_execute_without_changing_core_enum(self):
        class ExtraPhase(PhaseResolver):
            phase = PhaseKey("test.extra_phase")

            def timing(self, game):
                return TimingId.PROTAGONIST_ABILITY

            def validate_command(self, action, arguments):
                if action != "invoke" or arguments:
                    raise ValueError("bad custom command")

            def controller(self, game):
                return "a"

            def legal_actions(self, game, actor):
                return [{"actor": actor, "action": "invoke"}] if actor == "a" else []

            def execute(self, game, actor, action, arguments):
                game.state.phase = "day_start"
                game._event("custom_phase", "扩展阶段已结算。")

        game = Game()
        game.ruleset = replace(game.ruleset, phases=game.ruleset.phases.extended(ExtraPhase()))
        game.state.phase = "test.extra_phase"
        game.dispatch("a", "invoke")
        self.assertEqual(game.state.phase, "day_start")
        self.assertEqual(game.decisions[-1].timing, TimingId.PROTAGONIST_ABILITY)

    def test_wm_spell_is_an_extra_offer_at_the_same_timing(self):
        offer = ActionOffer.create(
            actor="a", kind="wm.cast_spell", timing=TimingId.PROTAGONIST_ABILITY,
            source=RuleSource("wm.ex_spell"), parameters={"spell": "sensory"},
            label="发动感官强化",
        )
        activation = Activation(RuleSource("wm.ex_spell"), TimingId.PROTAGONIST_ABILITY,
                                ActivationMode.OPTIONAL, "a", offers=(offer,))
        self.assertEqual(activation.offers[0].kind, "wm.cast_spell")
        self.assertEqual(activation.offers[0].parameters["spell"], "sensory")

    def test_ahr_world_is_component_and_switch_is_effect(self):
        store = ComponentStore((AhrWorldState(),))
        clone = store.clone()
        clone.get(AhrWorldState).hidden = True
        self.assertFalse(store.get(AhrWorldState).hidden)
        self.assertTrue(clone.to_dict()["ahr.world"]["hidden"])
        switch = CustomEffect("ahr.switch_world", {"to": "hidden"})
        self.assertEqual(normalize_effect(switch),
                         {"kind": "ahr.switch_world", "to": "hidden"})

    def test_mz_public_claim_does_not_leak_actual_identity(self):
        public = Observation("role_announced", "忍者公开宣称身份。",
                             visibility=Visibility.PUBLIC,
                             data={"character": "student", "announced_role": "key"},
                             timing=TimingId.INCIDENT)
        trace = ResolutionTrace(
            RuleSource("mz.ninja_confession"), TimingId.INCIDENT,
            CustomEffect("mz.announce_role", {"character": "student", "role": "key"}),
            (public,), {"actual_role": "ninja"},
        )
        projection = public.to_dict()
        self.assertNotIn("source", projection)
        self.assertNotIn("actual_role", json.dumps(projection, ensure_ascii=False))
        self.assertEqual(trace.details["actual_role"], "ninja")
        self.assertEqual(trace.to_dict()["source"], "mz.ninja_confession")

    def test_hsa_curses_live_outside_character_state(self):
        curses = HsaCurseState({"shrine": ["curse_1", "curse_2"]})
        store = ComponentStore((curses,))
        self.assertEqual(store.to_dict()["hsa.board_curses"]["boards"]["shrine"],
                         ["curse_1", "curse_2"])
        self.assertNotIn("character", store.to_dict()["hsa.board_curses"])


if __name__ == "__main__":
    unittest.main()
