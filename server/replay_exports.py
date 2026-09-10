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
    symbols = sorted(set(result['trade_replay'].get('end_mark_age_seconds', {})) | {'SPOT'})
    def valuations():
        for row in selected_rows(store, manifest, 'btc_trade_valuations', start, end):
            def values(n, r=row):
                opening = r['starting_nav'] * capital
                return [r['date'], r['nav_usd'], r['cash_usd'], (f'B{n}-C{n}', r['nav_usd']-r['cash_usd']),
                        r['futures_notional_usd'], r['direct_nav'], r['fees_usd'], r['return_fraction'],
                        r['reconstruction_error_usd'], opening, (f'B{n}/J{n}-1', r['nav_usd']/opening-1),
                        r['units'], r['targets'], r['mark_us'], r['mark_ids'], *[r['units'].get(s,0) for s in symbols]]
            yield values
    event_fields = ['date', 'kind', 'symbol', 'order_id', 'trade_id', 'signed_btc', 'price', 'fee_usd', 'cash_usd', 'nav_usd', 'reported_us']
    def events():
        for row in selected_rows(store, manifest, 'btc_trade_events', start, end):
            yield [row.get(k) for k in event_fields] + [row]
    overview = [['Selected start UTC', start], ['Selected end UTC', end], ['Initial capital USD', capital],
                ['Rows', 'All stored valuations and order/fill events within the inclusive UTC bounds; no resimulation or chart sampling.'],
                ['Opening NAV', 'Value immediately before each valuation interval; the first selected interval can start before the selected bound.'],
                ['Timestamps', 'UTC ISO text preserves microseconds. Returns are fractions. Units and mark identifiers retain the original JSON records.'],
                ['Futures', 'Notional exposure is not additive to NAV. Cash includes Treasury collateral. Futures mark prices were not saved in valuation rows; fill prices are in Events.'],
                ['Run identity', result.get('benchmark', {}).get('report_uri', manifest.get('base_url', 'Stored server backtest'))],
                ['Full-run start', result['summary']['start']], ['Full-run end', result['summary']['end']],
                *[['Assumption', a] for a in result['trade_replay'].get('assumptions', [])]]
    yield from workbook([
        ('Overview', ['Description', 'Value'], overview),
        ('Valuations', ['UTC timestamp', 'NAV USD', 'Cash / Treasury USD', 'Direct BTC value USD', 'Long futures notional USD', 'Direct holding index', 'Cumulative fees USD', 'Interval return fraction', 'NAV reconstruction error USD', 'Opening NAV USD', 'Return from NAV fraction', 'Units by instrument', 'Target units by instrument', 'Mark timestamps (microseconds)', 'Mark trade IDs', *['Units: '+s for s in symbols]], valuations()),
        ('Events', event_fields + ['Complete event record'], events()),
        ('Parameters', ['Parameter', 'Saved value'], result['parameters'].items())])
