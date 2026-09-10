"""Basic Tragedy X endgame policy."""

FINAL_GUESS = True
EARLY_FINAL_GUESS = True


def _plot_loss(game, main):
    state = game.state
    if main == "sealed":
        return state.locations["shrine"] >= 2
    if main == "sign":
        return any(character.intrigue >= 2 and game.roles[character.id] == "key"
                   for character in state.characters.values())
    if main == "change":
        return any(record["kind"] == "butterfly" and record["happened"]
                   for record in game.incident_records)
    if main == "bomb":
        return any(state.locations[game._loop_initial_locations[character.id]] >= 2
                   for character in state.characters.values()
                   if game.roles[character.id] == "witch")
    return False


OPERATIONS = {"_plot_loss": _plot_loss}
