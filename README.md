# 青河水质观测湖

区域资料中心用固定日批交接水质观测。站批冻结后，库管可调整实际卷槽，质控员可在原卷退役后交回此前采集的索引，夜班仍按同一日批号领取原序观测。

## 运行

需要 Python 3.11，依赖均来自标准库。在项目根目录执行控制台提供的完整回归入口。

```sh
python3 -B check_project.py
```

也可直接运行完整 unittest 套件或业务演示。

```sh
python3 -B -m unittest discover
python3 -B -m lake.demo
```

演示使用项目内的样例和独立临时库。它先签出青河桥东站的铜检 7、锌检 11，按样例重分卷、改槽并退役旧卷。只有铜检回件且新锌卷离线时，铜检领取待取。锌检补件后重开同一库，在锌卷依然离线时领出铜检 7 及原站行 1。第二批演示同值异出处、缺测和实测零值。

## 公开 Python 接口

用 `lake.storage.bootstrap.open_lake(path)` 作为连接上下文。首次打开库后调用 `initialize_lake(db)`。后续可重复初始化，或直接重开已经初始化的库。使用空闲连接调用下面的业务操作，每个操作自行管理读写事务。

| 入口 | 参数与返回 |
| --- | --- |
| `lake.intake.freeze.freeze_day(db, batch, initial_volume)` | 接受 `StationBatch(station, batch_id, rows)`，每行是 `StationRow(line, project, concentration)`。发布首卷并返回 `FrozenDay`，其中有 `day_id` 和 `row_count`。首卷使用从 0 起的局部槽。 |
| `lake.index.work_order.issue_work(db, day_id, volumes)` | 从现行目录选择一组在用卷，返回 `WorkOrder`。其 `work_id` 用于回件，`scope` 包含日批、来源布局和所签卷槽。 |
| `lake.layout.repack.repack_day(db, day_id, plan, *, before_commit=None)` | 接受 `RepackPlan(replace, moves)`。`replace` 是被选卷名序列，`moves` 是 `(SlotAddress, SlotAddress)` 源址和目标址对的序列。返回新的 `LayoutManifest`。可选回调在写卷和事务内发布就绪后、提交前运行。回调抛出异常即撤销本轮换装。 |
| `lake.layout.retirement.retire_volumes(db, volumes)` | 返回本次成功退役的卷名。现行卷、已退役卷及未登记卷不产生退役动作。 |
| `lake.index.receipt.register_index(db, artifact)` | 接受 `IndexArtifact` 或同形 JSON 对象，包含 `work_id`、`day_id`、`claims`。每条声明包含 `volume`、`slot`、`project`。返回新登记的证明数。同一来源行的相同声明可重报。 |
| `lake.query.project_read.read_project(db, day_id, project)` | 返回 `ProjectResult`。`complete` 含原序结果，`pending` 表示需取的卷暂不可读，`integrity_error` 表示核验失败。失败结果的 `rows` 为空。 |

`LayoutCatalog(db).current(day_id)` 可查看现行布局。`ReadabilityStore(db).set_readable(volume, readable)` 持久设置在库卷的可读状态，重开后继续生效。质控员可用 `VolumeStore(db).read_slot(address)` 读取并核验已签范围内的实际观测，再离线交回项目声明。

## 数据和错误语义

- 站名、站批号、卷名和项目名是去除首尾空白后保持原样的非空可打印字符串。名称按原样精确比较，接口拒绝带首尾空白的名称。站名与站批号的组合唯一。一个站批内原站行号各自唯一。原站行号为正的 64 位整数，物理槽为非负的 64 位整数。卷名在同一库中只分配一次。
- 项目决定命中。浓度为整数 μg/L 或 `None`，布尔值和数字字符串不作为整数接受。按输入位置生成从 1 开始的冻结序号，交付时按该序号排序。
- 换装计划逐个核对完整源卷槽，要覆盖被选卷的全部成员。目标可以跨卷重复使用局部槽号。未选卷继续参与现行布局。源卷离线或记录损坏时，换装抛出对应的存储异常并回滚。
- 索引证据只覆盖明确声明且验收的观测。错批、越界、与已核验项目不符或冲突的回件由 `ValueError` 拒收。未知工作单、未知日批和对不在库卷的卷道操作由 `KeyError` 报告。非法站批和非法换装计划由 `ValueError` 报告。
- 查询仅跳过所有成员都有已收排除证据的卷。需取卷按卷名顺序核验，遇到第一个不可读或损坏的卷时返回对应状态及卷名，无部分读数。卷内读取先核验完整性，再解码记录。
