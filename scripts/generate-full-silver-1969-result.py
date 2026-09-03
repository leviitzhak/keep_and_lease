"""Generate the canonical single-silver result used by the opt-in workbook test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.engine import StrategyEngine


ROOT = Path(__file__).resolve().parents[1]


def effective_parameters() -> dict[str, object]:
    saved = json.loads(
        (ROOT / "strategies" / "full silver long gradual").read_text(
            encoding="utf-8"
        )
    )["parameters"]
    parameters = dict(saved)
    parameters["weight_silver"] = "100"
    parameters["weight_gold"] = "0"
    parameters["weight_sp500"] = "0"
    parameters["weight_btc"] = "0"
    parameters["weight_treasury"] = "0"
    parameters["futures_contract_type"] = "regular"
    commodity_parameters = json.loads(str(parameters["commodity_parameters"]))
    commodity_parameters["silver"]["futures_contract_type"] = "regular"
    parameters["commodity_parameters"] = json.dumps(
        commodity_parameters, separators=(",", ":")
    )
    return parameters


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = StrategyEngine(ROOT).run_backtest(
        effective_parameters(),
        lambda stage, detail: print(f"{stage}: {detail}", flush=True),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"result: {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
