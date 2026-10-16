"""Small complete-posterior resampling and composition certificates."""
from collections import Counter
from dataclasses import replace
import random
import unittest
from unittest.mock import patch

from tragedy_sim import action_role_sampling as draft
from tragedy_sim import Game
from tragedy_sim.belief import FactorizedBeliefState, PublicEvidence, HiddenWorldHypothesis
from tragedy_sim.belief_culprit_posterior import joint_culprit_posterior
from tragedy_sim.engine import RuleError
from tragedy_sim.scenario_library import ScenarioLibrary

def fixture():
    evidence = PublicEvidence.from_view(Game(ScenarioLibrary().get('official-fs-01-first-script')).protagonist_team_view())
    evidence = replace(evidence,known_roles=(('girl','key'),('maiden','serial'),('doctor','brain'),('student','ordinary')),
                       known_plots=('murder_plan','ripper'))
    model = FactorizedBeliefState(joint_culprits=True)
    ranked = model.role_posterior(evidence,())
    assert len(ranked)==2 and model._exact_roles
    domains = model._culprits(evidence,())
    joint = joint_culprit_posterior(evidence.schedule,domains)
    return tuple(w for w,_ in ranked),tuple(p for _,p in ranked),evidence,domains,joint

class ActionRoleSamplingTests(unittest.TestCase):
    def test_equal_support_cannot_disappear(self):
        for seed in range(100):
            self.assertEqual(Counter(draft.residual_indices([.25]*4,4,rng=random.Random(seed))),dict.fromkeys(range(4),1))

    def test_nonuniform_counts_keep_mass_and_floor(self):
        counts = Counter()
        for seed in range(10000):
            drawn = draft.residual_indices([.1,.2,.7,0],4,rng=random.Random(seed))
            self.assertEqual(len(drawn),4)
            self.assertGreaterEqual(drawn.count(2),2)
            self.assertNotIn(3,drawn)
            counts.update(drawn)
        for i,p in enumerate([.1,.2,.7]):
            self.assertLess(abs(counts[i]/40000-p),.004)

    def test_integer_probabilities_and_invalid_inputs(self):
        self.assertEqual(Counter(draft.residual_indices([1,2,7],10,rng=random.Random(0))),{0:1,1:2,2:7})
        for weights in ([],[0,0],[-1,2],[float('nan')],[float('inf')]):
            with self.assertRaises(ValueError):
                draft.residual_indices(weights,4,rng=random.Random(0))
        for count in (0,-1,True,2.5):
            with self.assertRaises(ValueError):
                draft.residual_indices([1],count,rng=random.Random(0))

    def test_complete_roles_certify_every_legal_joint_composition(self):
        roles,weights,evidence,domains,joint = fixture()
        chosen, diagnostic = draft.certified_residual_roles(roles,weights,evidence,(),domains,joint,4,
                                                           exact=True,rng=random.Random(0))
        self.assertEqual(Counter(chosen),dict.fromkeys(roles,2))
        self.assertEqual(diagnostic['composition_checks'],60)
        self.assertEqual(diagnostic['used'],'residual_small')

    def test_uncertified_fallback_does_not_advance_rng(self):
        roles,weights,evidence,domains,joint = fixture()
        for options,reason in (({'exact':False},'role_support_not_complete'),
                               ({'count':1},'role_support_exceeds_budget'),
                               ({'joint':None},'joint_culprits_required'),
                               ({'composition_limit':1},'composition_limit')):
            kwargs = dict(count=4,exact=True,joint=joint,rng=random.Random(9),composition_limit=2048)
            kwargs.update(options)
            rng = kwargs['rng']; before = rng.getstate()
            chosen,diagnostic = draft.certified_residual_roles(roles,weights,evidence,(),domains,**kwargs)
            self.assertIsNone(chosen)
            self.assertEqual(diagnostic['fallback'],reason)
            self.assertEqual(rng.getstate(),before)

    def test_role_dependent_invalid_composition_falls_back(self):
        roles,weights,evidence,domains,joint = fixture()
        rng=random.Random(4); before=rng.getstate()
        with patch.object(HiddenWorldHypothesis,'materialize',side_effect=RuleError('invalid combination')):
            chosen,diagnostic = draft.certified_residual_roles(roles,weights,evidence,(),domains,joint,4,exact=True,rng=rng)
        self.assertIsNone(chosen)
        self.assertEqual(diagnostic['fallback'],'role_dependent_composition')
        self.assertEqual(rng.getstate(),before)

    def test_full_matcher_is_part_of_certificate(self):
        roles,weights,evidence,domains,joint = fixture()
        from tragedy_sim.witness import FsbtxWitnessMatcher
        rng=random.Random(4); before=rng.getstate()
        with patch.object(FsbtxWitnessMatcher,'matches',return_value=False):
            chosen,diagnostic = draft.certified_residual_roles(roles,weights,evidence,(),domains,joint,4,exact=True,rng=rng)
        self.assertIsNone(chosen)
        self.assertEqual(diagnostic['fallback'],'role_dependent_witness')
        self.assertEqual(rng.getstate(),before)

    def test_integrated_residual_draw_covers_support_and_diagnostics_are_read_only(self):
        roles,weights,evidence,domains,joint = fixture()
        model = FactorizedBeliefState(joint_culprits=True)
        model.action_role_sampling_policy = 'residual_small'
        matrix_rng = model.matrix_rng.getstate()
        result = model.sample(evidence,(),4,rng=random.Random(7))
        self.assertEqual(Counter(dict(w.roles)['worker'] for w in result.worlds),{'killer':2,'conspiracy':2})
        for world in result.worlds:
            self.assertTrue(joint.supports_assignment({d:c for d,_,_,c in world.incidents}))
        info = model.proposal_summary()['action_role_sampling']
        self.assertEqual(info['used'],'residual_small')
        self.assertEqual(info['role_masses'],[.5,.5])
        info['role_replicas'].clear()
        self.assertEqual(model.proposal_summary()['action_role_sampling']['role_replicas'],[2,2])
        self.assertEqual(model.matrix_rng.getstate(),matrix_rng)

    def test_support_exceeds_budget_integrated_fallback_is_iid_equivalent(self):
        _,_,evidence,_,_ = fixture()
        states = [FactorizedBeliefState(joint_culprits=True) for _ in range(2)]
        states[1].action_role_sampling_policy = 'residual_small'
        streams = [random.Random(11) for _ in range(2)]
        results = [model.sample(evidence,(),1,rng=rng) for model,rng in zip(states,streams)]
        self.assertEqual(results[0],results[1])
        self.assertEqual(streams[0].getstate(),streams[1].getstate())
        self.assertEqual(states[1].proposal_summary()['action_role_sampling']['fallback'],'role_support_exceeds_budget')

    def test_incomplete_pool_integrated_fallback_is_iid_equivalent(self):
        roles,weights,evidence,_,_ = fixture()
        states = [FactorizedBeliefState(joint_culprits=True) for _ in range(2)]
        states[1].action_role_sampling_policy = 'residual_small'
        streams = [random.Random(4) for _ in range(2)]
        results=[]
        for model,rng in zip(states,streams):
            with patch.object(model,'role_posterior',return_value=tuple(zip(roles,weights))):
                results.append(model.sample(evidence,(),4,rng=rng))
        self.assertEqual(results[0],results[1])
        self.assertEqual(streams[0].getstate(),streams[1].getstate())
        self.assertEqual(states[1].proposal_summary()['action_role_sampling']['fallback'],'role_support_not_complete')

    def test_empty_schedule_and_schedule_mismatch(self):
        roles,weights,evidence,_,_ = fixture()
        evidence=replace(evidence,schedule=())
        roles=tuple(replace(w,incidents=()) for w in roles)
        joint=joint_culprit_posterior((),{})
        chosen,info=draft.certified_residual_roles(roles,weights,evidence,(),{},joint,4,exact=True,rng=random.Random(1))
        self.assertIsNotNone(chosen)
        self.assertEqual(info['composition_checks'],2)
        bad=(replace(roles[0],incidents=((1,'suicide','suicide','girl'),)),roles[1])
        chosen,info=draft.certified_residual_roles(bad,weights,evidence,(),{},joint,4,exact=True,rng=random.Random(1))
        self.assertIsNone(chosen)
        self.assertEqual(info['fallback'],'incident_schedule_mismatch')

    def test_public_configuration_rejects_invalid_modes_and_other_agents(self):
        from tragedy_sim.particle_ensemble import ParticleEnsembleProtagonistAgent
        from benchmarks.ai_self_play import play
        for policy in (True,None,'unknown'):
            with self.subTest(policy=policy):
                with self.assertRaisesRegex(ValueError,'action_role_sampling_policy'):
                    ParticleEnsembleProtagonistAgent(action_role_sampling_policy=policy)
                with self.assertRaisesRegex(ValueError,'action_role_sampling_policy'):
                    play('official-fs-01-first-script',0,1,1,'random','random',action_role_sampling_policy=policy)
        with self.assertRaisesRegex(ValueError,'particle_ensemble'):
            play('official-fs-01-first-script',0,1,1,'random','random',action_role_sampling_policy='residual_small')

if __name__=='__main__':
    unittest.main()
