#!/usr/bin/env python3
"""One-shot migration for commodity-leg allocation semantics.

The commodity proportion is the full long commodity leg.  The replicating fund
and the futures+Treasuries replication are complementary implementations of
that leg.  Short notional is expressed as a fraction of the full commodity leg.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {".py", ".html", ".md", ".json", ".mjs", ".js", ".ts", ".tsx", ".yml", ".yaml"}
SKIP = {Path(__file__).resolve()}


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"expected snippet not found: {label}")
    return text.replace(old, new)


# Rename the parameters repo-wide so saved payloads, APIs, tests and docs all
# use names matching their new semantics.
for path in ROOT.rglob("*"):
    if not path.is_file() or path.resolve() in SKIP or ".git" in path.parts:
        continue
    if path.suffix.lower() not in TEXT_SUFFIXES:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    updated = text.replace("max_long_future", "max_futures_treasury_fraction")
    updated = updated.replace("max_short_fraction_of_slv", "max_short_fraction_of_long_leg")
    if updated != text:
        path.write_text(updated, encoding="utf-8")

strategy = ROOT / "backtest_silver_lease_strategy.py"
text = strategy.read_text(encoding="utf-8")

old_allocation = '''    slv_weight = clamp(
        (p.slv_start_rate - long_signal) /
        (p.slv_start_rate - p.slv_full_rate))
    if p.slv_entry_mode == "fixed":
        slv_weight = 1.0
    if not p.enable_slv_leg:
        slv_weight = 0.0
    treasury_weight = ((1.0 - slv_weight)
                       if p.enable_cash_long_futures_leg else 0.0)

    # Treasury and SLV form the fully invested base, while long futures are an
    # overlay sized independently by their positive lease signal.
    base_longs = {}
    long_notional = (p.max_futures_treasury_fraction * positive_strength
                     if p.enable_cash_long_futures_leg else 0.0)
'''
new_allocation = '''    # The configured commodity sleeve is the complete long commodity leg.
    # A share of that leg is implemented by Treasury collateral + long futures;
    # the complementary share is held in the replicating fund.  Therefore,
    # whenever both implementations are enabled, fund + futures replication = 1.
    futures_treasury_share = (
        p.max_futures_treasury_fraction * positive_strength
        if p.enable_cash_long_futures_leg else 0.0)
    futures_treasury_share = clamp(futures_treasury_share)
    if p.enable_slv_leg:
        slv_weight = 1.0 - futures_treasury_share
    else:
        slv_weight = 0.0
    treasury_weight = futures_treasury_share

    # Long-futures notional equals the Treasury-funded replication share; it is
    # no longer an independent overlay on top of a fully invested base.
    base_longs = {}
    long_notional = futures_treasury_share
'''
text = replace_required(text, old_allocation, new_allocation, "allocation block")

old_extension = '''    # A short-futures position is paired with an equally sized extension of
    # the complete base long book.  The extension retains the same relative
    # mix of long futures, SLV, and Treasuries.
    base_long_total = treasury_weight + slv_weight + sum(base_longs.values())
    long_extension = total_short
    extension_ratio = long_extension / base_long_total if base_long_total else 0.0
    treasury = treasury_weight * (1.0 + extension_ratio)
    slv = slv_weight * (1.0 + extension_ratio)
    longs = {symbol: weight * (1.0 + extension_ratio)
             for symbol, weight in base_longs.items()}
'''
new_extension = '''    # A short-futures position is paired with an equally sized extension of
    # the complete long commodity leg.  Treasury collateral is not counted as
    # a second long leg: fund exposure + long-futures exposure is the commodity
    # leg against which the short fraction is defined.
    base_long_total = slv_weight + sum(base_longs.values())
    long_extension = total_short
    extension_ratio = long_extension / base_long_total if base_long_total else 0.0
    treasury = treasury_weight * (1.0 + extension_ratio)
    slv = slv_weight * (1.0 + extension_ratio)
    longs = {symbol: weight * (1.0 + extension_ratio)
             for symbol, weight in base_longs.items()}
'''
text = replace_required(text, old_extension, new_extension, "short extension block")

# The pre-extension zero check should likewise count commodity exposure, not
# Treasury collateral as an additional long commodity position.
text = text.replace(
    "    if treasury_weight + slv_weight + sum(base_longs.values()) <= 0:\n",
    "    if slv_weight + sum(base_longs.values()) <= 0:\n",
)

# Clarify CLI descriptions while keeping their behavior compatible.
text = text.replace(
    'parser.add_argument("--max-long-future", type=float, default=0.50)',
    'parser.add_argument("--max-futures-treasury-fraction", type=float, default=0.50,\n'
    '                        help="Maximum fraction of the full commodity leg implemented with Treasury collateral + long futures")',
)
text = text.replace(
    'parser.add_argument("--max-short-fraction-of-slv", type=float, default=0.50)',
    'parser.add_argument("--max-short-fraction-of-long-leg", type=float, default=0.50,\n'
    '                        help="Maximum short-futures notional as a fraction of the full long commodity leg")',
)
strategy.write_text(text, encoding="utf-8")

html = ROOT / "public" / "silver_strategy_gui.html"
text = html.read_text(encoding="utf-8")

# The replicating-fund allocation is now derived as the complement of the
# futures+Treasuries share, so its independent transition controls are removed.
for obsolete in (
    '<label>Fund allocation<select name="slv_entry_mode"><option value="gradual">Gradual</option><option value="fixed">Fixed at 100% (no entry condition)</option></select></label>\n',
    '<label>Fund transition start (%)<input name="slv_start_rate" type="number" value="0.5" step="0.1"></label>\n',
    '<label>Fund fully allocated (%)<input name="slv_full_rate" type="number" value="-1.5" step="0.1"></label>\n',
):
    text = text.replace(obsolete, "")

text = text.replace(
    '<label>Maximum notional (%)<input name="max_futures_treasury_fraction" type="number" value="50" step="1"></label>',
    '<label>Maximum futures + Treasuries (% of commodity leg)<input name="max_futures_treasury_fraction" type="number" value="50" min="0" max="100" step="1"></label>',
)
text = text.replace(
    '<label>Maximum short notional (% of capital)<input name="max_short_fraction_of_long_leg" type="number" value="50" step="1"></label>',
    '<label>Maximum short notional (% of commodity leg)<input name="max_short_fraction_of_long_leg" type="number" value="50" min="0" step="1"></label>',
)
text = text.replace(
    "max_futures_treasury_fraction:'Maximum long-futures notional as a percentage of sleeve capital.'",
    "max_futures_treasury_fraction:'Maximum share of the full commodity leg implemented with Treasury collateral plus long futures. The remaining share is always held in the replicating fund when that leg is enabled.'",
)
text = text.replace(
    "max_short_fraction_of_long_leg:'Maximum short-futures notional as a percentage of sleeve capital.'",
    "max_short_fraction_of_long_leg:'Maximum short-futures notional as a percentage of the full long commodity leg, including both the replicating-fund and futures+Treasuries implementations.'",
)
text = text.replace(
    "slv_start_rate:'Lease rate where allocation starts moving from the fund toward cash and long futures.',slv_full_rate:'Lease rate where that transition reaches full allocation.',",
    "",
)
html.write_text(text, encoding="utf-8")

readme = ROOT / "README.md"
if readme.exists():
    text = readme.read_text(encoding="utf-8")
    marker = "## Commodity-leg allocation semantics"
    if marker not in text:
        text += '''\n\n## Commodity-leg allocation semantics\n\nEach configured commodity proportion is the **full long commodity leg**. Within that leg, the replicating fund and the Treasury-collateralized long-futures replication are complementary: if `a(r)` is the futures+Treasuries share, the replicating-fund share is `1 - a(r)`. The parameter `max_futures_treasury_fraction` caps `a(r)`, so `1 - max_futures_treasury_fraction` is the minimum replicating-fund share when both implementations are enabled.\n\nThe short parameter `max_short_fraction_of_long_leg` is measured against the full long commodity leg, not against only the fund or only the futures portion. A short position is paired with an equal-sized extension of the complete long commodity implementation.\n'''
        readme.write_text(text, encoding="utf-8")

print("commodity-leg allocation migration applied")
