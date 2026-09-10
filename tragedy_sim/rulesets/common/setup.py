"""Shared First Steps and Basic Tragedy X rules."""
from ...cards import LOCATIONS
from ...catalog import CHARACTERS
from ...model import TimingId
from ...domain import ComponentStore

def initialize(self):
    self.roles = dict(self.scenario['cast'])
    self.ex_cards = dict.fromkeys(self.roles, 0)
    self.ex_gauge = 0
    self.board_ex = dict.fromkeys(LOCATIONS, 0)
    self._apply_current_roles()
    self.known_roles = {}
    self.role_announcements = []
    self.known_culprits = {}
    self.known_plots = []
    self.day_used = set()
    self.loop_used = set()
    self.public_day_used = set()
    self.public_loop_used = set()
    self.guards = dict.fromkeys(self.roles, 0)
    self.protected = False
    self.incident_records = []
    self.winner = None
    self.history = []
    self.decisions = []
    self.loss_reasons = []
    self._resolution_traces = []
    self._activation_history = []
    self.components = ComponentStore()
    self._timing_window = None
    self._trace_observation_stack = []
    self._pending_source = None
    self._queue = []
    self._pending = None
    self._decision_actor = None
    self._decision_public_phase = None
    self._return_phase = None
    self._request = None
    self._ignore_intrigue = set()
    self._previous_goodwill = set()
    self._incident_before = None
    self._incident_effect = False
    self._guess_remaining = []
    self._mandatory_victims = []
    self._previous_dead = set()
    self._occurred_incidents = []
    self._announced_roles = set()
    self._fake_incident_active = False
    self._previous_ex_gauge = None
    self._movement_locks = {}
    self._sealed_boards = []
    self._prevented_incident_culprits = set()
    self._loop_initial_locations = {cid: CHARACTERS[cid].start for cid in self.roles}
    self._night_forced_done = False
    self._at_loop_end = False
    self.state.phase = 'day_start'
    self._event('loop_started', f"第 1 轮回开始，共 {self.scenario['loops']} 轮，每轮 {self.scenario['days']} 天。", timing=TimingId.LOOP_START)
    self._start_loop_placements()
