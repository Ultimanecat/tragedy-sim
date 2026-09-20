"""Deterministic Tragedy Looper engine and versioned JSON application service."""

from .engine import ActionGame, Character, RuleError
from .domain import (ActionOffer, Activation, ActivationMode, ActivationRule, ComponentStore, CounterChange,
                     CustomEffect, Effect, EffectResult, EndgamePlan, FlowPlan, KillCharacter,
                     LegacyEffect, MandatoryWindow, PhaseKey, ResolutionTrace, RuleContext, RuleSource,
                     SourcedEffect, StateComponent, TimingResolver, VictoryPolicy)
from .game import Game
from .flow import MATCH_FLOW, PHASE_LABELS, ControllerPolicy, MatchFlow, PhaseDefinition, phase_label
from .model import (DecisionRecord, GameModel, Observation, PhaseCursor, PhaseId, ResolutionStep,
                    SimulationResult, TimingId, Visibility)
from .replay import ReplayArchive, ReplaySession
from .service import GameService, LocalGameClient, PROTOCOL_VERSION, ServiceError
from .mcts import FullInformationMctsMastermindAgent
from .optimized_mcts import OptimizedMctsMastermindAgent
from .strategic_mcts import StrategicMctsMastermindAgent
from .joint_mastermind import JointPlanMastermindAgent
from .ismcts import (IsmctsProtagonistAgent, LegacyIsmctsProtagonistAgent,
                     IsmctsTrace, PublicStateDeterminizer)
from .belief import (CatalogBeliefSampler, ConstraintBeliefSampler,
                     BeliefParticleFilter, HiddenWorldHypothesis,
                     ParticleFilterResult, ParticleReplayResult,
                     ParticleReplayer, ParticleAdvanceResult,
                     ObservationCheckpoint, ObservationParticleAdvancer,
                     PublicEvidence, PublicSnapshot)
from .witness import (FsbtxWitnessCompiler, FsbtxWitnessMatcher, PublicWitness,
                      WitnessEvaluation, WitnessStrength, WitnessVerdict)
from .search import MastermindEvaluator, RootActionStats, SearchBudget, SearchTrace
from .evaluation import (EvaluationContribution, PositionEvaluation, PositionFeatures,
                         ScenarioConditionedEvaluator, ScenarioEvaluationContext)
from .ai import (BaselineProtagonistAgent, DefensiveProtagonistAgent,
                 RiskAwareProtagonistAgent)

__all__ = ["ActionGame", "ActionOffer", "Activation", "ActivationMode", "ActivationRule", "Character",
           "ComponentStore", "ControllerPolicy", "CounterChange", "CustomEffect", "DecisionRecord",
           "Effect", "EffectResult", "EndgamePlan", "FlowPlan", "Game", "GameModel", "KillCharacter",
           "GameService", "LocalGameClient", "PROTOCOL_VERSION", "ServiceError",
           "FullInformationMctsMastermindAgent", "OptimizedMctsMastermindAgent",
           "StrategicMctsMastermindAgent",
           "IsmctsProtagonistAgent", "LegacyIsmctsProtagonistAgent",
           "IsmctsTrace", "PublicStateDeterminizer",
           "CatalogBeliefSampler", "ConstraintBeliefSampler",
           "BeliefParticleFilter", "ParticleFilterResult",
           "HiddenWorldHypothesis", "ParticleReplayResult", "ParticleReplayer",
           "ParticleAdvanceResult", "ObservationParticleAdvancer",
           "ObservationCheckpoint", "PublicEvidence", "PublicSnapshot",
           "FsbtxWitnessCompiler", "FsbtxWitnessMatcher", "PublicWitness",
           "WitnessEvaluation", "WitnessStrength", "WitnessVerdict",
           "MastermindEvaluator", "RootActionStats",
           "EvaluationContribution", "PositionEvaluation", "PositionFeatures",
           "ScenarioConditionedEvaluator", "ScenarioEvaluationContext",
           "BaselineProtagonistAgent",
           "DefensiveProtagonistAgent",
           "RiskAwareProtagonistAgent",
           "SearchBudget", "SearchTrace",
           "MATCH_FLOW", "MatchFlow", "Observation", "PHASE_LABELS", "PhaseCursor", "PhaseDefinition", "PhaseId",
           "LegacyEffect", "MandatoryWindow", "PhaseKey", "ReplayArchive", "ReplaySession", "ResolutionStep",
           "ResolutionTrace", "RuleContext", "RuleError", "RuleSource", "SimulationResult",
           "SourcedEffect", "StateComponent", "TimingId", "TimingResolver", "VictoryPolicy",
           "Visibility", "phase_label"]
