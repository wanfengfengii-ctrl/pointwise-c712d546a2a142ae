from collections.abc import Mapping
from dataclasses import dataclass

from lake.intake.origin import require_name
from lake.layout.manifest import SlotAddress


@dataclass(frozen=True)
class IndexClaim:
    address: SlotAddress
    project: str

    def __post_init__(self) -> None:
        if not isinstance(self.address, SlotAddress):
            raise ValueError("index claim requires a full source slot address")
        require_name(self.project, "claimed project")


@dataclass(frozen=True)
class IndexArtifact:
    work_id: int
    day_id: int
    claims: tuple[IndexClaim, ...]

    def __post_init__(self) -> None:
        for field in ("work_id", "day_id"):
            value = getattr(self, field)
            if type(value) is not int or not 1 <= value <= 2**63 - 1:
                raise ValueError(f"{field} must be a positive 64-bit integer")
        if not isinstance(self.claims, tuple) or not all(isinstance(claim, IndexClaim) for claim in self.claims):
            raise ValueError("claims must be a tuple of index claims")


def parse_index_artifact(document: Mapping[str, object] | IndexArtifact) -> IndexArtifact:
    if isinstance(document, IndexArtifact):
        return document
    if not isinstance(document, Mapping) or document.keys() != {"day_id", "work_id", "claims"}:
        raise ValueError("index artifact requires day_id, work_id and claims")
    records = document["claims"]
    if not isinstance(records, (tuple, list)):
        raise ValueError("artifact claims must be an array")
    claims = []
    for record in records:
        if not isinstance(record, Mapping) or record.keys() != {"volume", "slot", "project"}:
            raise ValueError("an index claim requires volume, slot and project")
        address = SlotAddress(record["volume"], record["slot"])
        claims.append(IndexClaim(address, record["project"]))
    return IndexArtifact(document["work_id"], document["day_id"], tuple(claims))
