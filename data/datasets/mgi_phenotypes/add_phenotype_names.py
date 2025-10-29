#!/usr/bin/env python3

import json
from pathlib import Path
from typing import Any


def load_phenotype_mapping(json_file: Path) -> dict[str, str]:
    """Load MP phenotype IDs and their labels from mp.json."""
    mp_to_label: dict[str, str] = {}

    with open(json_file, "r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    # Navigate to the nodes in the graph
    for graph in data.get("graphs", []):
        for node in graph.get("nodes", []):
            node_id = node.get("id", "")
            label = node.get("lbl", "")

            # Extract MP ID from format "http://purl.obolibrary.org/obo/MP_0003631"
            if "MP_" in node_id:
                mp_id_with_underscore = node_id.split("MP_")[-1]
                mp_id_colon = f"MP:{mp_id_with_underscore}"
                mp_to_label[mp_id_colon] = label

    return mp_to_label


def parse_rpt_file(
    rpt_file: Path, phenotype_mapping: dict[str, str]
) -> tuple[list[str], dict[str, str]]:
    """Parse MGI_PhenotypicAllele.rpt and add phenotype labels."""
    with open(rpt_file, "r", encoding="utf-8") as f:
        lines: list[str] = f.readlines()

    # Skip comment lines at the beginning
    data_lines: list[str] = []

    for line in lines:
        if line.startswith("#"):
            continue
        if line.strip():  # Non-empty line
            data_lines.append(line.strip())

    return data_lines, phenotype_mapping


def add_phenotype_labels(
    data_lines: list[str], phenotype_mapping: dict[str, str]
) -> list[str]:
    """Add phenotype label column to data lines."""
    result_lines: list[str] = []

    for line in data_lines:
        fields = line.split("\t")

        # Column 11 (1-indexed, index 10) contains MP IDs
        if len(fields) > 10 and fields[10].strip():
            mp_ids: list[str] = [mp.strip() for mp in fields[10].split(",")]
            labels: list[str] = []

            for mp_id in mp_ids:
                if mp_id and mp_id in phenotype_mapping:
                    labels.append(phenotype_mapping[mp_id])

            # Insert the labels as the 3rd column only if present
            label_col = " | ".join(labels) if labels else ""
            if label_col:
                fields.insert(2, label_col)
                result_lines.append("\t".join(fields))
            # else: skip row entirely when no phenotype labels
        # else: skip row entirely when no MP IDs

    return result_lines


def main() -> None:
    # Setup paths
    script_dir = Path(__file__).parent
    rpt_file = script_dir / "MGI_PhenotypicAllele.rpt"
    columns_file = script_dir / "columns.txt"
    json_file = script_dir / "mp.json"
    output_file = script_dir / "MGI_PhenotypicAllele_annotated.rpt"

    # Load phenotype mappings
    print("Loading phenotype mappings from mp.json...")
    phenotype_mapping = load_phenotype_mapping(json_file)
    print(f"Loaded {len(phenotype_mapping)} phenotype mappings")

    # Load columns
    print("Loading column headers...")
    with open(columns_file, "r") as f:
        columns: list[str] = [line.strip() for line in f.readlines()]

    # Insert the new column header as the 3rd column
    columns.insert(2, "High-level Mammalian Phenotype Names (comma-delimited)")

    # Parse RPT file
    print("Parsing MGI_PhenotypicAllele.rpt...")
    data_lines, phenotype_mapping = parse_rpt_file(rpt_file, phenotype_mapping)
    print(f"Found {len(data_lines)} data lines")

    # Add phenotype labels
    print("Adding phenotype labels...")
    result_lines = add_phenotype_labels(data_lines, phenotype_mapping)

    # Write output
    print(f"Writing to {output_file}...")
    with open(output_file, "w") as f:
        # Write header
        f.write("\t".join(columns) + "\n")

        # Write data lines
        for line in result_lines:
            f.write(line + "\n")

    print("Done!")


if __name__ == "__main__":
    main()
