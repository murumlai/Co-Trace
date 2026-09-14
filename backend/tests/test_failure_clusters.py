from __future__ import annotations

from app.aggregator import compute_failure_clusters, compute_pareto
from app.models import UnitRecord
from app.record_views import signature_for


def _failure(
    unit_id: str,
    serial: str,
    message: str,
    start_time: str,
    *,
    station: str = "ST1",
    lot: str = "LOT1",
) -> UnitRecord:
    return UnitRecord(
        unit_id=unit_id,
        serial_number=serial,
        result="FAIL",
        error_code="E001",
        error_message=message,
        failing_step="VoltageCheck",
        station_id=station,
        lot_id=lot,
        product_code="P1",
        start_time=start_time,
        run_folder=unit_id,
    )


def test_clusters_group_normalized_signatures_and_match_pareto() -> None:
    records = [
        _failure("u1", "SN1", "Retry count 3 exceeded", "2026-01-01T10:00:00"),
        _failure(
            "u2",
            "SN2",
            "Retry count 7 exceeded",
            "2026-01-01T11:00:00",
            station="ST2",
            lot="LOT2",
        ),
        UnitRecord(unit_id="u3", result="PASS", run_folder="u3"),
    ]

    clusters = compute_failure_clusters(records)
    pareto = compute_pareto(records)

    assert len(clusters) == 1
    assert clusters[0]["signature"] == signature_for(records[0])
    assert clusters[0]["count"] == pareto[0]["count"] == 2
    assert clusters[0]["affected_serials"] == ["SN1", "SN2"]
    assert clusters[0]["stations"] == ["ST1", "ST2"]
    assert clusters[0]["lots"] == ["LOT1", "LOT2"]
    assert pareto[0]["signature"] == clusters[0]["signature"]


def test_clusters_sort_by_count_then_latest_failure() -> None:
    records = [
        _failure("a1", "A1", "Family A", "2026-01-01T10:00:00"),
        _failure("b1", "B1", "Family B", "2026-01-01T11:00:00"),
        _failure("c1", "C1", "Family C", "2026-01-01T09:00:00"),
        _failure("c2", "C2", "Family C", "2026-01-01T12:00:00"),
    ]

    clusters = compute_failure_clusters(records)

    assert [cluster["count"] for cluster in clusters] == [2, 1, 1]
    assert clusters[1]["last_seen"] == "2026-01-01T11:00:00"


def test_clusters_handle_empty_batch() -> None:
    assert compute_failure_clusters([]) == []