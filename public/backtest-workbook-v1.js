(function installKeepLeaseWorkbook(global) {
  "use strict";

  const TEMPLATE_VERSION = 2;
  const STYLE_IDS = {
    default: 0,
    title: 1,
    group: 2,
    header: 3,
    source: 4,
    formula: 5,
    percentSource: 6,
    percentFormula: 7,
    date: 8,
    integer: 9,
    note: 10,
    label: 11,
    checkHeader: 12,
    checkOk: 13,
  };

  function finiteNumber(value, fallback = null) {
    if (value && typeof value === "object" && Object.hasOwn(value, "value")) {
      return finiteNumber(value.value, fallback);
    }
    if (value === "" || value === null || value === undefined) return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function excelColumn(index) {
    let name = "";
    for (let number = index + 1; number; number = Math.floor((number - 1) / 26)) {
      name = String.fromCharCode(65 + ((number - 1) % 26)) + name;
    }
    return name;
  }

  function xmlEscape(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&apos;",
    })[character]);
  }

  function formula(expression, value = 0, style = "formula") {
    return { formula: expression.replace(/^=/, ""), value, style };
  }

  function styled(value, style = "default") {
    return { value, style };
  }

  function dateCell(value) {
    return { value, type: "date", style: "date" };
  }

  function asCell(value) {
    return value && typeof value === "object" && (
      Object.hasOwn(value, "formula") || Object.hasOwn(value, "value")
    ) ? value : { value };
  }

  function excelDateSerial(value) {
    if (!value) return null;
    const date = new Date(`${String(value).slice(0, 10)}T00:00:00Z`);
    if (!Number.isFinite(date.getTime())) return null;
    return date.getTime() / 86400000 + 25569;
  }

  function cellXml(rawValue, reference) {
    const cell = asCell(rawValue);
    const style = STYLE_IDS[cell.style || "default"] ?? STYLE_IDS.default;
    const styleAttribute = style ? ` s="${style}"` : "";
    if (cell.formula !== undefined) {
      const cached = cell.value;
      if (typeof cached === "string") {
        return `<c r="${reference}"${styleAttribute} t="str"><f>${xmlEscape(cell.formula)}</f><v>${xmlEscape(cached)}</v></c>`;
      }
      const numeric = finiteNumber(cached, 0);
      return `<c r="${reference}"${styleAttribute}><f>${xmlEscape(cell.formula)}</f><v>${numeric}</v></c>`;
    }
    if (cell.type === "date") {
      const serial = excelDateSerial(cell.value);
      return serial === null
        ? `<c r="${reference}"${styleAttribute}/>`
        : `<c r="${reference}"${styleAttribute}><v>${serial}</v></c>`;
    }
    if (typeof cell.value === "number" && Number.isFinite(cell.value)) {
      return `<c r="${reference}"${styleAttribute}><v>${cell.value}</v></c>`;
    }
    if (typeof cell.value === "boolean") {
      return `<c r="${reference}"${styleAttribute} t="b"><v>${cell.value ? 1 : 0}</v></c>`;
    }
    if (cell.value === null || cell.value === undefined || cell.value === "") {
      return `<c r="${reference}"${styleAttribute}/>`;
    }
    return `<c r="${reference}"${styleAttribute} t="inlineStr"><is><t xml:space="preserve">${xmlEscape(cell.value)}</t></is></c>`;
  }

  function worksheetXml(sheet) {
    const rowXml = sheet.rows.map((rawRow, rowIndex) => {
      const row = Array.isArray(rawRow) ? { cells: rawRow } : rawRow;
      const height = row.height ? ` ht="${row.height}" customHeight="1"` : "";
      const cells = row.cells.map((value, columnIndex) => (
        cellXml(value, `${excelColumn(columnIndex)}${rowIndex + 1}`)
      )).join("");
      return `<row r="${rowIndex + 1}"${height}>${cells}</row>`;
    }).join("");
    const maximumColumns = Math.max(1, ...sheet.rows.map((rawRow) => (
      Array.isArray(rawRow) ? rawRow.length : rawRow.cells.length
    )));
    const dimension = `A1:${excelColumn(maximumColumns - 1)}${Math.max(1, sheet.rows.length)}`;
    const columns = (sheet.widths || []).length
      ? `<cols>${sheet.widths.map((width, index) => (
          `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`
        )).join("")}</cols>`
      : "";
    const freeze = sheet.freeze
      ? `<pane xSplit="${sheet.freeze.xSplit || 0}" ySplit="${sheet.freeze.ySplit || 0}" topLeftCell="${sheet.freeze.topLeftCell}" activePane="bottomRight" state="frozen"/>`
      : "";
    const merges = (sheet.merges || []).length
      ? `<mergeCells count="${sheet.merges.length}">${sheet.merges.map((range) => `<mergeCell ref="${range}"/>`).join("")}</mergeCells>`
      : "";
    const filter = sheet.autoFilter ? `<autoFilter ref="${sheet.autoFilter}"/>` : "";
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>` +
      `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">` +
      `<dimension ref="${dimension}"/><sheetViews><sheetView workbookViewId="0">${freeze}</sheetView></sheetViews>` +
      `<sheetFormatPr defaultRowHeight="15"/>${columns}<sheetData>${rowXml}</sheetData>${filter}${merges}` +
      `<pageMargins left="0.25" right="0.25" top="0.5" bottom="0.5" header="0.2" footer="0.2"/>` +
      `</worksheet>`;
  }

  function stylesXml() {
    return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="3">
    <numFmt numFmtId="164" formatCode="0.000000;[Red](0.000000);-"/>
    <numFmt numFmtId="165" formatCode="0.0000%;[Red](0.0000%);-"/>
    <numFmt numFmtId="166" formatCode="yyyy-mm-dd"/>
  </numFmts>
  <fonts count="5">
    <font><sz val="10"/><name val="Aptos"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Aptos Display"/></font>
    <font><b/><color rgb="FF172033"/><sz val="10"/><name val="Aptos"/></font>
    <font><color rgb="FF008000"/><sz val="10"/><name val="Aptos"/></font>
    <font><b/><color rgb="FF166534"/><sz val="10"/><name val="Aptos"/></font>
  </fonts>
  <fills count="6">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF172033"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDCE6F1"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF2F2F2"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDCFCE7"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="3">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top/><bottom style="thin"><color rgb="FF9CA3AF"/></bottom><diagonal/></border>
    <border><left style="thin"><color rgb="FFD1D5DB"/></left><right style="thin"><color rgb="FFD1D5DB"/></right><top style="thin"><color rgb="FFD1D5DB"/></top><bottom style="thin"><color rgb="FFD1D5DB"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="14">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="left" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="3" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="3" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="165" fontId="3" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
    <xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
    <xf numFmtId="166" fontId="3" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="right"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="2" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="4" fillId="5" borderId="2" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;
  }

  function workbookBytes(sheets, fflateRuntime = global.fflate) {
    if (!fflateRuntime || typeof fflateRuntime.zipSync !== "function") {
      throw new Error("Spreadsheet compression support is unavailable.");
    }
    const utf8 = (value) => fflateRuntime.strToU8(value);
    const files = {
      "[Content_Types].xml": utf8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>${sheets.map((_, index) => `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join("")}</Types>`),
      "_rels/.rels": utf8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`),
      "xl/workbook.xml": utf8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><calcPr calcId="191029" fullCalcOnLoad="1" forceFullCalc="1" calcMode="auto"/><sheets>${sheets.map((sheet, index) => `<sheet name="${xmlEscape(sheet.name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`).join("")}</sheets></workbook>`),
      "xl/_rels/workbook.xml.rels": utf8(`<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${sheets.map((_, index) => `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`).join("")}<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`),
      "xl/styles.xml": utf8(stylesXml()),
    };
    sheets.forEach((sheet, index) => {
      files[`xl/worksheets/sheet${index + 1}.xml`] = utf8(worksheetXml(sheet));
    });
    return fflateRuntime.zipSync(files, { level: 6 });
  }

  function flattenParameters(parameters) {
    const rows = [];
    const visit = (prefix, value) => {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        Object.entries(value).forEach(([key, nested]) => visit(prefix ? `${prefix}.${key}` : key, nested));
        return;
      }
      rows.push([prefix, Array.isArray(value) ? JSON.stringify(value) : value ?? ""]);
    };
    Object.entries(parameters || {}).forEach(([key, value]) => {
      if (key === "commodity_parameters" && typeof value === "string") {
        try {
          visit(key, JSON.parse(value));
          return;
        } catch {
          // Preserve malformed legacy payloads verbatim for auditability.
        }
      }
      visit(key, value);
    });
    return rows;
  }

  function decodeHolding(item, fields) {
    if (!Array.isArray(item)) return item || {};
    return Object.fromEntries(fields.map((field, index) => [field, item[index]]));
  }

  function normalizeRecords(result, sleeves, period) {
    const selectedDates = new Set(period.rows.map((row) => row[0]));
    const available = Object.entries(result.commodity_sleeves || {}).map(([key, sleeve]) => {
      const fields = sleeve.holding_fields || [];
      const spreadsheetRows = sleeves?.[key]?.spreadsheetRows || sleeve.spreadsheet_rows || [];
      const records = spreadsheetRows
        .filter((record) => selectedDates.has(record.exit_date))
        .map((record) => ({
          ...record,
          holding_ledger: (record.holding_ledger || []).map((item) => decodeHolding(item, fields)),
        }));
      return { key, sleeve, records };
    }).filter(({ records }) => records.length);
    if (available.length !== 1) {
      throw new Error(`Detailed workbook template currently requires exactly one commodity sleeve; found ${available.length}.`);
    }
    return available[0];
  }

  function holdingSortKey(item) {
    const typeRank = { direct: 0, treasury: 1, future: 2, cash: 3 }[item.holding_type] ?? 4;
    const bookRank = item.book === "lease" ? 0 : 1;
    const sideRank = item.side === "long" ? 0 : item.side === "short" ? 1 : 2;
    return [typeRank, bookRank, sideRank, String(item.name || "")];
  }

  function compareHolding(left, right) {
    const a = holdingSortKey(left);
    const b = holdingSortKey(right);
    for (let index = 0; index < a.length; index += 1) {
      if (a[index] < b[index]) return -1;
      if (a[index] > b[index]) return 1;
    }
    return 0;
  }

  function addGroup(columns, groups, title, definitions) {
    const start = columns.length;
    definitions.forEach((definition) => columns.push(definition));
    groups.push({ title, start, end: columns.length - 1 });
  }

  function buildDailySheet(commodity, period) {
    const { sleeve, records } = commodity;
    const label = sleeve.product_label || commodity.key;
    const normalized = records.map((record) => ({
      ...record,
      holding_ledger: [...(record.holding_ledger || [])].sort(compareHolding),
    }));
    const maximumHoldings = Math.max(0, ...normalized.map((record) => record.holding_ledger.length));
    const columns = [];
    const groups = [];
    const add = (header, width = 16, style = "source") => ({ header, width, style });

    addGroup(columns, groups, "Interval and NAV", [
      add("Start date", 13, "date"), add("End date", 13, "date"), add("Elapsed days", 13, "integer"),
      add("Signal date", 13, "date"), add("Mode", 16, "default"), add("Start NAV", 15),
      add("Source total daily return", 22, "percentSource"), add("Calculated holdings return", 23, "percentFormula"),
      add("Holdings return difference", 23, "percentFormula"), add("Formula end NAV", 17, "formula"),
      add("Engine end NAV", 17), add("NAV difference", 17, "formula"),
    ]);
    addGroup(columns, groups, "Underlying and return reconstruction", [
      add("Underlying start spot", 20), add("Underlying end spot", 20), add("Underlying index start", 20, "formula"),
      add("Underlying index end", 20, "formula"), add("Underlying price change", 20, "percentFormula"),
      add("Lease book start — holdings sum", 25, "formula"), add("Lease book end — holdings sum", 25, "formula"),
      add("Keep book start — holdings sum", 25, "formula"), add("Keep book end — holdings sum", 25, "formula"),
      add("Lease book start in underlying", 27, "formula"), add("Lease book end in underlying", 27, "formula"),
      add("Keep book start in underlying", 27, "formula"), add("Keep book end in underlying", 27, "formula"),
      add("Total books start in underlying", 27, "formula"), add("Lease standalone return in underlying", 29, "percentFormula"),
      add("Lease contribution to combined book return", 32, "percentFormula"), add("Keep standalone return in underlying", 29, "percentFormula"),
      add("Keep contribution to combined book return", 32, "percentFormula"), add("Combined books return in underlying", 29, "percentFormula"),
      add("Reconstructed total daily return", 27, "percentFormula"), add("Underlying/book return difference", 28, "percentFormula"),
    ]);
    addGroup(columns, groups, "Book valuation and roll-forward", [
      add("Lease book interval P&L", 22, "formula"), add("Keep book interval P&L", 22, "formula"),
      add("Lease internal transfer check", 24, "formula"), add("Keep internal transfer check", 24, "formula"),
      add("Lease external/rebalancing transfer", 30, "formula"), add("Keep external/rebalancing transfer", 30, "formula"),
      add("Lease opening value", 20, "formula"), add("Lease accumulated P&L", 23, "formula"),
      add("Lease accumulated external transfers", 31, "formula"), add("Lease book end — roll-forward", 27, "formula"),
      add("Lease holdings vs roll-forward difference", 33, "formula"), add("Keep opening value", 20, "formula"),
      add("Keep accumulated P&L", 23, "formula"), add("Keep accumulated external transfers", 31, "formula"),
      add("Keep book end — roll-forward", 27, "formula"), add("Keep holdings vs roll-forward difference", 33, "formula"),
      add("Lease book start — engine audit", 27), add("Lease book end — engine audit", 27),
      add("Lease book engine audit difference", 31, "formula"), add("Keep book start — engine audit", 27),
      add("Keep book end — engine audit", 27), add("Keep book engine audit difference", 31, "formula"),
    ]);
    addGroup(columns, groups, "Detailed return contributions", [
      add("Direct gross price contribution", 29, "percentFormula"), add("Holding expense contribution", 27, "percentFormula"),
      add("Direct/replicating net contribution", 31, "percentFormula"), add("Direct decomposition difference", 29, "percentFormula"),
      add("Treasury contribution", 22, "percentFormula"),
      add("Futures contribution", 22, "percentFormula"), add("Cash/financing contribution", 25, "percentFormula"),
      add("Detailed contribution sum", 24, "percentFormula"), add("Detailed return difference", 24, "percentFormula"),
      add("Maximum holding P&L formula difference", 34, "formula"),
      add("Actual holding count", 20, "integer"),
    ]);

    const holdingGroups = [];
    for (let slot = 0; slot < maximumHoldings; slot += 1) {
      const start = columns.length;
      const definitions = [
        add("Name", 32, "default"), add("Type", 15, "default"), add("Book", 12, "default"), add("Side", 11, "default"),
        add("Contract type", 15, "default"), add("Start price", 17), add("End price", 17), add("Annual expense rate", 20, "percentSource"),
        add("Start quantity / units", 20), add("Units expensed", 18, "formula"), add("End quantity / units", 20, "formula"),
        add("Position (% NAV)", 19, "percentSource"), add("Value / notional", 19), add("Start value", 18),
        add("Gross P&L before expense", 24, "formula"), add("Holding expense", 20, "formula"), add("Economic P&L", 18, "formula"),
        add("Source economic P&L", 22), add("P&L formula difference", 23, "formula"), add("Internal transfer", 20), add("End value", 18),
        add("Spot price — start", 20), add("Spot price — end", 20),
        add("Premium", 16, "percentSource"), add("Matched USD rate", 20, "percentSource"), add("Lease rate", 17, "percentSource"),
        add("Maturity (days)", 18, "integer"), add("Return contribution", 20, "percentFormula"),
      ];
      definitions.forEach((definition) => columns.push(definition));
      const group = { title: `Holding ${slot + 1}`, start, end: columns.length - 1, slot };
      groups.push(group);
      holdingGroups.push(group);
    }

    const columnIndex = new Map(columns.map((column, index) => [column.header, index]));
    const reference = (header, row) => `${excelColumn(columnIndex.get(header))}${row}`;
    const slotReference = (slot, field, row) => {
      const fieldOffset = holdingGroups[slot].start + [
        "Name", "Type", "Book", "Side", "Contract type", "Start price", "End price", "Annual expense rate",
        "Start quantity / units", "Units expensed", "End quantity / units", "Position (% NAV)", "Value / notional", "Start value",
        "Gross P&L before expense", "Holding expense", "Economic P&L", "Source economic P&L", "P&L formula difference", "Internal transfer", "End value",
        "Spot price — start", "Spot price — end", "Premium", "Matched USD rate", "Lease rate", "Maturity (days)",
        "Return contribution",
      ].indexOf(field);
      return `${excelColumn(fieldOffset)}${row}`;
    };
    const groupHeaders = Array(columns.length).fill(null);
    const merges = [];
    groups.forEach((group) => {
      groupHeaders[group.start] = styled(group.title, "group");
      if (group.end > group.start) merges.push(`${excelColumn(group.start)}1:${excelColumn(group.end)}1`);
    });
    const rows = [
      { cells: groupHeaders, height: 23 },
      { cells: columns.map((column) => styled(column.header, "header")), height: 54 },
    ];

    const firstSpot = finiteNumber(normalized[0]?.slv_price, 1) || 1;
    const state = {
      lease: { opening: 0, accumulatedPnl: 0, accumulatedExternal: 0, priorEnd: 0 },
      keep: { opening: 0, accumulatedPnl: 0, accumulatedExternal: 0, priorEnd: 0 },
    };
    const numericRows = [];
    normalized.forEach((record, recordIndex) => {
      const rowNumber = recordIndex + 3;
      const ledger = record.holding_ledger || [];
      const startNav = finiteNumber(record.starting_nav, 0);
      const endNav = finiteNumber(record.ending_nav, startNav);
      const sourceReturn = finiteNumber(record.interval_return_pct, 0) / 100;
      const spotStart = finiteNumber(record.slv_price, 0);
      const spotEnd = finiteNumber(record.slv_exit_price, spotStart);
      const indexStart = firstSpot ? spotStart / firstSpot : 0;
      const indexEnd = firstSpot ? spotEnd / firstSpot : 0;
      const priceReturn = spotStart ? spotEnd / spotStart - 1 : 0;
      const book = {};
      for (const name of ["lease", "keep"]) {
        const holdings = ledger.filter((item) => item.book === name);
        const start = holdings.reduce((sum, item) => sum + finiteNumber(item.start_value, 0), 0);
        const end = holdings.reduce((sum, item) => sum + finiteNumber(item.end_value, 0), 0);
        const pnl = holdings.reduce((sum, item) => sum + finiteNumber(item.pnl_value, 0), 0);
        const internal = holdings.reduce((sum, item) => sum + finiteNumber(item.internal_transfer_value, 0), 0);
        const external = recordIndex ? start - state[name].priorEnd : finiteNumber(record[`${name}_book_external_transfer`], 0);
        const opening = recordIndex ? state[name].opening : start;
        const accumulatedPnl = (recordIndex ? state[name].accumulatedPnl : 0) + pnl;
        const accumulatedExternal = (recordIndex ? state[name].accumulatedExternal : 0) + external;
        const rollEnd = opening + accumulatedPnl + accumulatedExternal;
        const startUnderlying = indexStart ? start / indexStart : 0;
        const endUnderlying = indexEnd ? end / indexEnd : 0;
        book[name] = {
          start, end, pnl, internal, external, opening, accumulatedPnl, accumulatedExternal, rollEnd,
          rollDifference: end - rollEnd, startUnderlying, endUnderlying,
          standaloneUnderlying: startUnderlying ? endUnderlying / startUnderlying - 1 : null,
          sourceStart: finiteNumber(record[`${name}_book_start_value`], 0),
          sourceEnd: finiteNumber(record[`${name}_book_end_value`], 0),
        };
        state[name] = { opening, accumulatedPnl, accumulatedExternal, priorEnd: end };
      }
      const totalUnderlyingStart = book.lease.startUnderlying + book.keep.startUnderlying;
      book.lease.contributionUnderlying = totalUnderlyingStart
        ? (book.lease.endUnderlying - book.lease.startUnderlying) / totalUnderlyingStart : 0;
      book.keep.contributionUnderlying = totalUnderlyingStart
        ? (book.keep.endUnderlying - book.keep.startUnderlying) / totalUnderlyingStart : 0;
      const combinedUnderlying = book.lease.contributionUnderlying + book.keep.contributionUnderlying;
      const reconstructedReturn = (1 + priceReturn) * (1 + combinedUnderlying) - 1;
      const calculatedReturn = startNav
        ? ledger.reduce((sum, item) => sum + finiteNumber(item.pnl_value, 0), 0) / startNav : 0;
      const contributions = {};
      for (const type of ["direct", "treasury", "future", "cash"]) {
        contributions[type] = startNav ? ledger
          .filter((item) => item.holding_type === type)
          .reduce((sum, item) => sum + finiteNumber(item.pnl_value, 0), 0) / startNav : 0;
      }
      const directGrossContribution = startNav ? ledger
        .filter((item) => item.holding_type === "direct")
        .reduce((sum, item) => {
          const quantity = finiteNumber(item.quantity, 0);
          const startPrice = finiteNumber(item.price, 0);
          const endPrice = finiteNumber(item.exit_price, startPrice);
          return sum + finiteNumber(item.gross_pnl_value, quantity * (endPrice - startPrice));
        }, 0) / startNav : 0;
      const expenseContribution = startNav ? -ledger
        .filter((item) => item.holding_type === "direct")
        .reduce((sum, item) => {
          const quantity = finiteNumber(item.quantity, 0);
          const gross = finiteNumber(item.gross_pnl_value,
            quantity * (finiteNumber(item.exit_price, 0) - finiteNumber(item.price, 0)));
          return sum + finiteNumber(item.expense_value, gross - finiteNumber(item.pnl_value, 0));
        }, 0) / startNav : 0;
      const directDecompositionDifference = (
        directGrossContribution + expenseContribution - contributions.direct);
      const detailedSum = Object.values(contributions).reduce((sum, value) => sum + value, 0);
      const values = Array(columns.length).fill(null);
      const put = (header, value) => { values[columnIndex.get(header)] = value; };
      put("Start date", dateCell(record.date));
      put("End date", dateCell(record.exit_date));
      put("Elapsed days", formula(`B${rowNumber}-A${rowNumber}`, Math.max(0, (Date.parse(record.exit_date) - Date.parse(record.date)) / 86400000), "integer"));
      put("Signal date", dateCell(record.date));
      put("Mode", record.mode || "");
      put("Start NAV", styled(startNav, "source"));
      put("Source total daily return", styled(sourceReturn, "percentSource"));
      const holdingContributionReferences = holdingGroups.map((group) => slotReference(group.slot, "Return contribution", rowNumber));
      put("Calculated holdings return", formula(`SUM(${holdingContributionReferences.join(",")})`, calculatedReturn, "percentFormula"));
      put("Holdings return difference", formula(`${reference("Source total daily return", rowNumber)}-${reference("Calculated holdings return", rowNumber)}`, sourceReturn - calculatedReturn, "percentFormula"));
      put("Formula end NAV", formula(`${reference("Start NAV", rowNumber)}*(1+${reference("Calculated holdings return", rowNumber)})`, startNav * (1 + calculatedReturn)));
      put("Engine end NAV", styled(endNav, "source"));
      put("NAV difference", formula(`${reference("Engine end NAV", rowNumber)}-${reference("Formula end NAV", rowNumber)}`, endNav - startNav * (1 + calculatedReturn)));
      put("Underlying start spot", styled(spotStart, "source"));
      put("Underlying end spot", styled(spotEnd, "source"));
      put("Underlying index start", formula(`${reference("Underlying start spot", rowNumber)}/$${excelColumn(columnIndex.get("Underlying start spot"))}$3`, indexStart));
      put("Underlying index end", formula(`${reference("Underlying end spot", rowNumber)}/$${excelColumn(columnIndex.get("Underlying start spot"))}$3`, indexEnd));
      put("Underlying price change", formula(`IFERROR(${reference("Underlying end spot", rowNumber)}/${reference("Underlying start spot", rowNumber)}-1,0)`, priceReturn, "percentFormula"));

      const bookSlotTerms = (name, field) => holdingGroups.map((group) => (
        `IF(${slotReference(group.slot, "Book", rowNumber)}="${name}",${slotReference(group.slot, field, rowNumber)},0)`
      ));
      for (const name of ["lease", "keep"]) {
        const title = name[0].toUpperCase() + name.slice(1);
        put(`${title} book start — holdings sum`, formula(`SUM(${bookSlotTerms(name, "Start value").join(",")})`, book[name].start));
        put(`${title} book end — holdings sum`, formula(`SUM(${bookSlotTerms(name, "End value").join(",")})`, book[name].end));
        put(`${title} book interval P&L`, formula(`SUM(${bookSlotTerms(name, "Economic P&L").join(",")})`, book[name].pnl));
        put(`${title} internal transfer check`, formula(`SUM(${bookSlotTerms(name, "Internal transfer").join(",")})`, book[name].internal));
        put(`${title} external/rebalancing transfer`, formula(
          recordIndex
            ? `${reference(`${title} book start — holdings sum`, rowNumber)}-${reference(`${title} book end — holdings sum`, rowNumber - 1)}`
            : `${finiteNumber(record[`${name}_book_external_transfer`], 0)}`,
          book[name].external,
        ));
        put(`${title} opening value`, formula(
          recordIndex ? reference(`${title} opening value`, rowNumber - 1) : reference(`${title} book start — holdings sum`, rowNumber),
          book[name].opening,
        ));
        put(`${title} accumulated P&L`, formula(
          recordIndex
            ? `${reference(`${title} accumulated P&L`, rowNumber - 1)}+${reference(`${title} book interval P&L`, rowNumber)}`
            : reference(`${title} book interval P&L`, rowNumber),
          book[name].accumulatedPnl,
        ));
        put(`${title} accumulated external transfers`, formula(
          recordIndex
            ? `${reference(`${title} accumulated external transfers`, rowNumber - 1)}+${reference(`${title} external/rebalancing transfer`, rowNumber)}`
            : reference(`${title} external/rebalancing transfer`, rowNumber),
          book[name].accumulatedExternal,
        ));
        put(`${title} book end — roll-forward`, formula(
          `${reference(`${title} opening value`, rowNumber)}+${reference(`${title} accumulated P&L`, rowNumber)}+${reference(`${title} accumulated external transfers`, rowNumber)}`,
          book[name].rollEnd,
        ));
        put(`${title} holdings vs roll-forward difference`, formula(
          `${reference(`${title} book end — holdings sum`, rowNumber)}-${reference(`${title} book end — roll-forward`, rowNumber)}`,
          book[name].rollDifference,
        ));
        put(`${title} book start — engine audit`, styled(book[name].sourceStart, "source"));
        put(`${title} book end — engine audit`, styled(book[name].sourceEnd, "source"));
        put(`${title} book engine audit difference`, formula(
          `${reference(`${title} book end — holdings sum`, rowNumber)}-${reference(`${title} book end — engine audit`, rowNumber)}`,
          book[name].end - book[name].sourceEnd,
        ));
      }
      put("Lease book start in underlying", formula(`${reference("Lease book start — holdings sum", rowNumber)}/${reference("Underlying index start", rowNumber)}`, book.lease.startUnderlying));
      put("Lease book end in underlying", formula(`${reference("Lease book end — holdings sum", rowNumber)}/${reference("Underlying index end", rowNumber)}`, book.lease.endUnderlying));
      put("Keep book start in underlying", formula(`${reference("Keep book start — holdings sum", rowNumber)}/${reference("Underlying index start", rowNumber)}`, book.keep.startUnderlying));
      put("Keep book end in underlying", formula(`${reference("Keep book end — holdings sum", rowNumber)}/${reference("Underlying index end", rowNumber)}`, book.keep.endUnderlying));
      put("Total books start in underlying", formula(`${reference("Lease book start in underlying", rowNumber)}+${reference("Keep book start in underlying", rowNumber)}`, totalUnderlyingStart));
      put("Lease standalone return in underlying", formula(`IFERROR(${reference("Lease book end in underlying", rowNumber)}/${reference("Lease book start in underlying", rowNumber)}-1,0)`, book.lease.standaloneUnderlying || 0, "percentFormula"));
      put("Lease contribution to combined book return", formula(`IFERROR((${reference("Lease book end in underlying", rowNumber)}-${reference("Lease book start in underlying", rowNumber)})/${reference("Total books start in underlying", rowNumber)},0)`, book.lease.contributionUnderlying, "percentFormula"));
      put("Keep standalone return in underlying", formula(`IFERROR(${reference("Keep book end in underlying", rowNumber)}/${reference("Keep book start in underlying", rowNumber)}-1,0)`, book.keep.standaloneUnderlying || 0, "percentFormula"));
      put("Keep contribution to combined book return", formula(`IFERROR((${reference("Keep book end in underlying", rowNumber)}-${reference("Keep book start in underlying", rowNumber)})/${reference("Total books start in underlying", rowNumber)},0)`, book.keep.contributionUnderlying, "percentFormula"));
      put("Combined books return in underlying", formula(`${reference("Lease contribution to combined book return", rowNumber)}+${reference("Keep contribution to combined book return", rowNumber)}`, combinedUnderlying, "percentFormula"));
      put("Reconstructed total daily return", formula(`(1+${reference("Underlying price change", rowNumber)})*(1+${reference("Combined books return in underlying", rowNumber)})-1`, reconstructedReturn, "percentFormula"));
      put("Underlying/book return difference", formula(`${reference("Source total daily return", rowNumber)}-${reference("Reconstructed total daily return", rowNumber)}`, sourceReturn - reconstructedReturn, "percentFormula"));
      put("Direct gross price contribution", formula(`SUM(${holdingGroups.map((group) => `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",${slotReference(group.slot, "Gross P&L before expense", rowNumber)}/${reference("Start NAV", rowNumber)},0)`).join(",")})`, directGrossContribution, "percentFormula"));
      put("Holding expense contribution", formula(`-SUM(${holdingGroups.map((group) => `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",${slotReference(group.slot, "Holding expense", rowNumber)}/${reference("Start NAV", rowNumber)},0)`).join(",")})`, expenseContribution, "percentFormula"));
      put("Direct/replicating net contribution", formula(`${reference("Direct gross price contribution", rowNumber)}+${reference("Holding expense contribution", rowNumber)}`, directGrossContribution + expenseContribution, "percentFormula"));
      put("Direct decomposition difference", formula(`${reference("Direct/replicating net contribution", rowNumber)}-SUM(${holdingGroups.map((group) => `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",${slotReference(group.slot, "Return contribution", rowNumber)},0)`).join(",")})`, directDecompositionDifference, "percentFormula"));
      put("Treasury contribution", formula(`SUM(${holdingGroups.map((group) => `IF(${slotReference(group.slot, "Type", rowNumber)}="treasury",${slotReference(group.slot, "Return contribution", rowNumber)},0)`).join(",")})`, contributions.treasury, "percentFormula"));
      put("Futures contribution", formula(`SUM(${holdingGroups.map((group) => `IF(${slotReference(group.slot, "Type", rowNumber)}="future",${slotReference(group.slot, "Return contribution", rowNumber)},0)`).join(",")})`, contributions.future, "percentFormula"));
      put("Cash/financing contribution", formula(`SUM(${holdingGroups.map((group) => `IF(${slotReference(group.slot, "Type", rowNumber)}="cash",${slotReference(group.slot, "Return contribution", rowNumber)},0)`).join(",")})`, contributions.cash, "percentFormula"));
      put("Detailed contribution sum", formula(`SUM(${reference("Direct/replicating net contribution", rowNumber)},${reference("Treasury contribution", rowNumber)},${reference("Futures contribution", rowNumber)},${reference("Cash/financing contribution", rowNumber)})`, detailedSum, "percentFormula"));
      put("Detailed return difference", formula(`${reference("Source total daily return", rowNumber)}-${reference("Detailed contribution sum", rowNumber)}`, sourceReturn - detailedSum, "percentFormula"));
      const pnlFormulaDifferenceMaximum = Math.max(0, ...ledger.map((item) => {
        const gross = finiteNumber(item.gross_pnl_value,
          item.holding_type === "direct" ? finiteNumber(item.quantity, 0) * (finiteNumber(item.exit_price, 0) - finiteNumber(item.price, 0)) : finiteNumber(item.pnl_value, 0));
        const expense = finiteNumber(item.expense_value,
          item.holding_type === "direct" ? gross - finiteNumber(item.pnl_value, 0) : 0);
        return Math.abs(finiteNumber(item.pnl_value, 0) - gross + expense);
      }));
      put("Maximum holding P&L formula difference", formula(`MAX(${holdingGroups.map((group) => `ABS(${slotReference(group.slot, "P&L formula difference", rowNumber)})`).join(",")})`, pnlFormulaDifferenceMaximum));
      put("Actual holding count", formula(`COUNTA(${holdingGroups.map((group) => slotReference(group.slot, "Name", rowNumber)).join(",")})`, ledger.length, "integer"));

      holdingGroups.forEach((group) => {
        const item = ledger[group.slot] || {};
        const position = finiteNumber(item.position_pct, null);
        const startQuantity = finiteNumber(item.quantity, null);
        const startPrice = finiteNumber(item.price, null);
        const endPrice = finiteNumber(item.exit_price, null);
        const sourcePnl = finiteNumber(item.pnl_value, null);
        const grossPnl = finiteNumber(item.gross_pnl_value,
          item.holding_type === "direct" && startQuantity !== null && startPrice !== null && endPrice !== null
            ? startQuantity * (endPrice - startPrice) : finiteNumber(item.pnl_value, 0));
        const expenseValue = finiteNumber(item.expense_value,
          item.holding_type === "direct" ? grossPnl - finiteNumber(item.pnl_value, 0) : 0);
        const elapsedDays = Math.max(0, (Date.parse(record.exit_date) - Date.parse(record.date)) / 86400000);
        const expenseRate = finiteNumber(item.expense_rate,
          item.holding_type === "direct" && finiteNumber(item.start_value, 0) && elapsedDays
            ? expenseValue / finiteNumber(item.start_value, 0) * 365 / elapsedDays
            : null);
        const unitsExpensed = finiteNumber(item.units_expensed,
          item.holding_type === "direct" && endPrice ? expenseValue / endPrice : 0);
        const endQuantity = finiteNumber(item.end_quantity,
          item.holding_type === "direct" && startQuantity !== null ? startQuantity - unitsExpensed : startQuantity);
        const valuesByField = {
          "Name": item.name || "", "Type": item.holding_type || "", "Book": item.book || "", "Side": item.side || "",
          "Contract type": item.contract_type || "", "Start price": startPrice,
          "End price": endPrice, "Annual expense rate": expenseRate,
          "Start quantity / units": startQuantity, "Units expensed": unitsExpensed, "End quantity / units": endQuantity,
          "Position (% NAV)": position === null ? null : position / 100,
          "Value / notional": finiteNumber(item.notional_value, finiteNumber(item.start_value, null)),
          "Start value": finiteNumber(item.start_value, null), "Gross P&L before expense": grossPnl,
          "Holding expense": expenseValue, "Economic P&L": sourcePnl, "Source economic P&L": sourcePnl,
          "P&L formula difference": 0, "Internal transfer": finiteNumber(item.internal_transfer_value, null),
          "End value": finiteNumber(item.end_value, null),
          "Spot price — start": finiteNumber(item.spot_price, null), "Spot price — end": finiteNumber(item.exit_spot_price, null),
          "Premium": finiteNumber(item.premium_pct, null) === null ? null : finiteNumber(item.premium_pct, 0) / 100,
          "Matched USD rate": finiteNumber(item.matched_usd_rate_pct, null) === null ? null : finiteNumber(item.matched_usd_rate_pct, 0) / 100,
          "Lease rate": finiteNumber(item.lease_pct, null) === null ? null : finiteNumber(item.lease_pct, 0) / 100,
          "Maturity (days)": finiteNumber(item.maturity_days, null),
        };
        const fieldOrder = [
          "Name", "Type", "Book", "Side", "Contract type", "Start price", "End price", "Annual expense rate",
          "Start quantity / units", "Units expensed", "End quantity / units", "Position (% NAV)", "Value / notional", "Start value",
          "Gross P&L before expense", "Holding expense", "Economic P&L", "Source economic P&L", "P&L formula difference", "Internal transfer", "End value",
          "Spot price — start", "Spot price — end", "Premium", "Matched USD rate", "Lease rate", "Maturity (days)",
        ];
        fieldOrder.forEach((field, offset) => {
          const style = columns[group.start + offset].style;
          values[group.start + offset] = styled(valuesByField[field], style);
        });
        if (item.name) {
          values[group.start + fieldOrder.indexOf("Units expensed")] = formula(
            `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",IFERROR(${slotReference(group.slot, "Holding expense", rowNumber)}/${slotReference(group.slot, "End price", rowNumber)},0),0)`, unitsExpensed,
          );
          values[group.start + fieldOrder.indexOf("End quantity / units")] = formula(
            `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",${slotReference(group.slot, "Start quantity / units", rowNumber)}-${slotReference(group.slot, "Units expensed", rowNumber)},IF(${slotReference(group.slot, "Type", rowNumber)}="cash",${slotReference(group.slot, "End value", rowNumber)},${slotReference(group.slot, "Start quantity / units", rowNumber)}))`, endQuantity,
          );
          values[group.start + fieldOrder.indexOf("Gross P&L before expense")] = formula(
            `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",${slotReference(group.slot, "Start quantity / units", rowNumber)}*(${slotReference(group.slot, "End price", rowNumber)}-${slotReference(group.slot, "Start price", rowNumber)}),${slotReference(group.slot, "Source economic P&L", rowNumber)})`, grossPnl,
          );
          values[group.start + fieldOrder.indexOf("Holding expense")] = formula(
            `IF(${slotReference(group.slot, "Type", rowNumber)}="direct",${slotReference(group.slot, "Start value", rowNumber)}*${slotReference(group.slot, "Annual expense rate", rowNumber)}*${reference("Elapsed days", rowNumber)}/365,0)`, expenseValue,
          );
          values[group.start + fieldOrder.indexOf("Economic P&L")] = formula(
            `${slotReference(group.slot, "Gross P&L before expense", rowNumber)}-${slotReference(group.slot, "Holding expense", rowNumber)}`, finiteNumber(item.pnl_value, 0),
          );
          values[group.start + fieldOrder.indexOf("P&L formula difference")] = formula(
            `${slotReference(group.slot, "Source economic P&L", rowNumber)}-${slotReference(group.slot, "Economic P&L", rowNumber)}`, finiteNumber(item.pnl_value, 0) - grossPnl + expenseValue,
          );
        }
        values[group.end] = item.name
          ? formula(`IFERROR(${slotReference(group.slot, "Economic P&L", rowNumber)}/${reference("Start NAV", rowNumber)},0)`, startNav ? finiteNumber(item.pnl_value, 0) / startNav : 0, "percentFormula")
          : null;
      });
      rows.push({ cells: values });
      numericRows.push({
        sourceReturn, calculatedReturn, navDifference: endNav - startNav * (1 + calculatedReturn),
        underlyingDifference: sourceReturn - reconstructedReturn, detailDifference: sourceReturn - detailedSum,
        directDecompositionDifference, pnlFormulaDifferenceMaximum,
        leaseRollDifference: book.lease.rollDifference, keepRollDifference: book.keep.rollDifference,
        leaseEngineDifference: book.lease.end - book.lease.sourceEnd, keepEngineDifference: book.keep.end - book.keep.sourceEnd,
        holdingCount: ledger.length,
      });
    });

    return {
      sheet: {
        name: "Daily Holdings",
        rows,
        widths: columns.map((column) => column.width),
        merges,
        freeze: { xSplit: 5, ySplit: 2, topLeftCell: "F3" },
        autoFilter: `A2:${excelColumn(columns.length - 1)}${rows.length}`,
      },
      label,
      maximumHoldings,
      columns,
      numericRows,
      firstDataRow: 3,
      lastDataRow: rows.length,
      period,
    };
  }

  function buildOverview(result, daily) {
    const finalNav = daily.numericRows.length
      ? finiteNumber(daily.period.rows.at(-1)?.[result.portfolio_fields?.indexOf("nav")], null)
      : null;
    const rows = [
      { cells: [styled(`${daily.label} — detailed completed-backtest workbook`, "title"), null, null, null, null, null], height: 28 },
      [],
      [styled("Purpose", "label"), styled("Reconstruct the selected strategy path from the completed backtest holding ledger, with visible holding P&L, book valuation, underlying-return decomposition, NAV reconciliation, and model checks.", "note")],
      [styled("Holding interval", "label"), styled("Each row applies the start-date close holdings through the end-date close. Exchange holidays naturally create multi-calendar-day intervals.", "note")],
      [styled("Template version", "label"), TEMPLATE_VERSION],
      [styled("Commodity scope", "label"), `${daily.label}; this template version requires exactly one commodity sleeve.`],
      [styled("Mode", "label"), styled("positive = long futures only; neutral = no futures; negative = short futures only; long_and_short = both.", "note")],
      [styled("Futures value", "label"), styled("Regular and inverse exchange-traded futures are both carried at zero after daily settlement. Their signed notional records contractual price exposure; economic P&L settles into the attributed cash/margin holding.", "note")],
      [styled("Holding expense", "label"), styled("The direct or replicating holding expense is shown explicitly as annual rate × elapsed days / 365 × start value. An equal value of units is removed at the interval-end price, so the expense changes units rather than creating an internal cash transfer.", "note")],
      [styled("Book valuation", "label"), styled("Lease and keep values are independently reconstructed from attributed holdings and from opening value + accumulated P&L + external/rebalancing transfers.", "note")],
      [styled("Returns", "label"), styled("Standalone book return uses that book's start value. Contribution uses total lease + keep start value. Total return is reconstructed as underlying price change compounded with the combined book return quoted in the underlying.", "note")],
      [styled("Prices", "label"), styled("A future's spot fields contain the actual commodity spot quote. Futures notional and quantity do not rescale that spot price. The normalized underlying index is shown separately.", "note")],
      [],
      [styled("Selected result summary", "group")],
      [styled("First holding date", "label"), dateCell(daily.period.rows[0]?.[1] || daily.period.start)],
      [styled("Final interval end", "label"), dateCell(daily.period.end)],
      [styled("Holding intervals", "label"), daily.numericRows.length],
      [styled("Maximum simultaneous ledger holdings", "label"), daily.maximumHoldings],
      [styled("Ending NAV", "label"), styled(finalNav, "source")],
      [styled("Portfolio rebalancing", "label"), result.portfolio?.rebalancing || ""],
    ];
    return {
      name: "Overview",
      rows,
      widths: [42, 105, 2, 18, 18, 18],
      merges: ["A1:F1", "B3:F3", "B4:F4", "B7:F7", "B8:F8", "B9:F9", "B10:F10", "B11:F11", "B12:F12", "A14:F14"],
    };
  }

  function buildParameters(result, label) {
    const flattened = flattenParameters(result.parameters || {});
    const rows = [
      { cells: [styled(`${label} — completed-backtest parameters`, "title"), null, null, null], height: 28 },
      [],
      [styled("Parameter path", "header"), styled("Saved value", "header"), styled("Use", "header"), styled("Notes", "header")],
      ...flattened.map(([path, value]) => [path, styled(value, "source"), "Exact completed-run input", "Nested commodity parameters are expanded for auditability."]),
    ];
    return {
      name: "Parameters",
      rows,
      widths: [62, 32, 25, 58],
      merges: ["A1:D1"],
      freeze: { xSplit: 0, ySplit: 3, topLeftCell: "A4" },
      autoFilter: `A3:D${rows.length}`,
    };
  }

  function buildChecks(daily) {
    const start = daily.firstDataRow;
    const end = daily.lastDataRow;
    const index = new Map(daily.columns.map((column, columnIndex) => [column.header, columnIndex]));
    const range = (header) => `'Daily Holdings'!$${excelColumn(index.get(header))}$${start}:$${excelColumn(index.get(header))}$${end}`;
    const maximumAbsolute = (header) => `MAX(MAX(${range(header)}),-MIN(${range(header)}))`;
    const expectedRows = daily.numericRows.length;
    const checks = [
      ["Holding intervals", `COUNTA(${range("End date")})`, expectedRows, 0, "One row per selected completed holding interval."],
      ["Maximum simultaneous ledger holdings", `MAX(${range("Actual holding count")})`, daily.maximumHoldings, 0, "The exporter reserves exactly the maximum number of ledger slots required by the selected period."],
      ["Maximum holdings-return difference", maximumAbsolute("Holdings return difference"), 0, 1e-10, "Source total return less summed holding-level economic P&L contributions."],
      ["Maximum NAV difference", maximumAbsolute("NAV difference"), 0, 1e-10, "Engine ending NAV less formula-derived ending NAV."],
      ["Maximum underlying/book return difference", maximumAbsolute("Underlying/book return difference"), 0, 1e-10, "Source return less underlying price × combined underlying-book return reconstruction."],
      ["Maximum detailed-contribution difference", maximumAbsolute("Detailed return difference"), 0, 1e-10, "Source return less direct + Treasury + futures + cash contributions."],
      ["Maximum direct expense-decomposition difference", maximumAbsolute("Direct decomposition difference"), 0, 1e-10, "Net direct/replicating contribution less gross price contribution plus the explicit expense contribution."],
      ["Maximum holding P&L formula difference", maximumAbsolute("Maximum holding P&L formula difference"), 0, 1e-10, "Source holding economic P&L less gross P&L before expense minus the explicit holding expense."],
      ["Maximum lease holdings/roll-forward difference", maximumAbsolute("Lease holdings vs roll-forward difference"), 0, 1e-10, "Lease holdings sum versus opening + accumulated P&L + external transfers."],
      ["Maximum keep holdings/roll-forward difference", maximumAbsolute("Keep holdings vs roll-forward difference"), 0, 1e-10, "Keep holdings sum versus opening + accumulated P&L + external transfers."],
      ["Maximum lease engine-audit difference", maximumAbsolute("Lease book engine audit difference"), 0, 1e-10, "Lease holdings sum versus completed backtest book value."],
      ["Maximum keep engine-audit difference", maximumAbsolute("Keep book engine audit difference"), 0, 1e-10, "Keep holdings sum versus completed backtest book value."],
    ];
    const actualValues = [
      expectedRows,
      Math.max(0, ...daily.numericRows.map((row) => row.holdingCount)),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.sourceReturn - row.calculatedReturn))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.navDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.underlyingDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.detailDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.directDecompositionDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.pnlFormulaDifferenceMaximum))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.leaseRollDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.keepRollDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.leaseEngineDifference))),
      Math.max(0, ...daily.numericRows.map((row) => Math.abs(row.keepEngineDifference))),
    ];
    const rows = [
      { cells: [styled("Model checks", "title"), null, null, null, null, null, null], height: 28 },
      [],
      ["Check", "Actual", "Expected", "Difference", "Tolerance", "Status", "Notes"].map((value) => styled(value, "checkHeader")),
    ];
    checks.forEach(([name, actualFormula, expected, tolerance, notes], checkIndex) => {
      const rowNumber = rows.length + 1;
      const actual = actualValues[checkIndex];
      const difference = actual - expected;
      const status = Math.abs(difference) <= tolerance ? "OK" : "REVIEW";
      rows.push([
        name,
        formula(actualFormula, actual),
        styled(expected, "source"),
        formula(`B${rowNumber}-C${rowNumber}`, difference),
        styled(tolerance, "source"),
        formula(`IF(ABS(D${rowNumber})<=E${rowNumber},"OK","REVIEW")`, status, status === "OK" ? "checkOk" : "default"),
        styled(notes, "note"),
      ]);
    });
    const overallRow = rows.length + 2;
    rows.push([], [
      styled("Overall model status", "label"),
      formula(`IF(COUNTIF(F4:F${rows.length},"REVIEW")=0,"OK","REVIEW")`, actualValues.every((actual, index_) => Math.abs(actual - checks[index_][2]) <= checks[index_][3]) ? "OK" : "REVIEW", "checkOk"),
      null, null, null, null, styled(`Template v${TEMPLATE_VERSION}; full 1969 comparison is available as an opt-in regression test.`, "note"),
    ]);
    return {
      name: "Checks",
      rows,
      widths: [46, 22, 18, 20, 18, 15, 72],
      merges: ["A1:G1"],
      freeze: { xSplit: 0, ySplit: 3, topLeftCell: "A4" },
      autoFilter: `A3:G${overallRow - 2}`,
    };
  }

  function buildSheets({ result, sleeves, period }) {
    if (!result || !period?.rows?.length) {
      throw new Error("A completed backtest result and non-empty date interval are required.");
    }
    const commodity = normalizeRecords(result, sleeves, period);
    const daily = buildDailySheet(commodity, period);
    return [
      buildOverview(result, daily),
      buildParameters(result, daily.label),
      daily.sheet,
      buildChecks(daily),
    ];
  }

  global.KeepLeaseWorkbook = Object.freeze({
    templateVersion: TEMPLATE_VERSION,
    buildSheets,
    workbookBytes,
    excelColumn,
  });
})(globalThis);
