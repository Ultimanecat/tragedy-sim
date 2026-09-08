from typing import Any

from ..model import PhaseId
from .base import NextPhaseResolver


class IncidentResolver(NextPhaseResolver):
    phase = PhaseId.INCIDENT

    def execute(self, game, actor: str, action: str,
                arguments: dict[str, Any]) -> None:
        game._incident()
