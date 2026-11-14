"""Forecast-only attendance continuity rules. No actual-fee or policy writes.

Presence is roster membership, including zero hours. COMPLETE requires an
explicit, fingerprint-bound confirmation AND a successful full-roster import.
All stop dates are exclusive. An inclusive fee expiry is converted by +1 day.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping

VERSION = "2.2"
SOURCE_STATES = frozenset({"COMPLETE", "PARTIAL", "MISSING", "ERROR", "PENDING_CONFIRMATION"})


def next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


@dataclass(frozen=True)
class Source:
    state: str
    fingerprint: str = ""
    confirmed_fingerprint: str = ""
    confirmed_by: str = ""
    confirmed_at: str = ""
    imported: bool = False
    evidence: str = ""

    def effective_state(self) -> str:
        if self.state not in SOURCE_STATES:
            return "ERROR"
        if self.state != "COMPLETE":
            return self.state
        if not self.imported:
            return "ERROR"
        if not (self.fingerprint and self.fingerprint == self.confirmed_fingerprint
                and self.confirmed_by and self.confirmed_at):
            return "PENDING_CONFIRMATION"
        return "COMPLETE"


@dataclass(frozen=True)
class Decision:
    last_attendance_month: date | None
    next_source_status: str
    present_in_next_month: bool | None
    inferred_stop: date | None
    effective_stop: date | None
    status: str
    evidence: tuple[str, ...]


def evaluate(presence: Mapping[date, bool | None], sources: Mapping[date, Source],
             *, identity_ok: bool, official_stop: date | None = None,
             fee_expiry: date | None = None, from_month: date = date(2026, 9, 1)) -> Decision:
    """Evaluate every adjacent month, never merely the last positive month.

    Unknown identity blocks inference. A later return retains the conservative
    stop and requests episode review; it never silently restarts an episode.
    """
    present = sorted(m for m, value in presence.items() if value is True)
    last = max(present, default=None)
    missing = Source("MISSING")
    nxt = next_month(last) if last else None
    state = sources.get(nxt, missing).effective_state() if nxt else "MISSING"
    present_next = presence.get(nxt) if nxt else None
    gaps = [next_month(m) for m in present
            if identity_ok and next_month(m) >= from_month
            and presence.get(next_month(m)) is False
            and sources.get(next_month(m), missing).effective_state() == "COMPLETE"]
    inferred = min(gaps, default=None)
    rejoin = inferred is not None and any(m > inferred for m in present)
    limits = [x for x in (official_stop, inferred,
                          fee_expiry + timedelta(days=1) if fee_expiry else None) if x]
    effective = min(limits, default=None)
    status = ("IDENTITY_REVIEW" if not identity_ok else "REJOIN_REVIEW" if rejoin
              else "INFERRED_STOP" if inferred else "OFFICIAL_STOP" if official_stop
              else "PRESENT" if last else "NO_ATTENDANCE_EVIDENCE")
    evidence = tuple(sources[m].evidence for m in gaps if sources[m].evidence)
    return Decision(last, state, present_next, inferred, effective, status, evidence)


def cap_calendar_formula(formula: str, row: int) -> str:
    """Reuse approved native engine; cap only dates >= September 2026.

    Keep all existing rate/calendar/fee-window/data-quality bindings. No changes
    to official termination cells or actual revenue. Fail closed on drift.
    """
    if 'FORECAST_V22!$K' in formula:
        return formula
    marker = 'stop,MIN(TONG_QUAN!$E$6,'
    if formula.count(marker) != 1:
        raise ValueError("Forecast formula layout changed; audit before deploy")
    # K contains only inferred exclusive stops, never an official source date.
    limit = (f'IF(ISNUMBER(FORECAST_V22!$K{row}),'
             f'MAX(DATE(2026,9,1),FORECAST_V22!$K{row})-1,TONG_QUAN!$E$6),')
    return formula.replace(marker, marker + limit)
