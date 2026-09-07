import importlib.util
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).parents[1] / "public"))
SPEC = importlib.util.spec_from_file_location(
    "silver_strategy_gui",
    Path(__file__).parents[1] / "public" / "silver_strategy_gui.py",
)
GUI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GUI)


def test_max_drawdown_is_reported_as_positive_peak_to_trough_loss():
    assert GUI.max_drawdown([1.0, 1.2, 0.9, 1.1]) == 25.0


def test_max_drawdown_is_zero_for_monotonic_nav():
    assert GUI.max_drawdown([1.0, 1.1, 1.2]) == 0.0
