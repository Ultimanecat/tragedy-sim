"""First Steps incident entry point."""

from ..common.incidents import _incident as _shared_incident
from ..common.incidents import _record_incident_end


def _incident(game):
    return _shared_incident(game)


OPERATIONS = {"_incident": _incident, "_record_incident_end": _record_incident_end}
