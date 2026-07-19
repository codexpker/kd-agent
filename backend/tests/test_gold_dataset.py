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

