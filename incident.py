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
from lake.storage.bootstrap import initialize_lake, open_lake
from lake.storage.readability import ReadabilityStore
from lake.storage.volume import VolumeStore


def snapshot(result):
    return {"status": result.status.value, "volume": result.problem_volume,
            "rows": [asdict(row) for row in result.rows]}


def observe(path):
    samples = Path(__file__).resolve().parent / "samples"
    station = json.loads((samples / "station_batches.json").read_text(encoding="utf-8"))[0]
    placement = json.loads((samples / "repack_plan.json").read_text(encoding="utf-8"))
    rows = tuple(StationRow(**row) for row in station["rows"])
    batch = StationBatch(station["station"], station["batch_id"], rows)
    moves = tuple((SlotAddress(*move["source"]), SlotAddress(*move["target"])) for move in placement["moves"])
    plan = RepackPlan(tuple(placement["replace"]), moves)
    zinc = placement["offline"]

    with open_lake(path) as db:
        initialize_lake(db)
        day_id = freeze_day(db, batch, station["volume"]).day_id
        order = issue_work(db, day_id, plan.replace)
        store = VolumeStore(db)
        claims = [{"volume": address.volume, "slot": address.slot, "project": store.read_slot(address).project}
                  for address in sorted(order.scope.addresses)]
        copper, zinc_claim = claims
        repack_day(db, day_id, plan)
        if retire_volumes(db, plan.replace) != plan.replace:
            raise RuntimeError("旧卷未退役，未进入事故场景")
        header = {"work_id": order.work_id, "day_id": day_id}
        if register_index(db, {**header, "claims": [copper]}) != 1:
            raise RuntimeError("铜检索引未实收")
        ReadabilityStore(db).set_readable(zinc, False)
        partial = snapshot(read_project(db, day_id, "铜检"))
        if register_index(db, {**header, "claims": [zinc_claim]}) != 1:
            raise RuntimeError("锌检补件未实收")

    with open_lake(path) as db:
        offline = snapshot(read_project(db, day_id, "铜检"))
        ReadabilityStore(db).set_readable(zinc, True)
        online = snapshot(read_project(db, day_id, "铜检"))
    return {"铜证已收": partial, "补齐且锌卷离线": offline, "补齐且两卷可读": online}


def main():
    complete = {"status": "complete", "volume": None, "rows": [
        {"sequence": 1, "origin": {"station": "青河桥东", "batch_id": "QH-A", "line": 1},
         "project": "铜检", "concentration": 7},
    ]}
    expected = {
        "铜证已收": {"status": "pending", "volume": "zinc", "rows": []},
        "补齐且锌卷离线": complete,
        "补齐且两卷可读": complete,
    }
    with TemporaryDirectory(prefix="qinghe-incident-") as directory:
        actual = observe(Path(directory) / "lake.sqlite3")
    print(json.dumps({"expected": expected, "actual": actual}, ensure_ascii=False))
    if actual != expected:
        print("INCIDENT_WRONG_INDEX_COVERAGE")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
