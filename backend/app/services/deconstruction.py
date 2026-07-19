from app.gold_dataset import GoldDataset
from app.models import PaperDeconstruction


class PaperNotFoundError(LookupError):
    pass


class DeconstructionService:
    def __init__(self, dataset: GoldDataset) -> None:
        self.dataset = dataset

    def get(self, paper_id: str) -> PaperDeconstruction:
        result = self.dataset.get(paper_id)
        if result is None:
            raise PaperNotFoundError(paper_id)
        return result

