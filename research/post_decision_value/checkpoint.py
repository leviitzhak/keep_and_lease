"""Use existing bounded immutable replay journals, locally or via GcsCheckpoints."""
import dataclasses
from . import accounting, engine
from replay_checkpoints import DirectoryCheckpoints, GcsCheckpoints

TYPES = {c.__name__:c for c in (accounting.Instrument, accounting.Position, accounting.Cashflow,
    accounting.Ledger, accounting.Goal, engine.Trade, engine.Order, engine.Instruction,
    engine.ObservableState, engine.HiddenExchangeState, engine.Delays)}


def pack(value):
    if dataclasses.is_dataclass(value):
        return {'__type__':type(value).__name__, 'fields':{f.name:pack(getattr(value,f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value,tuple):return {'__tuple__':[pack(v) for v in value]}
    if isinstance(value,list):return [pack(v) for v in value]
    if isinstance(value,dict):return {k:pack(v) for k,v in value.items()}
    return value


def unpack(value):
    if isinstance(value,list):return [unpack(v) for v in value]
    if isinstance(value,dict):
        if '__type__' in value:return TYPES[value['__type__']](**{k:unpack(v) for k,v in value['fields'].items()})
        if '__tuple__' in value:return tuple(unpack(v) for v in value['__tuple__'])
        return {k:unpack(v) for k,v in value.items()}
    return value


def save_engine(store, tick, replay, identity):
    store.save(tick,dict(identity=identity,state=pack(replay.__dict__)))


def restore_engine(store, expected_identity):
    state=store.latest()
    if state['identity']!=expected_identity:raise ValueError('Replay identity mismatch')
    replay=engine.Engine.__new__(engine.Engine)
    replay.__dict__.update(unpack(state['state']))
    return replay
