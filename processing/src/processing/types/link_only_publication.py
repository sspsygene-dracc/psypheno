"""A paper listed on /publications with links but no data table (#242).

Some papers belong in the knowledge base although nothing about them loads as a
table — the useful artifact is a link out, typically a UCSC Cell Browser. Their
dataset `config.yaml` carries `deployTo`, `publication` and a dataset-level
`links:` list, and no `tables:`. `load-db` writes one `link_only_publications`
row per such dataset; the int/prod subsetter and the destination guard treat
the row like any other dataset-owned content, scoped by its `deployTo`.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from processing.types.table_to_process_config import DatasetLink, PublicationInfo


@dataclass
class LinkOnlyPublication:
    dataset: str
    deploy_to: frozenset[str]
    publication: PublicationInfo
    links: list[DatasetLink] = field(default_factory=list)
    description: str | None = None

    @classmethod
    def from_yaml(
        cls,
        loaded: dict[str, Any],
        *,
        dataset: str,
        deploy_to: list[str],
        yaml_path: Path,
    ) -> "LinkOnlyPublication":
        publication = PublicationInfo.from_yaml(loaded.get("publication") or {})
        if not publication.doi:
            raise ValueError(
                f"{yaml_path}: a dataset with `links:` and no tables is listed on "
                f"/publications by its DOI, so `publication.doi` is required."
            )
        raw_links = loaded.get("links") or []
        if not isinstance(raw_links, list) or not raw_links:
            raise ValueError(
                f"{yaml_path}: `links:` must be a non-empty list of URLs or "
                f"{{url, label, description}} entries."
            )
        description = loaded.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError(f"{yaml_path}: `description:` must be a string.")
        return cls(
            dataset=dataset,
            deploy_to=frozenset(deploy_to),
            publication=publication,
            links=[DatasetLink.from_yaml(entry, table_name=dataset) for entry in raw_links],
            description=description.strip() if description else None,
        )
