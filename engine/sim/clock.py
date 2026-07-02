"""Injected clock so every time-dependent code path is testable without sleeping.

Real code passes RealClock(); simulations pass SimClock and advance it manually.
All SQL that reasons about time takes an explicit `now` parameter — never now() in SQL.
"""

from datetime import UTC, datetime, timedelta


class SimClock:
    def __init__(self, start: datetime | None = None, step: timedelta = timedelta(hours=1)):
        self.now_dt = start or datetime(2026, 1, 1, tzinfo=UTC)
        self.step_size = step

    def now(self) -> datetime:
        return self.now_dt

    def tick(self, steps: int = 1) -> datetime:
        self.now_dt += self.step_size * steps
        return self.now_dt


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
