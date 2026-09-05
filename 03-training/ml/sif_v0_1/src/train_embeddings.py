"""Compatibility entry point for frozen-embedding v0.1 training.

The shared workflow keeps embedding and TF-IDF validation IDs identical, caches
the frozen pretrained embeddings, and writes both requested artifacts.
"""
from __future__ import annotations

import json

from supervised_v0_1 import train_all


def train() -> dict:
    return train_all()


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
