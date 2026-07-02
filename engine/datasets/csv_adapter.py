import csv
from collections.abc import Iterator
from pathlib import Path


class CSVAdapter:
    def __init__(self, file: str | Path, entity_key: str):
        self.file = Path(file)
        self.entity_key = entity_key

    def rows(self) -> Iterator[tuple[str, dict]]:
        with self.file.open(newline="") as f:
            for row in csv.DictReader(f):
                key = row[self.entity_key].strip()
                if key:
                    yield key, {k: v.strip() for k, v in row.items()}
