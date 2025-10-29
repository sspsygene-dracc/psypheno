from dataclasses import dataclass


@dataclass(frozen=True)
class MGIAcessionID:
    mgi_accession_id: str

    def __post_init__(self):
        if not self.mgi_accession_id.startswith("MGI:"):
            raise ValueError(f"Invalid MGI Accession ID: {self.mgi_accession_id}")

    def __repr__(self) -> str:
        return str(self.mgi_accession_id)
