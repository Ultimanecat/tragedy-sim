"""Offline diagnosis of factorized-belief fallbacks on a real match trajectory.

The probe observes the planner at its existing API boundary.  It does not
change sampling, select actions, or publish hidden setup information to players.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tragedy_sim.belief import FactorizedBeliefState, HiddenWorldHypothesis
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import FsbtxWitnessMatcher, WitnessStrength, WitnessVerdict

from .ai_self_play import play


def audit_match(scenario_id: str, seed: int, *, worlds: int = 32,
                nodes: int = 8, expected_digest: str | None = None) -> dict[str, Any]:
    scenario = ScenarioLibrary().get(scenario_id)
    truth = HiddenWorldHypothesis.from_scenario(scenario)
    matcher = FsbtxWitnessMatcher()
    current: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []
    original_choose = ParticleEnsembleProtagonistAgent.choose_action
    original_sample = FactorizedBeliefState.sample

    def observed_choose(self, *, participant, view, offers):
        current.update(loop=int(view['loop']), day=int(view['round']))
        selected = original_choose(self, participant=participant, view=view,
                                   offers=offers)
        trace = self.last_trace
        if trace is not None and trace.fallback not in (None, 'joint_plan_followup'):
            fallbacks.append({**current, 'reason': trace.fallback,
                              'selected': (selected.get('actor'),
                                           selected.get('parameters'))})
        return selected

    def observed_sample(self, evidence, witnesses, count, *, rng):
        result = original_sample(self, evidence, witnesses, count, rng=rng)
        hard_conflicts = [
            {'source': w.source, 'kind': w.kind, 'subject': w.subject,
             'value': w.value}
            for w in witnesses if w.strength == WitnessStrength.HARD
            and matcher.verdict(truth, w) == WitnessVerdict.CONTRADICTED]
        sizes = dict(result.culprit_options)
        first_empty = (result.role_candidates == 0 and not any(
            row['role_candidates'] == 0 for row in samples))
        samples.append({**current, 'worlds': len(result.worlds),
                        'role_candidates': result.role_candidates,
                        'culprit_options': sizes, 'reason': result.reason,
                        'hard_conflicts': hard_conflicts,
                        'known_roles': list(evidence.known_roles) if first_empty else [],
                        'known_plots': list(evidence.known_plots) if first_empty else [],
                        'plot_sets': len(self.sampler._plot_sets(evidence)) if first_empty else None,
                        'hard_witnesses': ([{'source': w.source, 'kind': w.kind,
                                            'subject': w.subject, 'value': w.value}
                                           for w in witnesses
                                           if w.strength == WitnessStrength.HARD]
                                          if first_empty else []),
                        'witnesses': len(witnesses)})
        return result

    with (patch.object(ParticleEnsembleProtagonistAgent, 'choose_action',
                       observed_choose),
          patch.object(FactorizedBeliefState, 'sample', observed_sample)):
        match = play(scenario_id, seed, 2, 8, 'fixed', 'particle_ensemble',
                     protagonist_nodes=nodes, protagonist_particles=worlds)
    if expected_digest is not None and match.decision_digest != expected_digest:
        raise AssertionError('audit changed the recorded decision trajectory')
    return {
        'scenario': scenario_id, 'seed': seed, 'nodes': nodes,
        'worlds_requested': worlds, 'decision_digest': match.decision_digest,
        'winner': match.winner,
        'final_guess_correct': sum(row.correct for row in match.final_guesses),
        'final_guess_total': len(match.final_guesses),
        'loop_losses': len(match.loop_losses),
        'sample_count': len(samples),
        'fallbacks': fallbacks,
        'fallback_samples': [row for row in samples if row['reason']],
        'empty_role_samples': sum(row['role_candidates'] == 0 for row in samples),
        'empty_culprit_samples': sum(0 in row['culprit_options'].values()
                                     for row in samples),
        'truth_hard_conflicts': sum(bool(row['hard_conflicts']) for row in samples),
        'reason_counts': dict(Counter(row['reason'] for row in samples
                                      if row['reason'])),
        'elapsed_seconds': round(match.elapsed_seconds, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--worlds', type=int, default=32)
    parser.add_argument('--nodes', type=int, default=8)
    parser.add_argument('--expected-digest')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit_match(args.scenario, args.seed, worlds=args.worlds,
                         nodes=args.nodes, expected_digest=args.expected_digest)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {'fallbacks', 'fallback_samples'}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
