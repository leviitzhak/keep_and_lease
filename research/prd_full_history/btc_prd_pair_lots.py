"""Research reference for current-leg PRD and a ladder derived from owned lots.

Not an exchange/account ledger. Quantities are frozen reference BTC. Cash, native
contract netting, pending reservations and atomic persistence belong to the future
funded replay. Completed-leg execution history never becomes ladder credit.
"""
from dataclasses import dataclass, replace
from math import floor


@dataclass(frozen=True)
class Lot:
    id: str
    quantity: float
    long_apr: float | None
    short_apr: float | None

    def __post_init__(self):
        if self.quantity <= 0:
            raise ValueError('quantity must be positive')

    @property
    def prd(self):
        if self.long_apr is None or self.short_apr is None:
            return None
        return self.short_apr - self.long_apr


def weighted_prd(lots):
    if not lots or any(x.prd is None for x in lots):
        return None
    return sum(x.quantity * x.prd for x in lots) / sum(x.quantity for x in lots)


def remove(lots, quantity):
    """FIFO removal, returning immutable remaining and removed fragments."""
    if quantity < 0 or quantity > sum(x.quantity for x in lots) + 1e-12:
        raise ValueError('removal exceeds owned quantity')
    remaining, removed = [], []
    for x in lots:
        take = min(quantity, x.quantity)
        if take > 1e-12:
            removed.append(replace(x, quantity=take))
        if x.quantity - take > 1e-12:
            remaining.append(replace(x, quantity=x.quantity-take))
        quantity -= take
    return remaining, removed


def replace_leg(lots, quantity, side, executed_apr, transfer_id):
    if side not in ('long', 'short'):
        raise ValueError('unknown replacement side')
    remaining, moved = remove(lots, quantity)
    return remaining, [replace(x, id=f'{transfer_id}/{x.id}',
                              **{side + '_apr': executed_apr}) for x in moved]


def ladder(lots, base, increment, amount):
    """Declared research policy: fill contiguous rungs from actual current PRDs.

    Sort low-PRD lots first (ID breaks ties); fill each rung only with quantity
    whose current-leg PRD reaches that rung. Split fragments at amount boundaries.
    Equality qualifies, consistent with a fill at its intended opening threshold.
    Low/unknown-PRD quantity remains owned but cannot qualify a higher rung. No
    pair-average PRD is substituted for individual fills. Derive again on closure
    or replacement, so there is no independent transferable counter to drift.
    """
    if increment <= 0 or amount <= 0:
        raise ValueError('positive increment and rung amount required')
    occupancy, assignments, counted = [], [], 0.0
    for x in sorted(lots, key=lambda v: (float('-inf') if v.prd is None else v.prd, v.id)):
        q = x.quantity
        while q > 1e-12:
            level = floor((counted + 1e-12) / amount)
            threshold = base + level * increment
            if x.prd is None or x.prd + 1e-12 < threshold:
                break
            take = min(q, (level + 1) * amount - counted)
            if level == len(occupancy):
                occupancy.append(0.0)
            occupancy[level] += take
            assignments.append(dict(lot=x.id, rung=level, quantity=take, prd=x.prd))
            counted += take
            q -= take
    level = floor((counted + 1e-12) / amount)
    return dict(owned_quantity=sum(x.quantity for x in lots), counted_quantity=counted,
                unqualified_quantity=max(0, sum(x.quantity for x in lots)-counted),
                next_threshold=base + level * increment, occupancy=occupancy,
                assignments=assignments)
