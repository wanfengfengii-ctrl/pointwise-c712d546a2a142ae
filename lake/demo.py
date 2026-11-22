import json
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.index.receipt import register_index
from lake.index.work_order import issue_work
from lake.intake.freeze import freeze_day
from lake.intake.station_batch import StationBatch, StationRow
from lake.layout.manifest import SlotAddress
from lake.layout.repack import repack_day
from lake.layout.repack_plan import RepackPlan
from lake.layout.retirement import retire_volumes
from lake.query.project_read import read_project
from lake.query.result import ProjectResult
from lake.storage.bootstrap import initialize_lake, open_lake
from lake.storage.readability import ReadabilityStore
from lake.storage.volume import VolumeStore


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _batch(record: dict) -> StationBatch:
    rows = tuple(StationRow(**row) for row in record["rows"])
    return StationBatch(record["station"], record["batch_id"], rows)


def _result(result: ProjectResult) -> dict:
    return {"status": result.status.value, "rows": [asdict(row) for row in result.rows]}


def main() -> None:
    samples = Path(__file__).resolve().parent.parent / "samples"
    first, second = _load(samples / "station_batches.json")
    placement = _load(samples / "repack_plan.json")
    index_sample = _load(samples / "late_index.json")
    moves = tuple((SlotAddress(*move["source"]), SlotAddress(*move["target"])) for move in placement["moves"])
    plan = RepackPlan(tuple(placement["replace"]), moves)

    with TemporaryDirectory(prefix="qinghe-demo-") as directory:
        path = Path(directory) / "lake.sqlite3"
        with open_lake(path) as db:
            initialize_lake(db)
            day = freeze_day(db, _batch(first), first["volume"])
            order = issue_work(db, day.day_id, plan.replace)
            store = VolumeStore(db)
            claims = []
            for source in index_sample["claims"]:
                address = SlotAddress(source["volume"], source["slot"])
                observed = store.read_slot(address)
                if observed.project != source["project"]:
                    raise RuntimeError("sample index disagrees with the source reading")
                claims.append({"volume": address.volume, "slot": address.slot, "project": observed.project})
            repack_day(db, day.day_id, plan)
            if retire_volumes(db, plan.replace) != plan.replace:
                raise RuntimeError("sample source volume did not retire")
            ReadabilityStore(db).set_readable(placement["offline"], False)
            partial_count = index_sample["first_receipt_count"]
            header = {"work_id": order.work_id, "day_id": day.day_id}
            first_receipt = register_index(db, {**header, "claims": claims[:partial_count]})
            partial = _result(read_project(db, day.day_id, "铜检"))
            second_receipt = register_index(db, {**header, "claims": claims[partial_count:]})
            second_day = freeze_day(db, _batch(second), second["volume"])

        with open_lake(path) as db:
            initialize_lake(db)
            completed = _result(read_project(db, day.day_id, "铜检"))
            second_read = _result(read_project(db, second_day.day_id, "铜检"))

    expected_partial = {"status": "pending", "rows": []}
    expected_complete = {
        "status": "complete",
        "rows": [{"sequence": 1, "origin": {"station": "青河桥东", "batch_id": "QH-A", "line": 1},
                  "project": "铜检", "concentration": 7}],
    }
    if (first_receipt, second_receipt) != (1, 1) or partial != expected_partial or completed != expected_complete:
        raise RuntimeError(f"sample receipts or read results differ: {partial!r}, {completed!r}")
    second_values = [(row["sequence"], row["origin"]["line"], row["concentration"]) for row in second_read["rows"]]
    if second_read["status"] != "complete" or second_values != [(1, 9, 7), (2, 3, 7), (3, 12, None), (4, 5, 0)]:
        raise RuntimeError(f"second station batch differs: {second_read!r}")
    scenario = {
        "case_id": "V7.partial_then_complete",
        "input": {"station_batch": first, "repack": placement, "receipts": [claims[:partial_count], claims[partial_count:]]},
        "expected": expected_partial,
        "actual": partial,
        "downstream_expected": expected_complete,
        "downstream_actual": completed,
        "code_paths": ["lake/layout/repack.py", "lake/index/receipt.py", "lake/query/coverage.py", "lake/query/project_read.py"],
        "oracle": "旧站行 1 手工核得铜检 7。锌卷只载旧站行 2，补证前无法排除，补证后离线仍可排除。",
    }
    print("POINTWISE_SCENARIO " + json.dumps(scenario, ensure_ascii=False, sort_keys=True))
    print(json.dumps({"day_id": second_day.day_id, "project_read": second_read}, ensure_ascii=False))


if __name__ == "__main__":
    main()
