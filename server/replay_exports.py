"""Bounded-memory XLSX exports of stored replay rows, with no recalculation run."""
from datetime import datetime, timedelta, timezone
import io
import json
import math
import re
import zipfile
from xml.sax.saxutils import escape

from backtest_audit import read_chunk

MAX_SHEET_ROWS = 1_048_576
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'

# These columns expose stored evidence only. In particular an older independent
# order/fill audit must never acquire a reconstructed transfer ID during export.
PAIRED_VALUATION_FIELDS = [
    'commodity_nav_btc', 'free_cash_usd', 'posted_cash_usd',
    'unsettled_pnl_usd', 'pending_variation_usd', 'reserved_cash_usd',
    'available_cash_usd', 'treasury_value_usd', 'liabilities_usd',
    'active_pair_id', 'transfer_status', 'unpaired_btc',
]
PAIRED_EVENT_FIELDS = [
    'pair_id', 'role', 'ticket_id', 'status', 'source_symbol', 'target_symbol',
    'source_quantity_btc', 'target_quantity_btc', 'source_filled_btc',
    'target_filled_btc', 'matched_source_btc', 'unpaired_btc', 'paired_fill_ratio',
    'fees_usd', 'reserved_usd', 'free_cash_usd', 'posted_cash_usd',
    'unsettled_pnl_usd', 'amount_usd', 'reservation_id', 'payment_id',
    'acknowledgement_us', 'limit_price',
    'revision', 'order_revision', 'fill_revision', 'observation_us', 'decision_started_us',
    'decision_ready_us', 'submitted_us', 'previous_limit_price', 'applied',
    'rejection_reason', 'counterpart_price', 'counterpart_fee_usd',
    'target_effective_lease', 'binding_constraint',
]
DECISION_FIELDS = [
    'accepted', 'reason', 'source_symbol', 'target_symbol',
    'source_quantity_btc', 'target_quantity_btc', 'source_cash_usd',
    'source_fraction', 'horizon_us', 'keep_btc', 'swap_btc', 'edge_btc',
    'required_edge_btc', 'entry_cost_usd',
    'diagnostics.initial_capital_usd', 'diagnostics.initial_btc',
    'diagnostics.source_sale_limit', 'diagnostics.target_buy_limit',
    'diagnostics.target_cash_usd', 'diagnostics.cash_reserve_usd',
    'diagnostics.exposure_quantity_change_btc',
    'diagnostics.keep.interest_usd', 'diagnostics.swap.interest_usd',
    'diagnostics.keep.futures_pnl_usd', 'diagnostics.swap.futures_pnl_usd',
    'diagnostics.keep.exit_cost_usd', 'diagnostics.swap.exit_cost_usd',
    'diagnostics.keep.minimum_cash_usd', 'diagnostics.swap.minimum_cash_usd',
    'diagnostics.keep.funding_feasible', 'diagnostics.swap.funding_feasible',
    'diagnostics.projected_break_even_days', 'diagnostics.cash_rate',
    'diagnostics.forecast_model', 'diagnostics.liquidity_assumption',
    'rate_snapshot.age_days', 'rate_snapshot.data_version',
]
TRANSFER_FIELDS = [
    'pair_id', 'status', 'reason', 'source_symbol', 'target_symbol',
    'source_quantity_btc', 'target_quantity_btc', 'source_filled_btc',
    'target_filled_btc', 'matched_source_btc', 'unpaired_btc', 'paired_fill_ratio',
    'source_value_usd', 'target_value_usd', 'fees_usd', 'reserved_usd',
    'submitted_us', 'completed_us', 'max_unpaired_btc', 'max_legging_seconds',
    'observed_lease', 'executed_price_only_lease', 'lease_price_deviation',
    'direction_adjusted_lease_deviation', 'completion_lease',
    'repricing_supported', 'target_effective_lease', 'executed_effective_lease',
    'effective_lease_shortfall',
    'source_vwap', 'target_vwap', 'matched_source_fees_usd', 'target_fees_usd',
    'effective_lease_expiry_us', 'effective_lease_rate_time_us', 'effective_lease_cash_rate',
    'decision.horizon_us', 'decision.keep_btc', 'decision.swap_btc',
    'decision.edge_btc', 'decision.required_edge_btc',
]
HORIZON_FIELDS = [
    'source_fraction', 'horizon_us', 'keep_btc', 'swap_btc', 'edge_btc',
    'required_edge_btc', 'reason',
]


def stored_value(row, path):
    """Read an explicit nested audit field without estimating missing values."""
    value = row
    for key in path.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def timestamp_text(value):
    if value is None:
        return None
    return (datetime(1970, 1, 1) + timedelta(microseconds=value)).isoformat(timespec='microseconds')


def utc(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec='microseconds')


