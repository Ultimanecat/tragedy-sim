"""Offline diagnosis of factorized-belief fallbacks on a real match trajectory.

The probe observes the planner at its existing API boundary.  It does not
change sampling, select actions, or publish hidden setup information to players.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
from unittest.mock import patch

from tragedy_sim.belief import (FactorizedBeliefState, HiddenWorldHypothesis,
                               PublicEvidence)
from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
from tragedy_sim.ismcts import PublicStateDeterminizer
from tragedy_sim.scenario_library import ScenarioLibrary
from tragedy_sim.witness import (FsbtxWitnessCompiler, FsbtxWitnessMatcher,
                                WitnessStrength, WitnessVerdict)

from .ai_self_play import play


def audit_match(scenario_id: str, seed: int, *, worlds: int = 32,
                nodes: int = 8, expected_digest: str | None = None,
                disabled_witness_sources: tuple[str, ...] = (),
                capture_action_worlds: bool = False,
                independent_dark_history: bool = False,
                disable_incident_escape: bool = False) -> dict[str, Any]:
    scenario = ScenarioLibrary().get(scenario_id)
    truth = HiddenWorldHypothesis.from_scenario(scenario)
    matcher = FsbtxWitnessMatcher()
    current: dict[str, int] = {}
    samples: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    final_context: dict[str, Any] = {}
    action_contexts: list[dict[str, Any]] = []
    active_context: dict[str, Any] | None = None
    original_choose = ParticleEnsembleProtagonistAgent.choose_action
    original_sample = FactorizedBeliefState.sample
    original_determinize = PublicStateDeterminizer.determinize
    original_escape_targets = ParticleEnsembleProtagonistAgent._incident_escape_targets

    def observed_escape_targets(view, evidence, witnesses):
        return (() if disable_incident_escape else
                original_escape_targets(view, evidence, witnesses))

    def observed_choose(self, *, participant, view, offers):
        nonlocal active_context
        active_context = None
        if (capture_action_worlds and view.get('phase') == 'protagonists'
                and not self._joint_plan):
            active_context = {**{'loop': int(view['loop']),
                                 'day': int(view['round'])},
                              'view': deepcopy(view), 'worlds': []}
            action_contexts.append(active_context)
        current.update(loop=int(view['loop']), day=int(view['round']))
        if not any(row['loop'] == current['loop'] and row['day'] == current['day']
                   for row in observations):
            observations.append({**current,
                                 'characters': {cid: {
                                     key: character.get(key)
                                     for key in ('location', 'paranoia',
                                                 'goodwill', 'intrigue', 'alive')}
                                     for cid, character in
                                     view.get('characters', {}).items()},
                                 'pending': view.get('pending', ())})
        selected = original_choose(self, participant=participant, view=view,
                                   offers=offers)
        if view.get('phase') == 'final_guess':
            # Seat-authorized input only; this development artifact may contain
            # private investigation answers and must not be sent to opponents.
            final_context.update(
                view=deepcopy(view),
                evidence=asdict(PublicEvidence.from_view(view)),
                witnesses=[asdict(w) for w in self.evidence_ledger.witnesses])
        trace = self.last_trace
        if trace is not None and trace.fallback not in (None, 'joint_plan_followup'):
            fallbacks.append({**current, 'reason': trace.fallback,
                              'selected': (selected.get('actor'),
                                           selected.get('parameters'))})
        return selected

    def observed_determinize(self, hypothesis, evidence, view, **kwargs):
        if independent_dark_history:
            kwargs['coherent_history'] = False
        world = original_determinize(self, hypothesis, evidence, view, **kwargs)
        if active_context is not None:
            active_context['worlds'].append({
                'hypothesis': asdict(hypothesis),
                'force_history': bool(kwargs.get('force_history')),
                'coherent_history': bool(kwargs.get('coherent_history')),
                'pending': ([asdict(item) for item in world.state.pending]
                            if world is not None else None),
            })
        return world

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
          patch.object(FactorizedBeliefState, 'sample', observed_sample),
          patch.object(PublicStateDeterminizer, 'determinize', observed_determinize),
          patch.object(ParticleEnsembleProtagonistAgent, '_incident_escape_targets',
                       staticmethod(observed_escape_targets))):
        match = play(scenario_id, seed, 2, 8, 'fixed', 'particle_ensemble',
                     protagonist_nodes=nodes, protagonist_particles=worlds,
                     disabled_witness_sources=disabled_witness_sources)
    if expected_digest is not None and match.decision_digest != expected_digest:
        raise AssertionError('audit changed the recorded decision trajectory')
    return {
        'scenario': scenario_id, 'seed': seed, 'nodes': nodes,
        'truth_setup': asdict(truth),
        'worlds_requested': worlds, 'decision_digest': match.decision_digest,
        'independent_dark_history': independent_dark_history,
        'disable_incident_escape': disable_incident_escape,
        'disabled_witness_sources': disabled_witness_sources,
        'winner': match.winner,
        'final_guess_correct': sum(row.correct for row in match.final_guesses),
        'final_guess_total': len(match.final_guesses),
        'final_guesses': [asdict(row) for row in match.final_guesses],
        'final_role_candidates': match.final_role_candidates,
        'final_true_setup_hard_compatible': match.final_true_setup_hard_compatible,
        'known_roles_before_final': match.known_roles_before_final,
        'final_belief_roles': match.final_belief_roles,
        'final_belief_setups': match.final_belief_setups,
        'final_soft_witnesses': match.final_soft_witnesses,
        'final_public_deaths': match.final_public_deaths,
        'final_context': final_context,
        # Development-only hidden hypotheses. Never expose in player replay.
        'action_contexts': action_contexts,
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
        'observations': observations,
        'protagonist_plays': [asdict(row) for row in match.protagonist_plays],
        'mastermind_plays': [asdict(row) for row in match.mastermind_plays],
        'losses': [asdict(row) for row in match.loop_losses],
        'searches': [{'loop': row.loop, 'day': row.day,
                      'selected_bundle': row.selected_bundle,
                      'belief_roles': row.belief_roles,
                      'candidates': [{key: candidate[key] for key in (
                          'bundle', 'day_survivals', 'mean_value',
                          'location_guard_bonus') if key in candidate}
                          for candidate in row.candidates]}
                     for row in match.protagonist_searches],
        'elapsed_seconds': round(match.elapsed_seconds, 3),
    }


def reanalyze_final(report: Mapping[str, Any], *,
                    disabled_witness_sources: tuple[str, ...] = ()) -> dict[str, Any]:
    """Recompile and solve a saved authorized view without replaying a match."""
    started = perf_counter()
    view = report.get('final_context', {}).get('view')
    if not isinstance(view, Mapping):
        raise ValueError('report has no saved final protagonist view')
    # New reports bind the hidden diagnostic truth to the original run. Older
    # context reports can still use the current library, explicitly labelled.
    saved_truth = report.get('truth_setup')
    truth = (HiddenWorldHypothesis(
        saved_truth['scenario_id'], saved_truth['main_plot'],
        tuple(saved_truth['subplots']),
        tuple(tuple(item) for item in saved_truth['roles']),
        tuple(tuple(item) for item in saved_truth['incidents'])) if saved_truth else
             HiddenWorldHypothesis.from_scenario(
                 ScenarioLibrary().get(report['scenario'])))
    evidence = PublicEvidence.from_view(view)
    witnesses = FsbtxWitnessCompiler(
        disabled_sources=disabled_witness_sources).compile(view)
    solver = FactorizedBeliefState()
    solved = solver.exact_role_map(evidence, witnesses)
    matcher = FsbtxWitnessMatcher()
    role_witnesses = solver._role_witnesses(witnesses)
    selected = (max(solved.ranked, key=lambda pair: (
        pair[1], tuple(sorted(pair[0].roles)))) if solved.ranked else None)
    actual = dict(truth.roles)
    guesses = dict(selected[0].roles) if selected else {}
    return {
        'mode': 'final_reanalysis', 'scenario': report['scenario'],
        'source_decision_digest': report['decision_digest'],
        'truth_source': 'saved_run' if saved_truth else 'current_library',
        'disabled_witness_sources': disabled_witness_sources,
        'correct': sum(guesses.get(cid) == role for cid, role in actual.items()),
        'total': len(actual), 'guesses': guesses,
        'selected_setup': asdict(selected[0]) if selected else None,
        'selected_weight': selected[1] if selected else None,
        'role_domain_configurations': solved.compatible_count,
        'truth_hard_compatible': matcher.matches(truth, witnesses),
        'truth_hard_conflicts': [asdict(w) for w in witnesses
                                if w.strength == WitnessStrength.HARD and
                                matcher.verdict(truth, w) == WitnessVerdict.CONTRADICTED],
        'truth_role_soft_score': matcher.soft_score(truth, role_witnesses),
        'selected_role_soft_score': (matcher.soft_score(selected[0], role_witnesses)
                                     if selected else None),
        'witness_sources': dict(Counter(w.source for w in witnesses)),
        'elapsed_seconds': round(perf_counter() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--scenario')
    mode.add_argument('--reanalyze', type=Path,
                      help='solve a saved final view; does not rerun the match')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--worlds', type=int, default=32)
    parser.add_argument('--nodes', type=int, default=8)
    parser.add_argument('--expected-digest')
    parser.add_argument('--capture-action-worlds', action='store_true',
                        help='save authorized roots and sampled hidden hypotheses offline')
    parser.add_argument('--independent-dark-history', action='store_true',
                        help='ablate coherent past-reveal proposals')
    parser.add_argument('--disable-incident-escape', action='store_true',
                        help='ablate hard-evidence Murder victim movement proposals')
    parser.add_argument('--disable-witness-source', action='append', default=[])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    disabled = tuple(args.disable_witness_source)
    if args.reanalyze:
        report = reanalyze_final(json.loads(args.reanalyze.read_text(encoding='utf-8')),
                                disabled_witness_sources=disabled)
    else:
        report = audit_match(args.scenario, args.seed, worlds=args.worlds,
                             nodes=args.nodes, expected_digest=args.expected_digest,
                             disabled_witness_sources=disabled,
                             capture_action_worlds=args.capture_action_worlds,
                             independent_dark_history=args.independent_dark_history,
                             disable_incident_escape=args.disable_incident_escape)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {'fallbacks', 'fallback_samples',
                                     'observations', 'protagonist_plays',
                                     'mastermind_plays', 'losses', 'searches',
                                     'final_guesses', 'final_belief_roles',
                                     'final_belief_setups', 'final_soft_witnesses',
                                     'final_public_deaths', 'final_context', 'truth_setup',
                                     'action_contexts'}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
