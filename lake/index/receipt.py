import hmac
import sqlite3
from collections.abc import Mapping

from lake.index.artifact import IndexArtifact, parse_index_artifact
from lake.index.evidence import EvidenceBook
from lake.index.work_order import WorkOrder, WorkOrderBook
from lake.layout.manifest import SlotAddress
from lake.storage.integrity import project_commitment
from lake.storage.transaction import transaction


def validate_receipt(
    order: WorkOrder, artifact: IndexArtifact, commitments: Mapping[SlotAddress, bytes],
    accepted: Mapping[SlotAddress, str],
) -> dict[SlotAddress, str]:
    if artifact.work_id != order.work_id or artifact.day_id != order.scope.day_id:
        raise ValueError("artifact does not match the work order and frozen day")
    submitted = {}
    for claim in artifact.claims:
        address = claim.address
        if not order.scope.contains(address):
            raise ValueError(f"source slot outside signed work scope: {address!r}")
        prior = submitted.get(address, accepted.get(address))
        if prior is not None and prior != claim.project:
            raise ValueError(f"conflicting projects for source slot: {address!r}")
        if not hmac.compare_digest(project_commitment(address, claim.project), commitments[address]):
            raise ValueError(f"claimed project differs from the signed source slot: {address!r}")
        submitted[address] = claim.project
    return {address: project for address, project in submitted.items() if address not in accepted}


def register_index(db: sqlite3.Connection, document: Mapping[str, object] | IndexArtifact) -> int:
    artifact = parse_index_artifact(document)
    with transaction(db, write=True):
        orders = WorkOrderBook(db)
        order = orders.get(artifact.work_id)
        evidence = EvidenceBook(db)
        accepted = evidence.accepted_for_day(order.scope.day_id)
        claims = validate_receipt(order, artifact, orders.project_commitments(order.work_id), accepted)
        return evidence.record_claims(artifact, claims)
