"""Dataset adapters: anything that yields (entity_key, facts_dict) rows.

Tier-1 = bring-your-own-data (a SQL adapter against an owned DB, v2),
Tier-2 = public/curated data via CSVAdapter, Tier-3 = generated data (v2).
"""

from collections.abc import Iterator
from typing import Protocol


class DatasetAdapter(Protocol):
    def rows(self) -> Iterator[tuple[str, dict]]: ...


def get_adapter(kind: str, config: dict):
    if kind == "csv":
        from engine.datasets.csv_adapter import CSVAdapter

        return CSVAdapter(config["file"], config["entity_key"])
    raise ValueError(f"unknown dataset adapter: {kind}")
