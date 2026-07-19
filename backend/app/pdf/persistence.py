from dataclasses import dataclass
from typing import Literal

from app.pdf.contracts import PersistenceRight


class PersistenceDeniedError(PermissionError):
    pass


PdfPersistenceAction = Literal["created", "unchanged"]


@dataclass(frozen=True)
class PdfPersistenceResult:
    paper_id: str
    parse_run_id: int
    action: PdfPersistenceAction


def require_persistence_right(right: PersistenceRight | None) -> PersistenceRight:
    if right is None:
        raise PersistenceDeniedError(
            "Persistence requires open full text, a user private copy, or institutional authorization"
        )
    return right
