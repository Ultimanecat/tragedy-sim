"""Printed-rule deductions from received current-identity answers.

Never inspect a hidden cast here. Unknown dynamic rulesets require their own
observation adapter before treating a current answer as an initial identity.
"""


def initial_character_id(cid):
    return "part_timer" if cid == "part_timer_question" else cid


def initial_role_options(module, cid, role):
    if module not in {"FS", "BTX"} or cid == "part_timer":
        return None
    if module == "BTX" and role == "serial" and cid != "part_timer_question":
        return frozenset({"serial", "ordinary"})
    return frozenset({role})


def initial_role_deduction(module, cid, role):
    options = initial_role_options(module, cid, role)
    return ((initial_character_id(cid), next(iter(options)))
            if options is not None and len(options) == 1 else None)
