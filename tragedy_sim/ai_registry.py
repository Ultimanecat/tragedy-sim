"""Room-selectable policies and their construction, separate from room lifecycle.

Historical algorithms remain available to development benchmarks. Retired room
IDs fail explicitly; they never silently select a different policy.
"""

from dataclasses import dataclass
from typing import Callable

from .ai import (AgentPolicy, BaselineProtagonistAgent, DefensiveProtagonistAgent,
                 FixedStrategyMastermindAgent, RandomAgent)
from .joint_mastermind import JointPlanMastermindAgent
from .mcts import FullInformationMctsMastermindAgent
from .optimized_mcts import OptimizedMctsMastermindAgent
from .oracle_protagonist import FullCardOracleProtagonistAgent, HiddenCardOracleProtagonistAgent
from .particle_ensemble import ParticleEnsembleProtagonistAgent
from .search import SearchBudget
from .strategic_mcts import StrategicMctsMastermindAgent


@dataclass(frozen=True)
class RoomAiSpec:
    nickname: str
    role: str
    factory: Callable[[], AgentPolicy]
    modules: frozenset[str] | None = None
    team_only: bool = False


def _search_budget():
    return SearchBudget(node_limit=24, rollout_depth=12)


ROOM_AI = {
    "random": RoomAiSpec("随机 AI", "both", RandomAgent),
    "baseline_protagonist": RoomAiSpec("基础干扰主人公 AI", "protagonist", BaselineProtagonistAgent),
    "defensive_protagonist": RoomAiSpec("公开信息防守主人公 AI", "protagonist", DefensiveProtagonistAgent),
    "fixed_mastermind": RoomAiSpec("定式剧作家 AI", "mastermind", FixedStrategyMastermindAgent),
    "mcts_mastermind": RoomAiSpec("朴素 MCTS 剧作家 AI", "mastermind",
        lambda: FullInformationMctsMastermindAgent(_search_budget())),
    "optimized_mcts_mastermind": RoomAiSpec("优化 MCTS 剧作家 AI", "mastermind",
        lambda: OptimizedMctsMastermindAgent(_search_budget())),
    "strategic_mcts_mastermind": RoomAiSpec("策略 MCTS 剧作家 AI", "mastermind",
        lambda: StrategicMctsMastermindAgent(_search_budget())),
    "joint_mastermind": RoomAiSpec("三牌联合剧作家 AI", "mastermind",
        lambda: JointPlanMastermindAgent(_search_budget()), frozenset({"FS", "BTX"})),
    "belief_joint_mastermind": RoomAiSpec("信念采样剧作家 AI", "mastermind",
        lambda: JointPlanMastermindAgent(
            SearchBudget(node_limit=96, rollout_depth=12, time_limit_ms=10000),
            reply_model="belief"), frozenset({"BTX"})),
    "oracle_cards_protagonist": RoomAiSpec("开眼红方（剧本＋明牌）", "protagonist",
        lambda: FullCardOracleProtagonistAgent(SearchBudget(node_limit=48, rollout_depth=24)),
        frozenset({"FS", "BTX"}), True),
    "oracle_script_protagonist": RoomAiSpec("开眼红方（剧本＋暗牌）", "protagonist",
        lambda: HiddenCardOracleProtagonistAgent(SearchBudget(node_limit=48, rollout_depth=24)),
        frozenset({"FS", "BTX"}), True),
    "particle_ensemble_protagonist": RoomAiSpec("粒子集成主人公 AI", "protagonist",
        lambda: ParticleEnsembleProtagonistAgent(
            SearchBudget(node_limit=24, rollout_depth=12, time_limit_ms=3000), particle_count=12),
        frozenset({"FS", "BTX"}), True),
}

RETIRED_ROOM_AI = frozenset({"risk_aware_protagonist", "ismcts_protagonist",
                            "survival_ismcts_protagonist", "ismcts_legacy_protagonist"})


def build_room_ai(strategy: str, *, random_agent: AgentPolicy | None = None) -> AgentPolicy:
    if strategy == "random" and random_agent is not None:
        return random_agent
    return ROOM_AI[strategy].factory()
