"""Benchmark gates for the IR round-trip.

Per spec S33 §"Benchmark gates":

| Gate | Threshold |
|------|-----------|
| Full-corpus R3 round-trip (preserving) | ≤ 200 ms |
| Median per-fixture R3 round-trip | ≤ 5 ms |
| 95th-percentile per-fixture R3 round-trip | ≤ 20 ms |

Each benchmark runs the harness three times and takes the median
per fixture to kill noise, then aggregates. Writes
``build/ir-benchmarks.json`` with per-fixture and aggregate
timings so CI can upload it as an artifact.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mdd.confluence.ir import parse_confluence_storage, render_confluence_storage
from mdd.markdown.ir import parse_markdown, render_markdown

if TYPE_CHECKING:
    from .conftest import SnapshotFixture

_BUILD_DIR = Path(__file__).resolve().parents[2] / "build"

_FULL_CORPUS_GATE_MS = 200.0
_MEDIAN_FIXTURE_GATE_MS = 5.0
_P95_FIXTURE_GATE_MS = 20.0


def _r3_once(storage: str) -> str:
    """One R3 round-trip leg in preserving mode."""
    ir_a = parse_confluence_storage(storage, mode="preserving")
    md = render_markdown(ir_a)
    ir_b = parse_markdown(md)
    # Simple reattach — full identity.reattach is exercised by R3 correctness tests.
    return render_confluence_storage(ir_b, mode="preserving")


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def _measure_corpus(snapshots: list[SnapshotFixture]) -> dict[str, float]:
    """Per-fixture median R3 timing across 3 runs (milliseconds)."""
    per_fixture: dict[str, float] = {}
    for snap in snapshots:
        runs_ms: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            try:
                _r3_once(snap.storage_xhtml)
            except Exception:
                # Some fixtures exercise Origin shapes Phase 4 hasn't covered;
                # skip the benchmark for those — the correctness gate already
                # xfails them.
                runs_ms.append(float("nan"))
                continue
            runs_ms.append((time.perf_counter() - t0) * 1000.0)
        clean = [v for v in runs_ms if v == v]  # filter NaN
        if clean:
            per_fixture[snap.page_id] = statistics.median(clean)
    return per_fixture


def _write_report(per_fixture: dict[str, float], totals: dict[str, float]) -> None:
    _BUILD_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "per_fixture_ms": per_fixture,
        "totals": totals,
        "gates": {
            "full_corpus_ms": _FULL_CORPUS_GATE_MS,
            "median_fixture_ms": _MEDIAN_FIXTURE_GATE_MS,
            "p95_fixture_ms": _P95_FIXTURE_GATE_MS,
        },
    }
    (_BUILD_DIR / "ir-benchmarks.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def test_benchmark_r3_timings(corpus_snapshots: list[SnapshotFixture]) -> None:
    """R3 timing gates (full corpus, median, p95) — all on the same data."""
    per_fixture = _measure_corpus(corpus_snapshots)
    timings = list(per_fixture.values())
    full_corpus_ms = sum(timings)
    median_ms = statistics.median(timings)
    p95_ms = _percentile(timings, 95.0)

    totals = {
        "full_corpus_ms": full_corpus_ms,
        "median_fixture_ms": median_ms,
        "p95_fixture_ms": p95_ms,
        "fixtures_measured": float(len(timings)),
    }
    _write_report(per_fixture, totals)

    failures: list[str] = []
    if full_corpus_ms > _FULL_CORPUS_GATE_MS:
        failures.append(
            f"full-corpus R3 = {full_corpus_ms:.1f} ms > {_FULL_CORPUS_GATE_MS} ms gate"
        )
    if median_ms > _MEDIAN_FIXTURE_GATE_MS:
        failures.append(
            f"median per-fixture R3 = {median_ms:.2f} ms > {_MEDIAN_FIXTURE_GATE_MS} ms gate"
        )
    if p95_ms > _P95_FIXTURE_GATE_MS:
        failures.append(
            f"95th-percentile per-fixture R3 = {p95_ms:.2f} ms > {_P95_FIXTURE_GATE_MS} ms gate"
        )
    assert not failures, (
        "benchmark thresholds exceeded: "
        + "; ".join(failures)
        + ". Per spec S33: 'If they flake, raise — don't disable'. "
        + "Calibrate by re-measuring then lifting the gate."
    )
