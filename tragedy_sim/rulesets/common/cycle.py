"""Shared First Steps and Basic Tragedy X rules."""
from copy import deepcopy
from ...cards import ACTORS, ACTOR_NAMES, COUNTER_NAMES, PROTAGONISTS
from ...catalog import CHARACTERS, MODULES, REFUSAL, ROLE_NAMES
from ...engine import RuleError, State
from ...effects.vocabulary import op, option
from ...model import TimingId

def _configure_day_actions(self):
    self.configure_actions(mastermind=3,
                           protagonists=self._protagonists_from(self.state.leader))

def _begin_night(self):
    s = self.state
    s.leader = PROTAGONISTS[(PROTAGONISTS.index(s.leader) + 1) % 3]
    self._event('leader_changed', f'领队轮换为{ACTOR_NAMES[s.leader]}。', timing=TimingId.LEADER_CHANGE)
    s.phase = 'day_end'
    self._event('phase_changed', '进入日末结算：先结算强制效果，再由剧作家选择可选效果。')
    self._start_day_end_forced()

def _start_master_abilities_forced(self):
    """Activate compulsory mastermind-phase abilities before optional ones."""
    queue = []
    if 'sacred_tree' in self.state.characters:
        tree = self.state.characters['sacred_tree']
        if tree.present and tree.alive and self.roles['sacred_tree'] in REFUSAL:
            choices = [option(
                f"御神木（强制）：将一个{COUNTER_NAMES[counter]}指示物移给{target.name}",
                [op('transfer', source='sacred_tree', target=target.id, counter=counter)])
                for counter in COUNTER_NAMES if getattr(tree, counter)
                for target in self._living()
                if target.id != 'sacred_tree' and target.location == tree.location]
            if choices:
                queue.append(op('choice', prompt='御神木拥有拒绝友好的身份：剧作家必须转移一个指示物',
                                options=choices))
    self._return_phase = 'master_abilities'
    self._open_timing_window(TimingId.MASTERMIND_ABILITY, queue,
                             'core.mastermind_mandatory')

def _start_loop_placements(self):
    queue = self._character_loop_effects()
    if queue:
        self._return_phase = 'day_start'
        self._queue = queue
        self._drain()

def _start_day_end_forced(self):
    if self._night_forced_done:
        return
    self._night_forced_done = True
    self._return_phase = 'day_end'
    queue = [op('next_day_end_mandatory')]
    self._open_timing_window(TimingId.DAY_END, queue, 'core.day_end_mandatory')

def _queue_day_end_mandatory_batch(self):
    """Activate every mandatory effect on one snapshot, then resolve the batch."""
    living = self._living()
    victims = []
    target_choices = []
    loss_reasons = []
    ex_gain = 0
    for c in living:
        lone_targets = []
        for location in self._ability_locations(c.id):
            others = [target for target in living
                      if target.id != c.id and target.location == location]
            if len(others) == 1 and others[0].id not in lone_targets:
                lone_targets.append(others[0].id)
        serial_key = f'mandatory:serial:{c.id}'
        if self._has(c.id, 'serial') and serial_key not in self.day_used and lone_targets:
            self.day_used.add(serial_key)
            if len(lone_targets) == 1:
                victims.append(lone_targets[0])
            else:
                target_choices.append({
                    'prompt': f'{c.name}（杀人狂·强制）：选择能力使用区域',
                    'options': [option(f'使{self.name(target)}死亡',
                                       [op('mandatory_poison_mark', source=c.id,
                                           target=target)])
                                for target in lone_targets],
                })
        if c.id == 'part_timer' and sum(getattr(c, counter) for counter in COUNTER_NAMES) >= 3:
            victims.append(c.id)
    if not victims and (not target_choices) and (not loss_reasons):
        return
    self._mandatory_victims.extend(victims)
    follow = [op('resolve_mandatory_deaths')]
    if ex_gain:
        follow.append(op('ex_gauge', amount=ex_gain))
    if loss_reasons:
        follow.append(op('loop_loss', reason='；'.join(loss_reasons)))
    follow.append(op('next_day_end_mandatory'))
    choice_batch = [op('mandatory_choice_batch', choices=target_choices)] if target_choices else []
    self._queue = choice_batch + follow + self._queue

def _finish_loop(self, forced=False):
    self._record_incident_end()
    self._at_loop_end = True
    try:
        self._resolve_loop_end(forced)
    finally:
        self._at_loop_end = False

