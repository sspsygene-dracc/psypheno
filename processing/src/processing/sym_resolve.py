#!/usr/bin/env python3

import logging
import sys
import argparse
import gzip
from collections import defaultdict


def parse_args() -> argparse.Namespace:
    "setup logging, parse command line arguments and options. -h shows auto-generated help page"
    parser = argparse.ArgumentParser(
        """usage: %prog [options] -g hgncFile inputTsv outputTsv - 
    convert human symbols to more stable HGNC identifiers.
    Recognizes outdated or deprecrated symbols and gene names. Input file must have a header line.
    By default, assumes that the first field is the symbol and converts that field to a HGNC:ID.

    Examples:
        symResolve -g ../../hgnc_complete_set.txt brennan.tsv \
            brennan.hgnc.tsv -m ensembl_id=ensembl -r brennan.dropped.txt 
        symResolve -m gene_id=ensembl schema.tsv schema.hgnc.tsv -r schema.dropped.tsv
        symResolve ../hgnc/hgnc_complete_set.txt sfari.tsv sfari.hgnc.tsv -f 1
    """
    )

    parser.add_argument(
        "-d", "--debug", dest="debug", action="store_true", help="show debug messages"
    )
    parser.add_argument(
        "-f",
        "--outField",
        dest="out_field",
        action="store",
        help="Write HGNC to this field, default is first field. A number, 0-based.",
        default="0",
    )
    parser.add_argument(
        "-i",
        "--insert",
        dest="insert",
        action="store_true",
        help="Instead of replacing the value in field -f, "
        "insert a new column in front of it with the HGNC-ID",
    )
    parser.add_argument(
        "-r",
        "--removed",
        dest="removed_fname",
        action="store",
        help="Write genes that were removed to this file",
    )
    parser.add_argument(
        "-m",
        "--mapFields",
        dest="map_fields",
        action="store",
        help=(
            "process this field from the input file, default is first field. "
            "If file has a header line, can be a comma-sep list of field names. "
            "Can have format <fieldName>=<idName>, with <idName> "
            "being one of the HGNC ID names, e.g. 'ensembl'."
            "For each column, you can specify the content of the "
            "field, e.g. ens=ensembl,uip=uniprot,symbol=sym"
        ),
        default=None,
    )
    parser.add_argument(
        "-g",
        "--hgncInfo",
        dest="hgnc_fname",
        action="store",
        help="read hgnc_complete_set.txt from this file, default is %default. "
        "Grab one with wget "
        "https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
        default="/hive/data/outside/hgnc/current/hgnc_complete_set.txt",
    )
    parser.add_argument(
        "",
        "--mgi",
        dest="mgi",
        action="store",
        help="To map mouse symbols. Read HGNC_AllianceHomology.rpt from this file. "
        "Get this file with wget "
        "https://www.informatics.jax.org/downloads/reports/HGNC_AllianceHomology.rpt. "
        "Use key 'mgiSym' in -m.",
    )

    parser.add_argument(
        "",
        "--zfin",
        dest="zfin",
        action="store",
        help="To map zebrafish symbols. Read human-orthos.tsv. "
        "Get this file with wget "
        "https://zfin.org/downloads/human_orthos.txt. Use key 'zfinSym' if using -m.",
    )
    parser.add_argument("in_fname", help="input TSV file name")
    parser.add_argument("out_fname", help="output TSV file name")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger().setLevel(logging.INFO)

    return args


def get_syms(
    row: list[str], index_map: dict[str, int], field_names: list[str]
) -> set[str]:
    "return list of syms from row"
    syms: set[str] = set()

    for field_name in field_names:
        field_idx = index_map[field_name]
        alias_str = row[field_idx]
        if alias_str != "":
            alias_list = alias_str.split("|")
            alias_list = [x.upper() for x in alias_list]
            for al_sym in alias_list:
                syms.add(al_sym)

    return syms


