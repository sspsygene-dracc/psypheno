#!/usr/bin/env python3

import logging
import sys
import os
from collections import Counter
import sqlite3
from typing import Optional
from os.path import dirname, join
from os.path import normpath
import argparse


def parse_args() -> argparse.Namespace:
    "setup logging, parse command line arguments and options. -h shows auto-generated help page"
    parser = argparse.ArgumentParser(
        """usage: %prog [options] dbFname tabSepFname - load a tab-file file into a database.
            
    Examples:
    wget https://ftp.ebi.ac.uk/pub/databases/genenames/hgnc/tsv/hgnc_complete_set.txt
    sqLoad genes.db hgnc_complete_set.txt -t hgnc -f hgnc_id,symbol,name,locus_group,alias_symbol,
    alias_name,prev_symbol,prev_name,gene_group,entrez_id,ensembl_gene_id,refseq_accession,
    uniprot_ids,mgd_id,cosmic,omim_id,orphanet,mane_select,gencc
    sqLoad genes.db  sfari.hgnc.tsv -f hgnc_id,genetic_category,gene_score,syndromic,
    eagle,number_of_reports --int gene_score,eagle,number_of_reports

    Field names cannot contain . or - and other special chars, 
    so these are "cleaned" (usually: replaced with '_')
    Use the clean field names in the options below."""
    )

    parser.add_argument(
        "-d", "--debug", dest="debug", action="store_true", help="show debug messages"
    )
    parser.add_argument(
        "-f",
        "--use-fields",
        action="store",
        help=(
            "subset of fields to load, comma-separated list, "
            "can be in format oldName=newName if fields should be renamed. "
            "By default all fields will be loaded."
        ),
    )
    parser.add_argument(
        "-i",
        "--index",
        dest="index",
        action="store",
        help="list of fields for which an index should be created, "
        "comma-separated list. By default only the first field is indexed.",
    )
    parser.add_argument(
        "-t",
        "--table",
        dest="table",
        action="store",
        help="name of table, default is basename of infile",
    )
    parser.add_argument(
        "--int-fields",
        action="store",
        help="comma-sep list of fields that are integers",
    )
    parser.add_argument(
        "--float-fields",
        action="store",
        help="comma-sep list of fields that are floats",
    )
    parser.add_argument(
        "--no-dupl",
        action="store_true",
        help="stop if first field is duplicated",
    )
    parser.add_argument("db_name", help="database file name")
    parser.add_argument("in_fname", help="input TSV file name")

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger().setLevel(logging.INFO)

    return args


def parse_tsv(fname: str) -> tuple[list[str], list[list[str]]]:
    "parse tsv in memory and return as headerNames, rows"
    ifh = open(fname, encoding="utf8")
    data = ifh.read()
    lines = data.split("\n")

    field_names: list[str] = lines[0].split("\t")
    field_names = [x.strip('"') for x in field_names]
    lines = lines[1:]

    rows: list[list[str]] = []
    for line in lines:
        if len(line) == 0:
            continue
        row = line.split("\t")
        row = [f.replace("\a", "\n").replace("\b", "\t").strip('"') for f in row]
        if len(row) != len(field_names):
            print(f"row {repr(row)} has different field count than header")
            print(f"Headers are: {repr(field_names)}")
            sys.exit(1)
        rows.append(row)

    return field_names, rows


def run_sql(conn: sqlite3.Connection, sql: str) -> None:
    "execute sql and commit, handle errors"
    try:
        logging.debug(sql)
        conn.execute(sql)
        conn.commit()
    except sqlite3.OperationalError as ex:
        print("SQL error")
        print(sql)
        print(repr(ex))
        sys.exit(1)


def check_dupl(rows: list[list[str]]) -> None:
    "stop if any row contains a duplicated value in the first field"
    counter: Counter[str] = Counter()
    for row in rows:
        field0: str = row[0]
        counter[field0] += 1
    dupl_rows: list[str] = []
    for val, count in counter.items():
        if count > 1:
            dupl_rows.append(val)
    if len(dupl_rows) > 0:
        logging.error("Duplicate gene IDs: %s", ", ".join(dupl_rows))
        assert False


