from dataclasses import dataclass


@dataclass(frozen=True)
class EnsemblGene:
    ensembl_id: str

    def __post_init__(self):
        if not self.ensembl_id.startswith("ENS"):
            raise ValueError(f"Invalid Ensembl ID: {self.ensembl_id}")

    def __repr__(self) -> str:
        return str(self.ensembl_id)