def add_syms(row: list[str], syms: list[str], field_idx: int) -> None:
    alias_str = row[field_idx]
    if alias_str != "":
        alias_list = alias_str.split("|")
        alias_list = [x.upper() for x in alias_list]
        for al_sym in alias_list:
            if al_sym in syms:
                logging.error("sym %s is already in the list", al_sym)
                sys.exit(1)
            else:
                syms.append(al_sym)


acc_types = ["ensembl_gene_id", "entrez_id", "uniprot_ids"]
acc_type_names = ["ensembl", "entrez", "uniprot"]


def parse_zfin(fname: str) -> dict[str, str]:
    "parse zfin human_orthos.txt, return symbol -> HGNC-ID"
    skipped: list[str] = []
    logging.info("Parsing %s", fname)
    lines = open_split(fname)
    sym_to_id: dict[str, str] = {}
    for l in lines:
        row = l.split("\t")
        sym = row[1]
        hgnc_id = row[7]
        if hgnc_id == "":
            skipped.append(sym)
        sym_to_id[hgnc_id] = sym
    logging.info("No HGNC for these genes in zfin file: %s", repr(skipped))
    return sym_to_id


def parse_mgi(fname: str) -> dict[str, str]:
    "parse MGI HGNC_AllianceHomology.rpt file, return symbol -> HGNC-ID"
    logging.info("Parsing %s", fname)
    lines = open_split(fname)
    headers: list[str] = lines[0].split("\t")
    assert headers[-1] == "HGNC ID"
    assert headers[1] == "Marker Symbol"
    _field_idx: dict[str, int] = dict([(h, i) for i, h in enumerate(headers)])
    sym_to_id: dict[str, str] = {}
    hgnc_idx: int = headers.index("HGNC ID")

    for l in lines[1:]:
        row = l.split("\t")
        row = [x.strip('"') for x in row]

        main_sym: str = row[1]
        gene_id: str = row[hgnc_idx]

        if gene_id == "null":
            continue

        assert main_sym not in sym_to_id
        sym_to_id[main_sym] = gene_id

    return sym_to_id


def open_split(fname: str) -> list[str]:
    if fname.endswith(".gz"):
        fh = gzip.open(fname, "rt")
    else:
        fh = open(fname)
    lines = fh.read().splitlines()
    return lines


