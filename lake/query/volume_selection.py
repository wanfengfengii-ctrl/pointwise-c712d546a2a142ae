from collections.abc import Mapping

from lake.layout.manifest import LayoutManifest
from lake.query.coverage import Coverage


def select_candidate_volumes(manifest: LayoutManifest, coverage: Mapping[str, Coverage]) -> tuple[str, ...]:
    candidates = []
    for volume in manifest.volumes:
        proved = coverage.get(volume)
        if proved is None or proved.matches or proved.unknown:
            candidates.append(volume)
    return tuple(candidates)
