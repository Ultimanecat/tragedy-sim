"""Public hand/slot constraints for today's hidden mastermind cards.

Targets never eliminate ineffective bluffs. Distinct physical card IDs are
enforced jointly, including the two separate Paranoia +1 cards.
"""

from .cards import deck


def has_distinct_assignment(domains, forced=None):
    allowed = {slot: set(cards) for slot, cards in domains.items()}
    for slot, card in (forced or {}).items():
        if card not in allowed.get(slot, ()):
            return False
        allowed[slot] = {card}
    owners = {}

    def assign(slot, seen):
        for card in sorted(allowed[slot]):
            if card in seen:
                continue
            seen.add(card)
            if card not in owners or assign(owners[card], seen):
                owners[card] = slot
                return True
        return False

    return all(assign(slot, set()) for slot in sorted(allowed, key=lambda slot: len(allowed[slot])))


def dark_card_domains(view):
    """Sound slot marginals using only public deck, discard and visible faces."""
    from .belief_matrix import BeliefContradiction

    values = tuple(deck("m", str(view.get("module", ""))))
    unavailable = set(view.get("discarded", {}).get("m", ()))
    disabled = set(view.get("public_setup", {}).get("special_rules", {}).get("disabled_mastermind_cards", ()))
    pending = [item for item in view.get("pending", ()) if item.get("actor") == "m"]
    domains, targets = {}, {}
    for slot, item in enumerate(pending):
        key = str(slot)
        card = item.get("card")
        # Revealed current cards can already have entered the discard list.
        allowed = ({card} if card else set(values).difference(unavailable))
        domains[key] = allowed.intersection(values).difference(disabled)
        targets[key] = str(item["target"])
    if not has_distinct_assignment(domains):
        raise BeliefContradiction("No distinct-card assignment satisfies today's public hand")
    # Three slots are small enough to compute full all-different arc support.
    for slot in domains:
        domains[slot] = {card for card in domains[slot]
                         if has_distinct_assignment(domains, {slot: card})}
    return values, domains, targets
