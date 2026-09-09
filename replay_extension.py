"""Fork a verified replay checkpoint into a later end date without altering its parent.

The first implementation requires the exact same immutable market manifest and
engine/rate fingerprint. A newly appended dataset needs separate prefix validation.
"""
import copy
import hashlib
import math
from backtest_audit import read_chunk, ReplayAuditStore
from replay_checkpoints import fingerprint


def extend_checkpoint(parent, old_payload, new_payload, manifest_bytes, data_root,
                      parent_audit, child_audit, child_journal):
    from btc_trade_backtest import us_time, milliseconds
    if child_journal.latest() is not None:
        raise ValueError('Extension destination already has a checkpoint')
    if not parent or parent['identity'] != fingerprint(old_payload, manifest_bytes, data_root):
        raise ValueError('Parent engine, rates, parameters or market manifest differ')
    old = {k: v for k, v in old_payload.items() if k != 'backtest_end'}
    new = {k: v for k, v in new_payload.items() if k != 'backtest_end'}
    if old != new:
        raise ValueError('Only the end date may change for an extension')
    lo, hi = us_time(old_payload['backtest_end']), us_time(new_payload['backtest_end'])
    if hi <= lo or parent['source_cursor_exclusive_us'] >= lo:
        raise ValueError('Extension must follow a checkpoint strictly before the old end')
    state = copy.deepcopy(parent)
    state['identity'] = fingerprint(new_payload, manifest_bytes, data_root)
    state['extension_parent'] = dict(identity=parent['identity'], end=old_payload['backtest_end'],
                                    cursor_us=parent['source_cursor_exclusive_us'])
    # Keep sampled charts bounded; historical financial/audit rows are unchanged.
    interval = milliseconds(new_payload['execution_interval_seconds'], 'Execution interval', 1)
    sample = max(1, math.ceil((hi-us_time(new_payload['backtest_start']))/interval/2000))
    previous = state['state']['sample_every']
    stride = max(1, math.ceil(sample/previous))
    state['state']['series'] = state['state']['series'][::stride]
    state['state']['sample_every'] = sample
    target = ReplayAuditStore(child_audit)
    for saved in state['audit'].values():
        for entry in saved['entries']:
            # Validate complete compressed and decompressed identity before publication.
            for _ in read_chunk(parent_audit, entry):
                pass
            data = parent_audit.get(entry['object'])
            if hashlib.sha256(data).hexdigest() != entry['compressed_sha256']:
                raise ValueError('Parent audit changed during extension')
            target.put(entry['object'], data)
    child_journal.save(state['source_cursor_exclusive_us'], state)
    return state