def load_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[list[str]],
    load_fields: list[str],
    int_fields: list[str] | None,
    float_fields: list[str] | None,
    no_dupl: bool,
) -> None:
    "load rows into sqlite database using prepared statement and bulk load"
    sql = f"DROP TABLE IF EXISTS {table};"
    run_sql(conn, sql)
    print(f"Dropped table {table}")

    field_defs: list[str] = []
    for field in load_fields:
        field_type = "text"
        if int_fields and field in int_fields:
            field_type = "int"
        if float_fields and field in float_fields:
            field_type = "float"
        field_defs.append(" " + field + " " + field_type)
    field_str = ", ".join(field_defs)

    sql_parts = [f"CREATE TABLE {table} ({field_str})"]
    sql = "".join(sql_parts)

    run_sql(conn, sql)
    print(f"Created table {table} with: {sql}")

    if no_dupl:
        check_dupl(rows)

    print("Loading rows")
    quest_mark_str = ",".join(["?"] * len(load_fields))
    sql = f"INSERT INTO {table} VALUES ({quest_mark_str})"
    conn.executemany(sql, rows)
    print(f"Loaded {len(rows)} rows")
    conn.commit()


def clean_field_names(fields: list[str]) -> list[str]:
    "remove chars that are not valid in sql field names"
    new_fields: list[str] = []
    for f in fields:
        f = f.replace(".", "_")
        f = f.replace("-", "_")
        new_fields.append(f)
    return new_fields


def open_sqlite(db_name: str) -> sqlite3.Connection:
    "set super fast sqlite options"
    conn = sqlite3.connect(db_name)
    conn.execute("PRAGMA journal_mode = OFF;")
    conn.execute("PRAGMA synchronous = 0;")
    conn.execute("PRAGMA cache_size = 10000000;")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


def create_indexes(conn: sqlite3.Connection, table: str, idx_fields: list[str]) -> None:
    """create the SQLite indexes.
    Always must make them at the end, otherwise the db file will be fragmented"""
    logging.debug("Fields to index %s", repr(idx_fields))
    for field in idx_fields:
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        run_sql(conn, sql)


def filter_rows(
    fields: list[str],
    rows: list[list[str]],
    use_fields: list[str] | None,
) -> tuple[list[str], list[list[str]]]:
    "only keep useFields of the rows. 'fields' is a comma-sep string."
    if use_fields is None:
        use_fields = fields

    field_idx_list: list[int] = []
    new_names: list[str] = []
    for field_name in use_fields:
        if "=" in field_name:
            parts = field_name.split("=")
            assert len(parts) == 2
            field_name = parts[0]
            new_name = parts[1]
        else:
            new_name = field_name

        new_names.append(new_name)

        try:
            idx = fields.index(field_name)
        except ValueError as e:
            raise ValueError(
                f"Error: field {field_name} not in input file. Possible fields are: {fields}",
            ) from e

        field_idx_list.append(idx)

    new_rows: list[list[str]] = []
    for row in rows:
        new_row: list[str] = [row[x] for x in field_idx_list]
        new_rows.append(new_row)

    fields[0] = fields[0].strip("#")
    new_names[0] = new_names[0].strip("#")

    print(f"Using these fields from input file: {', '.join(fields)}")
    print(f"Field names in SQL are: {', '.join(new_names)}")
    return new_names, new_rows


def maybe_comma_sep(s: str | None) -> list[str] | None:
    if s is None:
        return None
    s_list = s.split(",")
    s_list = [s.strip() for s in s_list]
    return s_list


def parse_conf(fname: str) -> dict[str, str]:
    "parse a hg.conf style file, return as dict key -> value (all strings)"
    logging.debug("Parsing %s", fname)
    conf: dict[str, str] = {}
    for line in open(fname, encoding="utf8"):
        line = line.strip()
        if line.startswith("#"):
            continue
        elif line.startswith("include "):
            incl_fname = line.split()[1]
            abs_fname = normpath(join(dirname(fname), incl_fname))
            if os.path.isfile(abs_fname):
                incl_dict = parse_conf(abs_fname)
                conf.update(incl_dict)
        elif "=" in line:
            key, value = line.split("=", 1)
            conf[key] = value
    return conf


def main() -> None:
    args = parse_args()

    table = args.table

    use_fields = maybe_comma_sep(args.use_fields)
    index_fields = maybe_comma_sep(args.index)
    int_fields = maybe_comma_sep(args.int_fields)
    float_fields = maybe_comma_sep(args.float_fields)
    no_dupl = args.no_dupl

    db_name = args.db_name
    in_fname = args.in_fname
    field_names, rows = parse_tsv(in_fname)
    field_names = clean_field_names(field_names)
    conn = open_sqlite(db_name)

    if table is None:
        table = os.path.basename(in_fname).split(".")[0]

    print(f"db={db_name}")
    print(f"table={table}")

    use_fields, rows = filter_rows(field_names, rows, use_fields)

    load_rows(conn, table, rows, use_fields, int_fields, float_fields, no_dupl)

    if index_fields is None:
        index_fields = [use_fields[0]]

    create_indexes(conn, table, index_fields)

    conn.execute("PRAGMA analysis_limit=1000;")
    conn.execute("PRAGMA optimize;")
    conn.close()


main()
