"""Dependency-free full-fill contractual baseline (no fill-probability model)."""


def analytical(obs, actions, goal, instruments):
    current = goal.outcome(obs.ledger.holdings(instruments))['utility']
    scores = []
    for action in actions:
        ledger = obs.ledger.clone()
        for order in action.orders:
            ledger.fill(instruments[order.symbol], order.quantity, order.limit)
        scores.append(goal.outcome(ledger.holdings(instruments))['utility'] - current)
    # First maximum matches the original np.argmax tie rule: wait wins zero ties.
    return max(range(len(actions)), key=scores.__getitem__)
