from app.gold_dataset import GoldDataset
from app.models import SearchHit, SearchResponse


class DemoSearchService:
    def __init__(self, dataset: GoldDataset) -> None:
        self.dataset = dataset

    def search(self, query: str, limit: int) -> SearchResponse:
        q = query.casefold()
        scored: list[tuple[int, SearchHit]] = []
        for item in self.dataset.manifest["papers"]:
            title = item["title"]
            haystack = f"{title} time series anomaly detection transformer multivariate".casefold()
            tokens = [token for token in q.replace("，", " ").split() if token]
            score = sum(1 for token in tokens if token in haystack)
            record = self.dataset.get(item["paper_id"])
            hit = SearchHit(
                paper_id=item["paper_id"],
                title=title,
                year=record.year if record else int(item["paper_id"].rsplit("-", 1)[-1]),
                venue=record.venue if record else "Queued for review",
                snippet=(
                    "Gold development seed with evidence-grounded narrative analysis."
                    if record
                    else "Included in the first TAD annotation queue; deep analysis is not yet published."
                ),
                has_gold=record is not None,
            )
            scored.append((score, hit))
        scored.sort(key=lambda pair: (pair[0], pair[1].has_gold, pair[1].year), reverse=True)
        return SearchResponse(query=query, backend="demo", hits=[hit for _, hit in scored[:limit]])