def parse_hgnc(fname: str) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """parse HGNC return two dictionaries with symbol -> HGNC ID
    and another dict with accession -> HGNC ID.
    Make sure that these are unique, so remove all symbols
    and accessions that point to two HGNC IDs
    """
    logging.info("Parsing %s", fname)
    lines: list[str] = open_split(fname)
    headers: list[str] = lines[0].split("\t")
    assert headers[1] == "symbol"
    field_idx: dict[str, int] = dict([(h, i) for i, h in enumerate(headers)])

    sym_to_id: dict[str, str] = {}
    alt_sym_to_id: dict[str, str] = {}
    remove_syms: set[str] = set()

    acc_to_sym: dict[str, dict[str, str]] = {}
    for acc_type in acc_types:
        acc_to_sym[acc_type] = {}
    rem_accs: defaultdict[str, set[str]] = defaultdict(set)

    for l in lines:
        row: list[str] = l.split("\t")
        row = [x.strip('"') for x in row]

        gene_id: str = row[0]
        main_sym: str = row[1]

        for acc_type in acc_types:
            idx: int = field_idx[acc_type]
            acc: str = row[idx]
            if acc == "":
                continue
            acc_dict: dict[str, str] = acc_to_sym[acc_type]

            accs: list[str] = acc.split("|")
            for acc in accs:
                if acc in acc_dict:
                    rem_accs[acc_type].add(acc)
                acc_dict[acc] = gene_id

        sym_to_id[main_sym] = gene_id

        alias_list: set[str] = get_syms(
            row, field_idx, ["alias_symbol", "prev_symbol", "prev_name"]
        )

        for al_sym in alias_list:
            if al_sym in alt_sym_to_id:
                remove_syms.add(al_sym)
            else:
                alt_sym_to_id[al_sym] = gene_id

    logging.info("%d alt symbols are non-unique and cannot be used", len(remove_syms))
    logging.debug(
        "The following alt symbols are non-unique and cannot be used: %s", remove_syms
    )
    assert "ATP6C" in alt_sym_to_id
    for rs in remove_syms:
        del alt_sym_to_id[rs]

    alts_are_mains: set[str] = set(alt_sym_to_id).intersection(sym_to_id)
    logging.info(
        "%d alt symbols are identical to main symbols and are used as mains only",
        len(alts_are_mains),
    )
    logging.debug(
        (
            "The following alt symbols are identical to main symbols "
            "and cannot be used as alts anymore: %s"
        ),
        alts_are_mains,
    )
    for rs in alts_are_mains:
        del alt_sym_to_id[rs]

    sym_to_id.update(alt_sym_to_id)

    new_acc_to_sym: dict[str, dict[str, str]] = {}
    for acc_type in acc_types:
        del_accs: set[str] = rem_accs[acc_type]
        logging.info("Removing %d non-unique %s-accessions", len(del_accs), acc_type)
        logging.debug("Removing %s-accessions: %s", acc_type, repr(del_accs))
        new_accs: dict[str, str] = acc_to_sym[acc_type].copy()
        for acc in del_accs:
            del new_accs[acc]
        new_acc_to_sym[acc_type.split("_", maxsplit=1)[0]] = new_accs

    logging.info(
        "HGNC symbols: %d genes / main symbols, %d alternate unique symbols",
        len(sym_to_id),
        len(alt_sym_to_id),
    )
    for acc_type, acc_dict in new_acc_to_sym.items():
        logging.info("HGNC %s: %d accessions", acc_type, len(acc_dict))

    assert "ENSG00000204446" in new_acc_to_sym["ensembl"]
    return sym_to_id, new_acc_to_sym


def find_solid_syms(syms: list[str]) -> list[str]:
    "remove the weird symbols and return new list"
    solid_syms: list[str] = []
    for sym in syms:
        if not "orf" in sym and not "." in sym:
            solid_syms.append(sym)

    return solid_syms


def parse_map_fields(
    map_fields: str | None,
    name_to_idx: dict[str, int],
    acc_to_id: dict[str, dict[str, str]],
    in_field_idx: int,
) -> list[tuple[int, str]]:
    "given a string with fieldName=accType,fieldName2=accType, etc, return a list of (fieldIdx,id)"
    map_strategy: list[tuple[int, str]] = []
    if map_fields is None:
        for name, index in name_to_idx.items():
            if index == in_field_idx:
                map_fields = name + "=sym"
                break

    assert map_fields is not None

    fields = map_fields.split(",")
    for field_acc_type in fields:
        field, acc_type = field_acc_type.split("=")
        if field not in name_to_idx:
            logging.error("%s is not a valid field name in the input file", field)
            sys.exit(1)
        if acc_type not in acc_to_id and acc_type != "sym":
            logging.error(
                "%s is not 'sym' or a valid accession type. Valid types are: %s",
                acc_type,
                repr(acc_type_names),
            )
            sys.exit(1)

        map_strategy.append((name_to_idx[field], acc_type))
    return map_strategy