def _resolve_loop_end(self, forced=False):
    s = self.state
    loss = forced
    for c in s.characters.values():
        if self.roles[c.id] == 'friend' and (not c.alive):
            self._reveal_role(c.id)
            loss = True
            self.loss_reasons.append('亲友死亡')
    main = self.scenario['main_plot']
    plot_loss = self.ruleset.operations['_plot_loss'](self, main)
    if plot_loss:
        self.loss_reasons.append('规则 Y 失败条件')
    loss |= plot_loss
    self._queue, self._pending, self._request = ([], None, None)
    self._decision_actor = None
    self._decision_public_phase = None
    self._previous_dead = {c.id for c in s.characters.values() if not c.alive}
    self._previous_goodwill = {c.id for c in s.characters.values() if c.goodwill > 0}
    if not loss:
        self._win('protagonists', '本轮全部日期已结束，未触发失败条件。主人公获胜！')
    else:
        self._event('loop_lost', f'第 {s.loop} 轮回失败。', remaining=self.scenario['loops'] - s.loop)
        if s.loop < self.scenario['loops']:
            s.phase = 'loop_end'
            self._event('loop_waiting', f"还剩 {self.scenario['loops'] - s.loop} 轮。可自由讨论，确认后开始下一轮。")
        elif self.ruleset.final_guess:
            self._start_final_guess()
        else:
            self._win('mastermind', f'{self.module} 没有最终猜测；轮回已耗尽，剧作家获胜。')

def _restore_board(self, *, apply_loop_rules=False):
    old = self.state
    self.state = State(characters=deepcopy(self._initial), leader=old.leader, loop=old.loop, events=old.events)
    self.state.hands = {actor: list(self._deck(actor)) for actor in ACTORS}
    self.roles = dict(self.scenario['cast'])
    if self.roles.get('part_timer') not in (None, 'ordinary'):
        self.roles['part_timer_question'] = self.roles['part_timer']
    if apply_loop_rules:
        self._apply_current_roles()
    self.guards = dict.fromkeys(self.roles, 0)
    self.protected = False
    self.day_used.clear()
    self.loop_used.clear()
    self.public_day_used.clear()
    self.public_loop_used.clear()
    self._ignore_intrigue.clear()
    self._ignored_placement_indexes.clear()
    self._mandatory_victims.clear()
    self.mastermind_plays = 3
    self.protagonist_order = self._protagonists_from(self.state.leader)
    self._night_forced_done = False
    self._fake_incident_active = False
    self.ex_gauge = 0
    self._movement_locks.clear()
    self._sealed_boards.clear()
    self._prevented_incident_culprits.clear()
    self._simulated_incident = None
    self._choice_actor_override = None
    self._board_echo_placements.clear()
    self._loop_initial_locations = {cid: CHARACTERS[cid].start for cid in self.roles}
    self._apply_character_setup()
    self._announced_roles.clear()
    self.incident_records = []

def _new_loop(self):
    self._restore_board(apply_loop_rules=True)
    s = self.state
    s.loop += 1
    self._apply_character_setup()
    s.phase = 'day_start'
    self._event('loop_started', f'第 {s.loop} 轮回开始：位置、存活、计数物、手牌、护卫及本轮效果已重置；历史日志和已公开信息保留。', timing=TimingId.LOOP_START)
    if 'threads' in self.scenario['subplots']:
        for cid in self.roles:
            if cid in self._previous_goodwill:
                self._change(cid, 'paranoia', 2)
    for cid, role in self.scenario['cast'].items():
        if role == 'friend' and self.known_roles.get(cid, {}).get('role') == 'friend':
            self._change(cid, 'goodwill', 1)
    self._start_loop_placements()

def _start_final_guess(self):
    final_incidents = self.incident_records
    self.ex_cards = dict.fromkeys(self.ex_cards, 0)
    self._restore_board()
    self.incident_records = final_incidents
    self._queue, self._pending, self._request = ([], None, None)
    self._decision_public_phase = None
    self.state.phase = 'final_guess'
    self._guess_remaining = list(self.roles)
    detail = ''
    self._event('final_guess_started', f'进入最终猜测：棋盘还原，身份恢复剧本初始分配。领队逐个声明角色身份，全部正确才获胜，答错即失败{detail}。')

def _guess(self, cid, role):
    if self.state.phase != 'final_guess' or cid not in self._guess_remaining or role not in ROLE_NAMES:
        raise RuleError('当前不能猜测这个角色或身份；使用 rules 查看身份 ID')
    character = cid
    correct = role == self.scenario['cast'][cid]
    self._event('guess_result', f"最终猜测：{self.name(cid)}是{ROLE_NAMES[role]}——{('正确' if correct else '错误')}。", correct=correct)
    if not correct:
        self._win('mastermind', '最终猜测失败，剧作家获胜。')
    else:
        self._reveal_role(cid, truthful=True)
        self._guess_remaining.remove(cid)
        if not self._guess_remaining:
            self._win('protagonists', '所有身份猜测正确，主人公获胜！')

OPERATIONS = {
    '_configure_day_actions': _configure_day_actions,
    '_begin_night': _begin_night,
    '_start_master_abilities_forced': _start_master_abilities_forced,
    '_start_loop_placements': _start_loop_placements,
    '_start_day_end_forced': _start_day_end_forced,
    '_queue_day_end_mandatory_batch': _queue_day_end_mandatory_batch,
    '_finish_loop': _finish_loop,
    '_resolve_loop_end': _resolve_loop_end,
    '_restore_board': _restore_board,
    '_new_loop': _new_loop,
    '_start_final_guess': _start_final_guess,
    '_guess': _guess,
}
