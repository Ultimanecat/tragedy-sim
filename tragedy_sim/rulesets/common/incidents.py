"""Shared First Steps and Basic Tragedy X rules."""
from ...cards import COUNTER_NAMES, LOCATIONS, STANDARD_COUNTERS
from ...catalog import CHARACTERS, INCIDENT_NAMES
from ...effects.vocabulary import op, option

def _incident(self):
    scheduled_day = self._scheduled_day()
    incident = next((i for i in self.scenario['incidents'] if i['day'] == scheduled_day), None)
    if incident is None:
        self._event('no_incident', '今日没有预定事件。')
        self._begin_night()
        return
    culprit = self.state.characters[incident['culprit']]
    kind = incident['kind']
    threshold = CHARACTERS[culprit.id].limit
    prophet_alive = any((False for c in self.state.characters.values()))
    prophet_blocks = any((False for c in self.state.characters.values()))
    forced = False
    incident_paranoia = culprit.paranoia
    prevented = culprit.id in self._prevented_incident_culprits
    happened = culprit.alive and (not prevented) and (forced or (not prophet_blocks and incident_paranoia >= threshold))
    public_kind = incident.get('public_kind', kind)
    record = {'day': self.state.round, 'kind': public_kind, 'happened': happened, 'effective': False}
    self.incident_records.append(record)
    self._event('incident_status', f'第 {self.state.round} 天「{INCIDENT_NAMES[public_kind]}」：' + ('发生。' if happened else '未发生。'), incident=public_kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    self._incident_effect = False
    living = self._living()
    choices, effects = ([], [])
    if kind in ('murder', 'faraway'):
        targets = [c for c in living if c.id != culprit.id and c.location == culprit.location] if kind == 'murder' else [c for c in living if c.intrigue >= 2]
        choices = [option(f'使{c.name}死亡', [op('kill', target=c.id)]) for c in targets]
    elif kind == 'suicide':
        effects = [op('kill', target=culprit.id)]
    elif kind == 'hospital':
        if self.state.locations['hospital'] >= 1:
            effects.append(op('kill_many', targets=[c.id for c in living if c.location == 'hospital']))
        if self.state.locations['hospital'] >= 2:
            effects.append(op('heroes_die'))
    elif kind == 'foul_play':
        effects = [op('counter', target='shrine', counter='intrigue', amount=2)]
    elif kind == 'malicious_rumor':
        effects = [op('counter', target=c.id, counter='paranoia', amount=2) for c in living if c.location == culprit.location]
    elif kind == 'poison_gas':
        choices = [option(f'{LOCATIONS[culprit.location]}与{LOCATIONS[location]}各获得密谋 +1', [op('counter', target=culprit.location, counter='intrigue', amount=1), op('counter', target=location, counter='intrigue', amount=1)]) for location in LOCATIONS if location != culprit.location]
    elif kind == 'exposure':
        same = [c for c in living if c.location == culprit.location]
        for index, first in enumerate(same):
            for second in same[index:]:
                add_effects = [op('counter', target=first.id, counter='goodwill', amount=1), op('counter', target=second.id, counter='goodwill', amount=1)]
                choices.append(option(f'放置 2 友好：{first.name}、{second.name}', add_effects))
                if first.id == second.id and first.goodwill >= 2:
                    choices.append(option(f'移除 2 友好：{first.name}', [op('counter', target=first.id, counter='goodwill', amount=-2)]))
                elif first.id != second.id and first.goodwill and second.goodwill:
                    choices.append(option(f'移除 2 友好：{first.name}、{second.name}', [op('counter', target=first.id, counter='goodwill', amount=-1), op('counter', target=second.id, counter='goodwill', amount=-1)]))
    elif kind == 'confession':
        effects = [op('reveal', target=culprit.id)]
    elif kind == 'missing':
        choices = [option(f'将{culprit.name}移至{LOCATIONS[loc]}，随后所在版图密谋 +1', [op('move', target=culprit.id, location=loc), op('missing_intrigue', target=culprit.id)]) for loc in LOCATIONS if loc not in culprit.forbidden]
    elif kind in ('unease', 'spreading'):
        counter, amount = ('paranoia', 2) if kind == 'unease' else ('goodwill', -2)
        for a in living:
            follow = [option(f"{b.name}：{('密谋 +1' if kind == 'unease' else '友好 +2')}", [op('counter', target=b.id, counter='intrigue' if kind == 'unease' else 'goodwill', amount=1 if kind == 'unease' else 2)]) for b in living if b.id != a.id]
            choices.append(option(f'{a.name}：{COUNTER_NAMES[counter]} {amount:+}', [op('counter', target=a.id, counter=counter, amount=amount), op('choice', prompt='选择另一个目标', options=follow)]))
    elif kind == 'butterfly':
        choices = [option(f'{c.name}：{COUNTER_NAMES[counter]} +1', [op('counter', target=c.id, counter=counter, amount=1)]) for c in living if c.location == culprit.location for counter in STANDARD_COUNTERS]
    if kind in ('murder', 'faraway', 'missing', 'unease', 'spreading', 'butterfly', 'poison_gas', 'exposure'):
        effects = [op('choice', prompt=f'结算{INCIDENT_NAMES[kind]}：选择合法目标', options=choices)]
    self._queue = effects + [op('incident_done'), op('night')]
    self._return_phase = 'day_end'
    self._drain()

def _ahr_incident(self, incident):
    kind = incident['kind']
    culprit = self.state.characters[incident['culprit']]
    threshold = CHARACTERS[culprit.id].limit - (kind == 'impulsive_murder')
    score = self._count(culprit, 'intrigue') if kind == 'imaginary_incident' else self._count(culprit, 'goodwill') if self.ex_gauge % 2 or kind == 'hope_light' else self._count(culprit, 'paranoia')
    happened = culprit.alive and (kind == 'dimension_swap' or score >= threshold)
    self.incident_records.append({'day': self.state.round, 'kind': kind, 'happened': happened, 'effective': False})
    self._event('incident_status', f'第 {self.state.round} 天「{INCIDENT_NAMES[kind]}」：' + ('发生。' if happened else '未发生。'), incident=kind, happened=happened)
    if not happened:
        self._begin_night()
        return
    self._incident_before = self._public_board()
    living = self._living()

    def murder_effects():
        return [op('choice', prompt='冲动杀人：选择同区域另一名角色死亡', options=[option(f'使{target.name}死亡', [op('kill', target=target.id)]) for target in living if target.id != culprit.id and target.location == culprit.location])]

    def distortion_effects():
        return [op('choice', prompt='次元歪曲：是否触发世界线变动', options=[option('触发世界线变动', [op('ahr_world_shift', reason='次元歪曲')]), option('不触发世界线变动', [])]), op('choice', prompt='次元歪曲：选择不安 +2 的角色', options=[option(f'{first.name}不安 +2', [op('counter', target=first.id, counter='paranoia', amount=2), op('choice', prompt='选择另一名角色友好 +2', options=[option(f'{second.name}友好 +2', [op('counter', target=second.id, counter='goodwill', amount=2)]) for second in living if second.id != first.id])]) for first in living])]

    def lost_effects():
        choices = []
        for target in living:
            if target.id == culprit.id or target.location != culprit.location:
                continue
            choices.append(option(f'移动{target.name}', [op('choice', prompt='选择目的地', options=[option(LOCATIONS[board], [op('move', target=target.id, location=board), op('move', target=culprit.id, location=self._loop_initial_locations[culprit.id])]) for board in LOCATIONS if board not in target.forbidden])]))
        return [op('choice', prompt='遗失之物：选择同区域另一名角色', options=choices)]
    if kind == 'impulsive_murder':
        effects = murder_effects()
    elif kind == 'dimension_swap':
        effects = [op('ahr_world_shift', reason='次元转换')]
    elif kind == 'dimension_distortion':
        effects = distortion_effects()
    elif kind == 'dimension_break':
        effects = [op('choice', prompt='次元断层：是否触发世界线变动', options=[option('触发世界线变动', [op('ahr_world_shift', reason='次元断层')]), option('不触发世界线变动', [])]), op('ahr_dimension_break', target=culprit.id)]
    elif kind == 'lost_property':
        effects = lost_effects()
    elif kind == 'imaginary_incident':
        effects = [op('choice', prompt='空想事件：选择一种事件效果', options=[option('冲动杀人', murder_effects()), option('次元歪曲', distortion_effects()), option('遗失之物', lost_effects())])]
    elif kind == 'hospital':
        effects = []
        if self.state.locations['hospital'] >= 1:
            effects.append(op('kill_many', targets=[c.id for c in living if c.location == 'hospital']))
        if self.state.locations['hospital'] >= 2:
            effects.append(op('heroes_die'))
    elif kind == 'will':
        effects = [op('kill', target=culprit.id), op('ahr_will')]
    elif kind == 'singularity':
        if self.ex_gauge % 2 == 0:
            if not self._ahr_singularity_occurred:
                effects = [op('ahr_singularity_first'), op('heroes_die')]
            else:
                effects = [op('ahr_world_shift', reason='奇点再次发生')]
        else:
            effects = [*[op('counter', target=c.id, counter='intrigue', amount=1) for c in living if c.location == culprit.location], op('ahr_singularity_hidden', target=culprit.id)]
    elif kind == 'hope_light':
        effects = [op('choice', actor=self.state.leader, prompt='隙间阳光：领队选择希望目标', options=[option(f'{c.name}希望 +1', [op('counter', target=c.id, counter='hope', amount=1)]) for c in living])]
    else:
        effects = [op('choice', prompt='绝望之暗：选择绝望目标', options=[option(f'{c.name}绝望 +1', [op('counter', target=c.id, counter='despair', amount=1)]) for c in living])]
    self._queue = effects + [op('incident_done'), op('night')]
    self._return_phase = 'day_end'
    self._drain()

def _record_incident_end(self):
    if self._incident_before is not None:
        changed = self._incident_effect or self._incident_before != self._public_board()
        self.incident_records[-1]['effective'] = changed
        self._event('incident_ended', '事件结算完成。' if changed else '事件已经发生，但未产生效果。', effective=changed)
        self._incident_before = None

OPERATIONS = {
    '_incident': _incident,
    '_ahr_incident': _ahr_incident,
    '_record_incident_end': _record_incident_end,
}
