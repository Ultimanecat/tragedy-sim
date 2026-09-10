"""Shared First Steps and Basic Tragedy X rules."""
from copy import deepcopy
from ...cards import COUNTER_NAMES, LOCATIONS, STANDARD_COUNTERS
from ...catalog import CHARACTERS, INCIDENT_NAMES, MODULE_PLOTS, PLOTS, REFUSAL
from ...engine import RuleError
from ...effects.vocabulary import op, option
from ...domain import SourcedEffect, legacy_effect
from ...i18n import label

def _available_key(self, key, once=False):
    return key not in self.day_used and (not once or key not in self.loop_used)

def _mark(self, key, once=False):
    self.day_used.add(key)
    if once:
        self.loop_used.add(key)

def _counter_options(self, source, key, targets, counter, amount, label, once=False):
    if not self._available_key(key, once):
        return []
    return [option(f'{label} → {self.name(t)} {COUNTER_NAMES[counter]} {amount:+}', [op('counter', target=t, counter=counter, amount=amount)], key=key, once=once) for t in targets]

def _scoped_targets(self, source, scope):
    s = self.state.characters[source]
    living = self._living()
    same = [c for c in living if c.location == s.location]
    if scope == 'self':
        return [source]
    if scope == 'rich' and s.location not in ('school', 'city'):
        return []
    if scope in ('corpse', 'any_corpse'):
        return [c.id for c in self.state.characters.values() if not c.alive and (scope == 'any_corpse' or c.location == s.location)]
    selected = living if scope == 'any_other' else same
    if scope in ('other', 'other_student', 'any_other', 'panicked_other'):
        selected = [c for c in selected if c.id != source]
    if scope in ('student', 'other_student'):
        selected = [c for c in selected if 'student' in CHARACTERS[c.id].traits]
    if scope == 'panicked_other':
        selected = [c for c in selected if c.paranoia >= CHARACTERS[c.id].limit]
    targets = [c.id for c in selected]
    if scope == 'same_or_location':
        targets.append(s.location)
    return targets

def _ability_options(self, source, ability, *, private=False):
    c = self.state.characters[source]
    key = f'goodwill:{source}:{ability.id}'
    used_day = self.day_used if private else self.public_day_used
    used_loop = self.loop_used if private else self.public_loop_used
    ability_counter = self._count(c, 'goodwill')
    if not c.alive or ability_counter < ability.threshold or key in used_day or (ability.once and key in used_loop):
        return []
    targets = self._scoped_targets(source, ability.scope)
    label = f'{c.name} · {ability.text}'
    results = []
    if ability.kind in ('counter', 'adjust'):
        for amount in (1, -1) if ability.kind == 'adjust' else (ability.amount,):
            results += [option(f'{label} → {self.name(t)} {COUNTER_NAMES[ability.counter]} {amount:+}', [op('counter', target=t, counter=ability.counter, amount=amount)]) for t in targets]
    elif ability.kind in ('reveal', 'kill', 'revive', 'guard'):
        results = [option(f'{label} → {self.name(t)}', [op(ability.kind, target=t)]) for t in targets]
    elif ability.kind == 'purify' and c.location == 'shrine':
        results = [option(label, [op('counter', target='shrine', counter='intrigue', amount=-1)])]
    elif ability.kind == 'release' and 'patient' in self.roles and self.state.characters['patient'].alive:
        results = [option(label, [op('release')])]
    elif ability.kind == 'protect':
        results = [option(label, [op('protect')])]
    elif ability.kind == 'prevent_incident':
        results = [option(label, [op('prevent_incident', target=source)])]
    elif ability.kind == 'recover':
        results = [option(f'{label} → {self._deck(self.state.leader)[card].name}', [op('recover', actor=self.state.leader, card=card)]) for card in self.state.discarded[self.state.leader]]
    elif ability.kind == 'culprit':
        results = [option(f"{label} → 第 {r['day']} 天的{INCIDENT_NAMES[r['kind']]}", [op('culprit', day=r['day'])]) for r in self.incident_records if r['happened']]
    elif ability.kind == 'plot':
        for plot in MODULE_PLOTS[self.module]:
            if PLOTS[plot][1] == 'X':
                results.append(option(f'{label}；声明：{PLOTS[plot][0]}', [op('informer', excluded=plot)]))
    elif ability.kind == 'transfer':
        others = self._scoped_targets(source, 'other')
        for a in others:
            for b in others:
                if a == b:
                    continue
                counters = STANDARD_COUNTERS
                for counter in (*counters, 'guard'):
                    count = self.guards[a] if counter == 'guard' else getattr(self.state.characters[a], counter)
                    if count:
                        results.append(option(f"{label}：{self.name(a)} → {self.name(b)}，{COUNTER_NAMES.get(counter, '护卫')}", [op('transfer', source=a, target=b, counter=counter)]))
    for result in results:
        result.update(key=key, once=ability.once, source=source, ability=ability.id, unrefusable=ability.unrefusable, goodwill=True)
    return results

