import sqlite3

from lake.index.evidence import EvidenceBook
from lake.intake.origin import require_name
from lake.layout.catalog import LayoutCatalog
from lake.query.coverage import CoverageIntegrityError, classify_coverage
from lake.query.result import ProjectResult, ReadStatus, assemble_project_result
from lake.query.volume_selection import select_candidate_volumes
from lake.storage.integrity import RecordIntegrityError
from lake.storage.readability import VolumeUnavailable
from lake.storage.transaction import transaction
from lake.storage.volume import VolumeStore


def read_project(db: sqlite3.Connection, day_id: int, project: str) -> ProjectResult:
    require_name(project, "project")
    with transaction(db):
        catalog = LayoutCatalog(db)
        manifest = catalog.current(day_id)
        accepted = EvidenceBook(db).accepted_for_day(day_id)
        transfers = catalog.transfers_for_day(day_id)
        try:
            coverage = classify_coverage(manifest, accepted, transfers, project)
        except CoverageIntegrityError:
            return ProjectResult(ReadStatus.INTEGRITY_ERROR)
        candidates = select_candidate_volumes(manifest, coverage)
        store = VolumeStore(db)
        observations = []
        for volume in candidates:
            try:
                rows = store.read_volume(volume, manifest.slots_for(volume))
            except VolumeUnavailable:
                return ProjectResult(ReadStatus.PENDING, problem_volume=volume)
            except RecordIntegrityError:
                return ProjectResult(ReadStatus.INTEGRITY_ERROR, problem_volume=volume)
            observations.extend(rows.values())
        return assemble_project_result(observations, project)