def get_hgnc_id(
    row: list[str],
    map_strategy: list[tuple[int, str]],
    sym_to_id: dict[str, str],
    acc_to_id: dict[str, dict[str, str]],
) -> tuple[str | None, list[tuple[str, str, str]], list[str]]:
    "return hgnc ID given a row and a mapStrategy"
    tried_ids: list[tuple[str, str, str]] = []
    tried_syms: list[str] = []
    for field_idx, acc_type in map_strategy:
        acc = row[field_idx]
        if "," in acc or "|" in acc or ";" in acc:
            print(acc)
            print(f"found comma/pipe/semicolon in {acc_type} accession")
            assert False
        tried_ids.append(("field" + str(field_idx), acc_type, acc))
        if acc_type == "sym":
            tried_syms.append(acc)
            if acc in sym_to_id:
                return sym_to_id[acc], tried_ids, tried_syms
        else:
            acc_dict = acc_to_id[acc_type]
            if acc in acc_dict:
                return acc_dict[acc], tried_ids, tried_syms
    return None, tried_ids, tried_syms


def main() -> None:
    args = parse_args()

    hgnc_fname: str = args.hgnc_fname

    in_fname = args.in_fname
    out_fname = args.out_fname
    if args.mgi:
        sym_to_id = parse_mgi(args.mgi)
        acc_to_id = {}
    elif args.zfin:
        sym_to_id = parse_zfin(args.zfin)
        acc_to_id = {}
    else:
        sym_to_id, acc_to_id = parse_hgnc(hgnc_fname)
    out_field_idx = int(args.out_field)
    map_fields = args.map_fields

    ofh = open(out_fname, "w")

    line_count = 0
    dupl_count = 0
    not_found: list[list[tuple[str, str, str]]] = []
    not_found_syms: list[str] = []
    name_to_idx = None
    map_strategy: list[tuple[int, str]] | None = None
    for line in open(in_fname, encoding="utf8"):
        row = line.rstrip("\n\r").split("\t")
        if name_to_idx is None:
            headers = row
            logging.info(
                (
                    "Treating %s as the header line. "
                    "Fix file is this does not look like a header line!"
                ),
                row,
            )
            name_to_idx = dict([(h, i) for i, h in enumerate(headers)])
            map_strategy = parse_map_fields(
                map_fields, name_to_idx, acc_to_id, out_field_idx
            )
            if args.insert is not None:
                row.insert(out_field_idx, "hgnc_id")
            else:
                row[out_field_idx] = "hgnc_id"
        else:
            assert map_strategy is not None
            hgnc_id, tried_ids, tried_syms = get_hgnc_id(
                row, map_strategy, sym_to_id, acc_to_id
            )
            if hgnc_id is None:
                logging.debug("Not resolved: %s", line.rstrip())
                logging.debug("Tried accessions/symbols: %s", repr(tried_ids))
                not_found.append(tried_ids)
                not_found_syms.extend(tried_syms)
                continue
            else:
                if not args.insert:
                    row[out_field_idx] = hgnc_id
                else:
                    row.insert(out_field_idx, hgnc_id)

        if "|" in row[out_field_idx]:
            hgnc_ids = row[out_field_idx].split("|")
            for hid in hgnc_ids:
                row[out_field_idx] = hid
                ofh.write("\t".join(row))
                ofh.write("\n")
                line_count += 1
                dupl_count += 1
        else:
            ofh.write("\t".join(row))
            ofh.write("\n")
            line_count += 1

    if len(not_found) != 0:
        logging.info(
            "%d symbols not found: skipped %d lines as their symbol could not be resolved",
            len(set(not_found_syms)),
            len(not_found),
        )
        logging.debug(repr(not_found))
        if args.removed_fname:
            rmfh = open(args.removed_fname, "w")
            for s in not_found:
                rmfh.write(f"{s[0][-1]}\n")
            logging.info("Wrote missing genes to %s", args.removed_fname)

        if len(not_found_syms) != 0:
            solid_syms = set(find_solid_syms(not_found_syms))
            logging.info(
                "Of those, the following %d symbols are not BAC/Accession/Orf: %s",
                len(solid_syms),
                set(solid_syms),
            )

    if dupl_count != 0:
        logging.info(
            "%d lines in the input file had to be duplicated, as the gene mapping was 1:many",
            dupl_count,
        )


main()
