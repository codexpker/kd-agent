import json
from functools import lru_cache
from importlib.resources import files

from app.models import PaperDeconstruction


class GoldDataset:
    def __init__(self) -> None:
        root = files("app.data.gold").joinpath("tad_v0_1")
        self._manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
        self._records: dict[str, PaperDeconstruction] = {}
        for item in self._manifest["papers"]:
            if item["status"] == "queued":
                continue
            filename = item["paper_id"].replace("-2022", "") + ".json"
            if item["paper_id"] == "anomaly-transformer-2022":
                filename = "anomaly_transformer.json"
            payload = json.loads(root.joinpath("records", filename).read_text(encoding="utf-8"))
            record = PaperDeconstruction.model_validate(payload)
            if record.dataset_version != self._manifest["dataset_version"]:
                raise ValueError("record and manifest dataset versions differ")
            self._records[record.paper_id] = record

    @property
    def manifest(self) -> dict:
        return self._manifest

    def get(self, paper_id: str) -> PaperDeconstruction | None:
        return self._records.get(paper_id)

    def list_records(self) -> list[PaperDeconstruction]:
        return list(self._records.values())


@lru_cache
def get_gold_dataset() -> GoldDataset:
    return GoldDataset()