def period(start, end, summary):
    start, end = utc(start), utc(end)
    if not utc(summary['start']) <= start < end <= utc(summary['end']):
        raise ValueError('Choose an increasing UTC period inside the completed backtest')
    return start, end


def stored_replay_period(manifest):
    """Include the owned opening position before the first valuation tick.

    The replay's first spot observation initializes its endowment immediately;
    its first valuation is only written at the next decision-clock boundary.
    New audits record the exact replay bounds as dataset metadata. Historical
    replay audits instead begin their event dataset with the initialization
    event, so its first chunk supplies the compatible opening bound. Do not
    take the minimum over every event: later bootstrap records can contain
    pre-window quote timestamps.
    """
    dataset = manifest['datasets']['btc_trade_valuations']
    entries = dataset['chunks']
    start = dataset.get('replay_start')
    if start is None:
        start = utc(entries[0]['start'])
        events = manifest['datasets'].get('btc_trade_events', {}).get('chunks', [])
        if events:
            start = min(start, utc(events[0]['start']))
    end = dataset.get('replay_end', entries[-1]['end'])
    return {'start': utc(start), 'end': utc(end)}


def selected_rows(store, manifest, product, start, end):
    for entry in manifest['datasets'].get(product, {}).get('chunks', []):
        if entry['end'] < start or entry['start'] > end:
            continue
        # Verify the whole bounded chunk even when a period cuts through it.
        for row in list(read_chunk(store, entry)):
            date = row.get('date')
            if date is None:
                date = (datetime(1970, 1, 1) + timedelta(microseconds=row['us'])).isoformat(timespec='microseconds')
            if start <= date <= end:
                yield row


def column(index):
    out = ''
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def cell(value, ref, header=False, wrap=False):
    style = ' s="1"' if header else ' s="3"' if wrap else ''
    if isinstance(value, tuple):
        formula, cached = value
        return f'<c r="{ref}" s="2"><f>{escape(formula)}</f><v>{cached}</v></c>'
    if value is None:
        return f'<c r="{ref}"/>'
    if isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value):
        return f'<c r="{ref}"{style or " s=\"2\""}><v>{value}</v></c>'
    if isinstance(value, (dict, list)):
        value = json.dumps(value, separators=(',', ':'), allow_nan=False)
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))
    if len(value) > 32767:
        raise ValueError('An audit field exceeds Excel cell capacity; download the raw audit')
    return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{escape(value)}</t></is></c>'


class Output(io.RawIOBase):
    def __init__(self):
        self.parts = []
        self.offset = 0
    def writable(self): return True
    def seekable(self): return False
    def tell(self): return self.offset
    def write(self, data):
        self.parts.append(data)
        self.offset += len(data)
        return len(data)
    def drain(self):
        parts, self.parts = self.parts, []
        yield from parts


