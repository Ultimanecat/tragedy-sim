"""Compatibility effect handlers extracted from Game; rule semantics are unchanged."""

from .vocabulary import op


def wm_extinction(game, effect):
    if game._wm_extinction_occurred:
        game._event("extinction_repeated", "灭绝之灾此前已经发生过，本次不产生效果。")
    else:
        game._wm_extinction_occurred = True
        game._incident_effect = True
        game._event("extinction_first", "灭绝之灾首次发生：所有角色与主人公死亡。")
        game._queue = [op("kill_many", targets=[c.id for c in game._living()]),
                       op("heroes_die")] + game._queue


def wm_dagon_active(game, effect):
    game._wm_dagon_active = True
    game._incident_effect = True
    game._event("dagon_whisper_active",
                "达贡黑井之息已经发生：本轮之后若有其他事件发生，主人公在该事件阶段结束时死亡。")


HANDLERS = {
    "wm_extinction": wm_extinction,
    "wm_dagon_active": wm_dagon_active,
}
