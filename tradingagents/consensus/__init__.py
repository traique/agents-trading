"""Module đồng thuận / position sizing / vòng tự học (lấy cảm hứng từ augur)."""
from .kelly import consensus_from_outputs, kelly_fraction, position_sizing, render_consensus_markdown
from .learning import (
    learning_summary,
    load_rolling_ic,
    rating_accuracy,
    write_rolling_ic,
)

__all__ = [
    "consensus_from_outputs",
    "kelly_fraction",
    "position_sizing",
    "render_consensus_markdown",
    "learning_summary",
    "load_rolling_ic",
    "rating_accuracy",
    "write_rolling_ic",
]
