from app.pdf.contracts import PersistenceRight


class PersistenceDeniedError(PermissionError):
    pass


def require_persistence_right(right: PersistenceRight | None) -> PersistenceRight:
    if right is None:
        raise PersistenceDeniedError(
            "Persistence requires open full text, a user private copy, or institutional authorization"
        )
    return right

