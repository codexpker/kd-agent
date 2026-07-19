import json
from functools import lru_cache
from importlib.resources import files

from app.models import PaperDeconstruction, PaperSource


class GoldDataset:
    def __init__(self) -> None:
        root = files("app.data.gold").joinpath("tad_v0_1")
        self._manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
        self._records: dict[str, PaperDeconstruction] = {}
        self._sources: dict[str, list[PaperSource]] = {}
        for item in self._manifest["papers"]:
            sources = [PaperSource.model_validate(source) for source in item.get("sources", [])]
            source_keys = [source.source_key for source in sources]
            if len(source_keys) != len(set(source_keys)):
                raise ValueError(f"duplicate source_key for {item['paper_id']}")
            self._sources[item["paper_id"]] = sources
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

    def sources_for(self, paper_id: str) -> list[PaperSource]:
        return list(self._sources.get(paper_id, []))


@lru_cache
def get_gold_dataset() -> GoldDataset:
    return GoldDataset()
