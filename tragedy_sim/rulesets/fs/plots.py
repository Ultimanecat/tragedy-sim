"""First Steps plot/endgame policy (there is no final guess)."""

FINAL_GUESS = False
EARLY_FINAL_GUESS = False


def _plot_loss(game, main):
    state = game.state
    if main == "protect":
        return state.locations["school"] >= 2
    if main == "avenger":
        return any(state.locations[game._loop_initial_locations[character.id]] >= 2
                   for character in state.characters.values()
                   if game.roles[character.id] == "brain")
    return False


OPERATIONS = {"_plot_loss": _plot_loss}
