"""Append-only, tamper-evident JSON-Lines storage.

Every line carries ``_hash`` (SHA-256 of its own canonical content plus the
previous line's hash) and ``_prev``. Lines are only ever appended; any edit or
deletion of an earlier line breaks the chain and :meth:`AppendOnlyLog.verify`
reports the first broken line. Writers refuse to append to a broken file.

The state directory is a git checkout of the ``nepse-v2-state`` branch in CI, so
every append is also preserved in git history.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

GENESIS = "0" * 64


class IntegrityError(RuntimeError):
    """An append-only file was modified (hash chain broken)."""


def canonical(obj: object) -> str:
    """Deterministic JSON (sorted keys, no spaces) used for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(obj: object) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


@dataclass
class AppendOnlyLog:
    """One JSONL file with a hash chain."""

    path: Path

    @property
    def compressed(self) -> bool:
        return self.path.suffix == ".gz"

    def _lines(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        raw = gzip.open(self.path, "rt", encoding="utf-8") if self.compressed else self.path.open(encoding="utf-8")
        with raw as fh:
            for n, line in enumerate(fh, 1):
                if line.strip():
                    try:
                        out.append(json.loads(line))
                    except ValueError as exc:
                        raise IntegrityError(f"{self.path}: line {n} is not valid JSON") from exc
        return out

    def verify(self) -> list[dict]:
        """Return all records; raise IntegrityError if the chain is broken."""
        prev = GENESIS
        records = self._lines()
        for n, rec in enumerate(records, 1):
            body = {k: v for k, v in rec.items() if k not in ("_hash", "_prev")}
            if rec.get("_prev") != prev or rec.get("_hash") != content_hash([prev, body]):
                raise IntegrityError(f"{self.path}: hash chain broken at line {n}")
            prev = rec["_hash"]
        return records

    def read(self) -> Iterator[dict]:
        yield from self.verify()

    def append(self, records: list[dict]) -> int:
        """Append records (verifying the existing chain first). Returns number appended."""
        if not records:
            return 0
        existing = self.verify()
        prev = existing[-1]["_hash"] if existing else GENESIS
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        for body in records:
            h = content_hash([prev, body])
            lines.append(canonical({**body, "_prev": prev, "_hash": h}))
            prev = h
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        if self.compressed:
            # A gzip file may hold several members; appending a new member keeps every
            # earlier byte untouched and readers see one continuous text stream.
            buf = io.BytesIO()
            with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
                gz.write(payload)
            payload = buf.getvalue()
        # 'ab' never truncates; flush + fsync so a crash cannot silently drop an append.
        with self.path.open("ab") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        return len(lines)


class StateStore:
    """Layout of the v2 memory.

    ::

        state/
          analyses/<YYYY>/<YYYY-MM-DD>.jsonl.gz  one record per stock per trading date (+ revisions)
          plan_changes.jsonl                    plan differences vs the previous trading date / revision
          recommendations.jsonl                 recommendation events (created, triggered, ..., closed)
          runs.jsonl                            one line per update run (counts, missing data, freshness)
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def analyses(self, trading_date: str) -> AppendOnlyLog:
        return AppendOnlyLog(self.root / "analyses" / trading_date[:4] / f"{trading_date}.jsonl.gz")

    @property
    def plan_changes(self) -> AppendOnlyLog:
        return AppendOnlyLog(self.root / "plan_changes.jsonl")

    @property
    def recommendations(self) -> AppendOnlyLog:
        return AppendOnlyLog(self.root / "recommendations.jsonl")

    @property
    def runs(self) -> AppendOnlyLog:
        return AppendOnlyLog(self.root / "runs.jsonl")

    def analysis_dates(self) -> list[str]:
        base = self.root / "analyses"
        if not base.exists():
            return []
        return sorted(p.name.split(".")[0] for p in base.glob("*/*.jsonl.gz"))

    def latest_by_symbol(self, trading_date: str) -> dict[str, dict]:
        """Latest revision per symbol for one trading date."""
        out: dict[str, dict] = {}
        for rec in self.analyses(trading_date).read():
            out[rec["symbol"]] = rec  # later lines are later revisions
        return out

    def previous_date(self, trading_date: str) -> str | None:
        earlier = [d for d in self.analysis_dates() if d < trading_date]
        return earlier[-1] if earlier else None

    def verify_all(self) -> dict[str, int]:
        """Verify every file; returns {relative path: line count}."""
        counts = {}
        for p in sorted([*self.root.rglob("*.jsonl"), *self.root.rglob("*.jsonl.gz")]):
            counts[str(p.relative_to(self.root))] = len(AppendOnlyLog(p).verify())
        return counts
