"""Compatibility entry point for the v0.1 AI-assisted supervised workflow.

The shared workflow evaluates both permitted model families on one duplicate-safe
split before writing the TF-IDF artifact and selecting a prototype.
"""
from __future__ import annotations

import json

from supervised_v0_1 import train_all


def train() -> dict:
    return train_all()


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
