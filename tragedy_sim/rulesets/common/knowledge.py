"""Shared First Steps and Basic Tragedy X rules."""
from ...catalog import PLOTS, ROLE_NAMES

def _script_roles(self):
    roles = set()
    for plot in (self.scenario['main_plot'], *self.scenario['subplots']):
        roles.update(PLOTS[plot][2])
    return roles

def _publish_role(self, target, role):
    if self._incident_before is not None:
        self._incident_effect = True
    self.known_roles[target] = {'role': role, 'loop': self.state.loop, 'day': self.state.round}
    self.role_announcements.append({'character': target, 'role': role, 'loop': self.state.loop, 'day': self.state.round, 'may_be_ninja_claim': False})
    self._event('role_revealed', f'公开信息：{self.name(target)}的身份为{ROLE_NAMES[role]}。', character=target, role=role)

def _reveal_role(self, target, *, truthful=False):
    self._publish_role(target, self.roles[target])

OPERATIONS = {
    '_script_roles': _script_roles,
    '_publish_role': _publish_role,
    '_reveal_role': _reveal_role,
}
