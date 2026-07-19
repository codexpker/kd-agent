from app.gold_dataset import GoldDataset


def test_queued_records_are_not_loadable() -> None:
    dataset = GoldDataset()
    assert dataset.get("tranad-2022") is None
    assert dataset.get("anomaly-transformer-2022") is not None


def test_manifest_and_record_version_match() -> None:
    dataset = GoldDataset()
    record = dataset.get("anomaly-transformer-2022")
    assert record is not None
    assert record.dataset_version == dataset.manifest["dataset_version"]


def test_completed_record_has_metadata_only_source_provenance() -> None:
    sources = GoldDataset().sources_for("anomaly-transformer-2022")

    assert len(sources) == 1
    assert sources[0].source_type == "curated_registry"
    assert sources[0].access_policy == "metadata_only"
    assert sources[0].source_uri is None
    assert sources[0].retrieved_at.utcoffset().total_seconds() == 0
    assert sources[0].source_metadata["full_text_rights_confirmed"] is False
