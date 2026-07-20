import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

from app.pdf.adapters import PyMuPdfAdapter
from app.pdf.contracts import PersistenceRight
from app.pdf.persistence import PersistenceDeniedError, require_persistence_right
from app.models import DocumentArtifact, DocumentStructure
from app.services.private_pdf_preview import (
    PrivatePdfNotFoundError,
    PrivatePdfPreviewError,
    PrivatePdfPreviewService,
)


def test_pdf_persistence_without_right_is_blocked() -> None:
    with pytest.raises(PersistenceDeniedError):
        require_persistence_right(None)


def test_confirmed_private_copy_is_accepted() -> None:
    right = PersistenceRight(basis="user_private_copy", confirmed_by="local-user")
    assert require_persistence_right(right).basis == "user_private_copy"


def test_pymupdf_adapter_extracts_objective_locations_when_installed(
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "generated-layout-fixture.pdf"
    document = fitz.open()
    first_page = document.new_page()
    first_page.insert_text((72, 72), "1 Introduction")
    first_page.insert_text((72, 110), "Figure 1: Fixture overview")
    first_page.insert_text((72, 150), "As shown in Figure 1, the fixture is visible.")
    second_page = document.new_page()
    second_page.insert_text((72, 72), "2 Experiments")
    document.save(path)
    document.close()

    parsed = PyMuPdfAdapter().parse(path)

    assert parsed.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert parsed.page_count == 2
    assert [item.title for item in parsed.sections] == ["Introduction", "Experiments"]
    assert parsed.sections[0].heading_bbox is not None
    assert parsed.artifacts[0].label == "Figure 1"
    assert parsed.artifacts[0].caption_bbox is not None
    assert parsed.references[0].artifact_id == parsed.artifacts[0].id
    assert parsed.references[0].bbox is not None


def test_pymupdf_adapter_prefers_pdf_toc_and_rejects_numeric_table_rows(
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "toc-layout-fixture.pdf"
    document = fitz.open()
    first_page = document.new_page()
    first_page.insert_text((72, 72), "INTRODUCTION")
    first_page.insert_text((72, 110), "76.72 56.19 59.78 86.87")
    second_page = document.new_page()
    second_page.insert_text((72, 72), "MODEL ANALYSIS")
    document.set_toc(
        [
            [1, "1 Introduction", 1],
            [2, "4.2 Model Analysis", 2],
        ]
    )
    document.save(path)
    document.close()

    parsed = PyMuPdfAdapter().parse(path)

    assert [(item.title, item.level, item.page_start) for item in parsed.sections] == [
        ("Introduction", 1, 1),
        ("Model Analysis", 2, 2),
    ]
    assert all("76.72" not in item.title for item in parsed.sections)
    assert parsed.sections[0].heading_bbox is not None


def test_private_pdf_preview_requires_hash_match_and_renders_png(
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    path = tmp_path / "private.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Figure 1: Authorized private preview")
    document.save(path)
    document.close()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    structure = DocumentStructure(
        paper_id="paper-1",
        source="parsed_pdf",
        parser_name="pymupdf",
        parser_version="test",
        file_sha256=digest,
        page_count=1,
        sections=[],
        artifacts=[],
        references=[],
    )
    artifact = DocumentArtifact(
        id="art-1",
        artifact_type="figure",
        label="Figure 1",
        caption="Authorized private preview",
        page=1,
        caption_bbox=[70.0, 55.0, 300.0, 80.0],
    )

    rendered = PrivatePdfPreviewService(str(tmp_path)).render_page(
        structure, 1, artifact
    )

    assert rendered.startswith(b"\x89PNG\r\n\x1a\n")
    assert str(path).encode() not in rendered
    with pytest.raises(PrivatePdfPreviewError, match="outside"):
        PrivatePdfPreviewService(str(tmp_path)).render_page(structure, 2)
    with pytest.raises(PrivatePdfNotFoundError, match="SHA-256"):
        PrivatePdfPreviewService(str(tmp_path)).render_page(
            structure.model_copy(update={"file_sha256": "0" * 64}), 1
        )


def test_offline_app_import_keeps_database_and_pdf_dependencies_lazy() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.main; "
                "assert 'sqlalchemy' not in sys.modules; "
                "assert 'fitz' not in sys.modules; "
                "assert 'app.storage.pdf_repository' not in sys.modules"
            ),
        ],
        cwd=backend_root,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stderr == ""