def options(self, actor):
    """Private choices MUST only be returned to the controlling actor."""
    if actor != self.controller:
        return []
    phase = self.state.phase
    if self._pending:
        return deepcopy(self._pending['options'])
    if not self._timing_optional_ready():
        return []
    result = []
    if phase == 'action_counters':
        for c in self._living():
            key = f'cultist:{c.id}'
            if self.roles[c.id] == 'cultist' and self._available_key(key):
                result.append(option(f'{c.name}（邪教徒）：忽略{LOCATIONS[c.location]}及该区域角色的禁止密谋', [op('ignore_intrigue', location=c.location)], key=key))
    elif phase == 'master_abilities':
        for c in self._living():
            if self._has(c.id, 'brain'):
                targets = self._scoped_targets(c.id, 'same_or_location')
                result += self._counter_options(c.id, f'brain:{c.id}', targets, 'intrigue', 1, f'{c.name}（主谋）')
            if self._has(c.id, 'conspiracy'):
                result += self._counter_options(c.id, f'conspiracy:{c.id}', self._scoped_targets(c.id, 'same'), 'paranoia', 1, f'{c.name}（传谣能力）')
            if c.id == 'doctor' and self.roles[c.id] in REFUSAL:
                for choice in self._ability_options(c.id, CHARACTERS[c.id].abilities[0], private=True):
                    choice['goodwill'] = False
                    result.append(choice)
        if 'rumor' in self.scenario['subplots']:
            result += self._counter_options(None, 'plot:rumor', list(LOCATIONS), 'intrigue', 1, '流言四起（每轮一次）', True)
    elif phase == 'goodwill':
        for c in self._living():
            for ability in CHARACTERS[c.id].abilities:
                result += self._ability_options(c.id, ability)
    elif phase == 'day_end':
        for c in self._living():
            if self._has(c.id, 'killer'):
                key = f'killer:character:{c.id}'
                if self._available_key(key):
                    for t in self._living():
                        if self.roles[t.id] == 'key' and t.id != c.id and (t.location == c.location) and (self._count(t, 'intrigue') >= 2):
                            result.append(option(f'{c.name}（杀手）：使{t.name}死亡', [op('kill', target=t.id)], key=key))
                key = f'killer:heroes:{c.id}'
                if self._count(c, 'intrigue') >= 4 and self._available_key(key):
                    result.append(option(f'{c.name}（杀手）：使主人公死亡', [op('heroes_die')], key=key))
            if self._has(c.id, 'lover') and c.paranoia >= 3 and (c.intrigue >= 1):
                key = f'lover:{c.id}'
                if self._available_key(key):
                    result.append(option(f'{c.name}（求爱者）：使主人公死亡', [op('heroes_die')], key=key))
            traveler_ready = c.goodwill <= 2
            if self._has(c.id, 'time_traveler') and self.state.round == self.scenario['days'] and traveler_ready:
                key = f'time_traveler:{c.id}'
                if self._available_key(key):
                    result.append(option(f'{c.name}（时间旅行者）：使主人公失败', [op('lose')], key=key))
    elif phase == 'refusal':
        request = self._request
        if request.get('already_used'):
            return [option('本日已结算此能力；公开宣布本次没有效果', refuse=True)]
        refusal = None if request['unrefusable'] else REFUSAL.get(self.roles[request['source']])
        if refusal != 'mandatory':
            result.append(option('执行已声明的友好能力', request['effects'], accept=True))
        if refusal:
            result.append(option('拒绝；公开宣布能力没有效果（仍计入次数）', refuse=True))
        return result
    if phase in ('action_counters', 'master_abilities', 'goodwill', 'day_end'):
        result.append(option('结束本阶段 / 不再发动可选能力', finish=True))
    return deepcopy(result)

def _choose(self, actor, index):
    options = self.options(actor)
    if type(index) is not int or not 1 <= index <= len(options):
        raise RuleError('选择编号无效；请重新查看 options')
    selected = options[index - 1]
    if self._pending:
        source = self._pending_source
        self._pending = None
        self._pending_source = None
        self._decision_actor = None
        self._queue = [SourcedEffect(legacy_effect(effect), source) for effect in selected['effects']] + self._queue
        self._drain()
        return
    if selected.get('finish'):
        self.ruleset.phases.resolve(self.state.phase).execute(self, actor, 'next', {})
        return
    already_used = 'key' in selected and selected['key'] in self.day_used
    if 'key' in selected:
        self._mark(selected['key'], selected.get('once', False))
    if selected.get('goodwill'):
        selected['already_used'] = already_used
        self.public_day_used.add(selected['key'])
        if selected.get('once'):
            self.public_loop_used.add(selected['key'])
        self._request = selected
        self.state.phase = 'refusal'
        self._event('goodwill_requested', f"领队声明：{selected['label']}。")
        return
    if self.state.phase == 'refusal':
        request = self._request
        self._request = None
        if selected.get('refuse'):
            rei_once = False
            if rei_once:
                for used in (self.day_used, self.loop_used, self.public_day_used, self.public_loop_used):
                    used.discard(request['key'])
            detail = '本轮一次能力被拒绝，不计为已使用；友好不消耗。' if rei_once else '这项友好能力没有效果；次数已使用，友好不消耗。'
            self._event('ability_no_effect', detail)
            self.state.phase = 'goodwill'
            return
        self._return_phase = 'goodwill'
    else:
        self._return_phase = self.state.phase
    self._queue = self._optional_effects(selected, actor)
    self._drain()

OPERATIONS = {
    '_available_key': _available_key,
    '_mark': _mark,
    '_counter_options': _counter_options,
    '_scoped_targets': _scoped_targets,
    '_ability_options': _ability_options,
    'options': options,
    '_choose': _choose,
}
