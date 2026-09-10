"""Shared First Steps and Basic Tragedy X rules."""
from ...engine import ActionGame, RuleError

def _can_target_action(self, actor, target):
    if target not in self.state.characters:
        return True
    if actor != 'm' and self._fake_incident_active and self.ex_cards.get(target, 0):
        return False
    return True

def play(self, actor, card_id, target):
    if target in self.state.characters and (not self._can_target_action(actor, target)):
        if actor == 'm':
            raise RuleError('预言家在场时，剧作家不能向其放置行动牌')
        raise RuleError('伪造事件生效后，主人公本轮不能向有 Ex 牌的角色放置行动牌')
    ActionGame.play(self, actor, card_id, target)

def _apply_current_roles(self):
    pass

def _movement_is_forbidden(self, target, effects):
    return ActionGame._movement_is_forbidden(self, target, effects)

def _movement_destination_allowed(self, target, destination):
    origin = self.state.characters[target].location
    return not any((self.state.round <= through and origin != destination and (board in (origin, destination)) for board, through in self._sealed_boards))

def _intrigue_forbids_cancel(self, count):
    return ActionGame._intrigue_forbids_cancel(self, count)

def _has(self, cid, role):
    if not self.state.characters[cid].alive and (not False):
        return False
    return self.roles[cid] == role or (self.roles[cid] == 'factor' and (role == 'key' and self.state.locations['city'] >= 2 or (role == 'conspiracy' and self.state.locations['school'] >= 2)))

def _ahr_refresh_roles(self):
    pass

def _count(self, character, counter):
    """Return a counter's rules value after hope/despair modifiers."""
    value = getattr(character, counter)
    return value

def _counter_mutated(self, target, counter):
    if 'virus' in self.scenario['subplots']:
        for c in self._living():
            if self.roles[c.id] == 'ordinary' and c.paranoia >= 3:
                self.roles[c.id] = 'serial'

def _ignore_forbid(self, counter, target):
    location = self.state.characters[target].location if target in self.state.characters else target
    return counter == 'intrigue' and location in self._ignore_intrigue or (counter == 'goodwill' and target in self.roles and self._has(target, 'time_traveler'))

def _kill(self, targets):
    killed = []
    key_death = False
    for target in dict.fromkeys(targets):
        c = self.state.characters[target]
        if not c.alive:
            continue
        if self._has(target, 'time_traveler'):
            self._event('death_prevented', f'{c.name}没有死亡。', target=target)
        elif self.guards[target]:
            self.guards[target] -= 1
            self._event('guard_spent', f'{c.name}的一个护卫标记被移除，替代这次死亡。', target=target)
        else:
            key_death |= self._has(target, 'key')
            killed.append(target)
    for target in killed:
        self.state.characters[target].alive = False
        self._event('character_died', f'{self.name(target)}死亡；尸体留在原地，计数物保留。', target=target)
    for target in killed:
        partner = {'lover': 'loved', 'loved': 'lover'}.get(self.roles[target])
        if partner:
            for c in self._living():
                if self.roles[c.id] == partner:
                    self._change(c.id, 'paranoia', 6)
    if key_death:
        self.loss_reasons.append('关键人物（或持有该能力的因子）死亡')
        self._finish_loop(forced=True)

OPERATIONS = {
    '_can_target_action': _can_target_action,
    'play': play,
    '_apply_current_roles': _apply_current_roles,
    '_movement_is_forbidden': _movement_is_forbidden,
    '_movement_destination_allowed': _movement_destination_allowed,
    '_intrigue_forbids_cancel': _intrigue_forbids_cancel,
    '_has': _has,
    '_ahr_refresh_roles': _ahr_refresh_roles,
    '_count': _count,
    '_counter_mutated': _counter_mutated,
    '_ignore_forbid': _ignore_forbid,
    '_kill': _kill,
}