def workbook(sheets):
    """Each (name, header, iterator) may span multiple Excel-sized sheets."""
    output, names = Output(), []
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
        for name, headers, rows in sheets:
            iterator, pending, part = iter(rows), None, 0
            while True:
                part += 1
                title = name if part == 1 else f'{name} {part}'
                names.append(title)
                notes = name in ('Overview', 'Parameters')
                with archive.open(f'xl/worksheets/sheet{len(names)}.xml', 'w', force_zip64=True) as sheet:
                    sheet.write((f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{NS}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>' + ''.join(f'<col min="{i}" max="{i}" width="{(40 if i == 1 else 110) if notes else (29 if i == 1 else 23)}" customWidth="1"/>' for i in range(1,len(headers)+1)) + '</cols><sheetData>').encode())
                    sheet.write(('<row r="1" ht="32" customHeight="1">' + ''.join(cell(v, column(i)+'1', True) for i,v in enumerate(headers,1)) + '</row>').encode())
                    row_number = 1
                    while row_number < MAX_SHEET_ROWS:
                        value = pending if pending is not None else next(iterator, None)
                        pending = None
                        if value is None: break
                        row_number += 1
                        if callable(value): value = value(row_number)
                        height = ' ht="60" customHeight="1"' if notes else ''
                        sheet.write((f'<row r="{row_number}"{height}>' + ''.join(cell(v, column(i)+str(row_number), wrap=notes) for i,v in enumerate(value,1)) + '</row>').encode())
                        if row_number % 128 == 0: yield from output.drain()
                    sheet.write((f'</sheetData><autoFilter ref="A1:{column(len(headers))}{row_number}"/></worksheet>').encode())
                yield from output.drain()
                pending = next(iterator, None)
                if pending is None: break
        archive.writestr('xl/styles.xml', f'''<styleSheet xmlns="{NS}"><numFmts count="1"><numFmt numFmtId="164" formatCode="#,##0.0000000000"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF17365D"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="4"><xf fontId="0" fillId="0" borderId="0" xfId="0"/><xf fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1"/></xf><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''')
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{NS}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i,n in enumerate(names,1)) + '</sheets><calcPr fullCalcOnLoad="1"/></workbook>')
        rel = 'http://schemas.openxmlformats.org/package/2006/relationships'
        base = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        archive.writestr('_rels/.rels', f'<Relationships xmlns="{rel}"><Relationship Id="rId1" Type="{base}officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/_rels/workbook.xml.rels', f'<Relationships xmlns="{rel}">' + ''.join(f'<Relationship Id="rId{i}" Type="{base}worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(names)+1)) + f'<Relationship Id="styles" Type="{base}styles" Target="styles.xml"/></Relationships>')
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' + ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(names)+1)) + '</Types>')
    yield from output.drain()


def replay_workbook(store, manifest, result, start, end):
    capital = float(result['trade_replay']['capital_usd'])
    paired = (result['trade_replay'].get('strategy') == 'cost_aware_paired' or
              result.get('parameters', {}).get('trade_strategy') == 'cost_aware_paired')
    symbols = sorted(set(result['trade_replay'].get('end_mark_age_seconds', {})) | {'SPOT'})
    def valuations():
        for row in selected_rows(store, manifest, 'btc_trade_valuations', start, end):
            def values(n, r=row):
                opening = r['starting_nav'] * capital
                futures = float(r.get('futures_notional_usd', 0) or 0)
                free = r.get('free_collateral_usd')
                if free is None:
                    free = float(r.get('cash_usd', 0) or 0) - abs(futures)
                ratio = r.get('collateralization_ratio')
                if ratio is None and abs(futures) > 1e-14:
                    ratio = float(r.get('cash_usd', 0) or 0) / abs(futures)
                # Funded NAV also includes unsettled futures P&L. Subtracting
                # cash would mislabel that P&L as direct BTC, so use the stored
                # spot value for that versioned policy.
                direct_value = (r.get('direct_btc_value_usd') if paired else
                                (f'B{n}-C{n}', r['nav_usd']-r['cash_usd']))
                return [r['date'], r['nav_usd'], r['cash_usd'], direct_value,
                        futures, r.get('target_futures_notional_usd'), free, ratio,
                        r.get('turnover_usd'), r['direct_nav'], r['fees_usd'], r['return_fraction'],
                        r['reconstruction_error_usd'], opening, (f'B{n}/N{n}-1', r['nav_usd']/opening-1),
                        r['units'], r['targets'], r['mark_us'], r['mark_ids'], *[r['units'].get(s,0) for s in symbols],
                        *([stored_value(r, k) for k in PAIRED_VALUATION_FIELDS] if paired else [])]
            yield values
    event_fields = ['date', 'kind', 'symbol', 'order_id', 'trade_id', 'side', 'signed_btc', 'price',
                    'observed_btc', 'fee_usd', 'cash_usd', 'nav_usd', 'reported_us', 'eligible_after_us',
                    'source_sequence', 'requested_btc', 'filled_btc', 'remainder_btc', 'reason']
    if paired:
        event_fields += PAIRED_EVENT_FIELDS
    def events():
        for row in selected_rows(store, manifest, 'btc_trade_events', start, end):
            yield [row.get(k) for k in event_fields] + [row]
    def transfer_rows():
        for row in selected_rows(store, manifest, 'btc_trade_events', start, end):
            if row.get('kind') in ('paired_transfer', 'paired_transfer_result'):
                yield [row['date'], row['kind'], timestamp_text(stored_value(row, 'decision.horizon_us')),
                       timestamp_text(row.get('submitted_us')), timestamp_text(row.get('completed_us')),
                       *[stored_value(row, k) for k in TRANSFER_FIELDS]]
    def decision_rows(alternatives=False):
        for row in selected_rows(store, manifest, 'btc_trade_events', start, end):
            if row.get('kind') != 'paired_decision':
                continue
            decision = row.get('decision')
            if not isinstance(decision, dict):
                continue
            identity = [row['date'], row.get('decision_id'), row.get('pair_id'), row.get('selected')]
            if alternatives:
                for candidate in stored_value(decision, 'diagnostics.alternatives') or []:
                    yield [*identity, decision.get('source_symbol'), decision.get('target_symbol'),
                           timestamp_text(candidate.get('horizon_us')),
                           *[stored_value(candidate, k) for k in HORIZON_FIELDS]]
            else:
                yield [*identity, timestamp_text(decision.get('horizon_us')),
                       *[stored_value(decision, k) for k in DECISION_FIELDS]]
    overview = [['Selected start UTC', start], ['Selected end UTC', end], ['Initial capital USD', capital],
                ['Rows', 'All stored valuations and order/fill events within the inclusive UTC bounds; no resimulation or chart sampling.'],
                ['Opening NAV', 'Value immediately before each valuation interval; the first selected interval can start before the selected bound.'],
                ['Timestamps', 'UTC ISO text preserves microseconds. Returns are fractions. Units and mark identifiers retain the original JSON records.'],
                ['Futures', 'Long futures are notional overlays collateralized by cash/Treasuries; their principal is not added to NAV. Actual notional is marked from filled units. Target notional is the desired futures exposure before partial-fill constraints.'],
                ['Collateral', 'Free collateral = cash/Treasuries minus absolute marked futures notional. Cash/futures collateral ratio is blank when no futures are held; a value below 1 would indicate a fully-funded collateral breach.'],
                ['Turnover', 'Cumulative filled turnover is based on actual simulated fills. The Events sheet exposes each order, fill, cancellation/replacement and observed trade volume used for that fill.'],
                ['Run identity', result.get('benchmark', {}).get('report_uri', manifest.get('base_url', 'Stored server backtest'))],
                ['Full-run start', result['summary']['start']], ['Full-run end', result['summary']['end']],
                *[['Assumption', a] for a in result['trade_replay'].get('assumptions', [])]]
    if paired:
        overview.extend([
            ['Funded NAV', 'Direct BTC value uses the stored spot value. NAV also includes free and posted cash, Treasury value, unsettled and pending variation, less liabilities; futures notional is not an asset.'],
            ['Funded collateral', 'The paired policy tests economic funding and immediately available cash separately. Posted cash and reserved cash are existing assets, never additions to NAV. Free collateral is funding equity less marked futures notional.'],
            ['Transfers', 'Paired transfers contains stored submission and result snapshots, including incomplete, cancelled and timed-out transfers. Do not sum these snapshots as separate transfers. pair_id links actual child fills, fees, reservations and funding in Events. Empty fields mean the source event did not report them.'],
            ['Decision forecasts', 'Transfer decisions shows recorded KEEP/SWAP forecasts in BTC at the same stored horizon. Horizon alternatives includes evaluated sizes/horizons and rejection reasons. These conditional forecasts are not realized returns. No historical entry cost is charged again by the exporter.'],
            ['Transfer periods', 'Every sheet contains only events inside the selected inclusive UTC period. A pair can start earlier or finish later; absence of a completion inside this export is not evidence of failure.'],
            ['Rate and fill measures', 'Observed, executed-price-only and completion lease measures are distinct from realized BTC return. All source quotes, clocks, model assumptions and raw event details remain on Events.'],
            ['Adaptive limits', 'For supported spot-to-futures entries, replacement requests record frozen observations and computation clocks. A limit changes only on an applied order_replace_arrival. The previous limit remains in force during transport; a rejected arrival does not change it.'],
            ['Effective lease', 'The entry lease includes matched spot-sale and futures-buy fees before annualization. It is distinct from the full-horizon net BTC forecast and from realized portfolio returns. Funding can bind before the economic price limit; separate child orders cannot guarantee an atomic paired fill.'],
            ['Legacy evidence', 'Transfer IDs are exported only when explicitly present in the stored audit. No pairs are inferred from unrelated historical fills.'],
        ])
        overview = [row for row in overview if row[0] != 'Collateral']
    sheets = [
        ('Overview', ['Description', 'Value'], overview),
        ('Valuations', ['UTC timestamp', 'NAV USD', 'Cash / Treasury USD', 'Direct BTC value USD',
                        'Actual long futures notional USD', 'Target long futures notional USD', 'Free collateral USD',
                        'Cash / futures collateral ratio', 'Cumulative filled turnover USD', 'Direct holding index',
                        'Cumulative fees USD', 'Interval return fraction', 'NAV reconstruction error USD',
                        'Opening NAV USD', 'Return from NAV fraction', 'Units by instrument', 'Target units by instrument',
                        'Mark timestamps (microseconds)', 'Mark trade IDs', *['Units: '+s for s in symbols],
                        *(PAIRED_VALUATION_FIELDS if paired else [])], valuations()),
        ('Events', event_fields + ['Complete event record'], events()),
        ('Parameters', ['Parameter', 'Saved value'], result['parameters'].items())]
    if paired:
        sheets.extend([
            ('Transfer decisions', ['date', 'decision_id', 'pair_id', 'selected', 'horizon_utc', *DECISION_FIELDS], decision_rows()),
            ('Paired transfers', ['date', 'kind', 'horizon_utc', 'submitted_utc', 'completed_utc', *TRANSFER_FIELDS], transfer_rows()),
            ('Horizon alternatives', ['date', 'decision_id', 'pair_id', 'selected', 'source_symbol',
                                      'target_symbol', 'horizon_utc', *HORIZON_FIELDS], decision_rows(alternatives=True)),
        ])
    yield from workbook(sheets)
