import pytest

from app.pdf.contracts import PersistenceRight
from app.pdf.persistence import PersistenceDeniedError, require_persistence_right


def test_pdf_persistence_without_right_is_blocked() -> None:
    with pytest.raises(PersistenceDeniedError):
        require_persistence_right(None)


def test_confirmed_private_copy_is_accepted() -> None:
    right = PersistenceRight(basis="user_private_copy", confirmed_by="local-user")
    assert require_persistence_right(right).basis == "user_private_copy"

