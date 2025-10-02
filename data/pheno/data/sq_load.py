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


def parseArgs() -> argparse.Namespace:
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
        "--useFields",
        dest="useFields",
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
        "",
        "--int",
        dest="intFields",
        action="store",
        help="comma-sep list of fields that are integers",
    )
    parser.add_argument(
        "",
        "--float",
        dest="floatFields",
        action="store",
        help="comma-sep list of fields that are floats",
    )
    parser.add_argument(
        "",
        "--noDupl",
        dest="noDupl",
        action="store_true",
        help="stop if first field is duplicated",
    )
    args = parser.parse_args()

    if args == []:
        parser.print_help()
        exit(1)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger().setLevel(logging.INFO)

    return args


def parseTsv(fname: str) -> tuple[list[str], list[list[str]]]:
    "parse tsv in memory and return as headerNames, rows"
    ifh = open(fname, encoding="utf8")
    # data = gzip.GzipFile(fileobj=data).read()
    # data = data.replace("\\\n", "\a") # translate escaped mysql newline to \a
    # data = data.replace("\\\t", "\b") # translate escaped mysql tab to \b
    data = ifh.read()
    lines = data.split("\n")

    fieldNames: list[str] = lines[0].split("\t")
    fieldNames = [x.strip('"') for x in fieldNames]
    lines = lines[1:]

    # convert tab-sep lines to namedtuples (=objects)
    rows: list[list[str]] = []
    for line in lines:
        if len(line) == 0:
            continue
        row = line.split("\t")
        row = [f.replace("\a", "\n").replace("\b", "\t").strip('"') for f in row]
        if len(row) != len(fieldNames):
            print(f"row {repr(row)} has different field count than header")
            print(f"Headers are: {repr(fieldNames)}")
            sys.exit(1)
        rows.append(row)

    return fieldNames, rows


def runSql(conn: sqlite3.Connection, sql: str) -> None:
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


def checkDupl(rows: list[list[str]]) -> None:
    "stop if any row contains a duplicated value in the first field"
    counter: Counter[str] = Counter()
    for row in rows:
        field0: str = row[0]
        counter[field0] += 1
    duplRows: list[str] = []
    for val, count in counter.items():
        if count > 1:
            duplRows.append(val)
    if len(duplRows) > 0:
        logging.error("Duplicate gene IDs: %s", ", ".join(duplRows))
        assert False


def loadRows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[list[str]],
    loadFields: list[str],
    intFields: Optional[list[str]],
    floatFields: Optional[list[str]],
    noDupl: bool,
) -> None:
    "load rows into sqlite database using prepared statement and bulk load"
    sql = f"DROP TABLE IF EXISTS {table};"
    runSql(conn, sql)
    print(f"Dropped table {table}")

    fieldDefs: list[str] = []
    for field in loadFields:
        fieldType = "text"
        if intFields and field in intFields:
            fieldType = "int"
        if floatFields and field in floatFields:
            fieldType = "float"
        fieldDefs.append(" " + field + " " + fieldType)
    fieldStr = ", ".join(fieldDefs)

    sqlParts = [f"CREATE TABLE {table} ({fieldStr})"]
    sql = "".join(sqlParts)

    runSql(conn, sql)
    print(f"Created table {table} with: {sql}")

    if noDupl:
        checkDupl(rows)

    print("Loading rows")
    questMarkStr = ",".join(["?"] * len(loadFields))
    sql = f"INSERT INTO {table} VALUES {questMarkStr}"
    conn.executemany(sql, rows)
    print(f"Loaded {len(rows)} rows")
    conn.commit()


def cleanFieldNames(fields: list[str]) -> list[str]:
    "remove chars that are not valid in sql field names"
    newFields: list[str] = []
    for f in fields:
        f = f.replace(".", "_")
        f = f.replace("-", "_")
        newFields.append(f)
    return newFields


def openSqlite(dbName: str) -> sqlite3.Connection:
    "set super fast sqlite options"
    # conn.set_trace_callback(print) # for debugging: print all sql statements
    conn = sqlite3.connect(dbName)
    conn.execute("PRAGMA journal_mode = OFF;")
    conn.execute("PRAGMA synchronous = 0;")
    conn.execute("PRAGMA cache_size = 10000000;")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn


def createIndexes(conn: sqlite3.Connection, table: str, idxFields: list[str]) -> None:
    """create the SQLite indexes.
    Always must make them at the end, otherwise the db file will be fragmented"""
    logging.debug("Fields to index %s", repr(idxFields))
    for field in idxFields:
        print(f"Creating index for {field}")
        sql = f"CREATE INDEX {table}_{field}_idx ON {table} ({field})"
        runSql(conn, sql)


def filterRows(
    fields: list[str],
    rows: list[list[str]],
    useFields: Optional[list[str]],
) -> tuple[list[str], list[list[str]]]:
    "only keep useFields of the rows. 'fields' is a comma-sep string."
    # if we use the raw input fields, make sure to remove the non-sql characters below
    if useFields is None:
        useFields = fields

    fieldIdxList: list[int] = []
    newNames: list[str] = []
    for fieldName in useFields:
        if "=" in fieldName:
            parts = fieldName.split("=")
            assert len(parts) == 2
            fieldName = parts[0]
            newName = parts[1]
        else:
            newName = fieldName

        newNames.append(newName)

        try:
            idx = fields.index(fieldName)
        except ValueError as e:
            raise ValueError(
                f"Error: field {fieldName} not in input file. Possible fields are: {fields}",
            ) from e

        fieldIdxList.append(idx)

    newRows: list[list[str]] = []
    for row in rows:
        newRow: list[str] = [row[x] for x in fieldIdxList]
        newRows.append(newRow)

    fields[0] = fields[0].strip("#")
    newNames[0] = newNames[0].strip("#")

    print(f"Using these fields from input file: {', '.join(fields)}")
    print(f"Field names in SQL are: {', '.join(newNames)}")
    return newNames, newRows


def maybeCommaSep(s: str | None) -> list[str] | None:
    if s is None:
        return None
    s_list = s.split(",")
    s_list = [s.strip() for s in s_list]
    return s_list


def parseConf(fname: str) -> dict[str, str]:
    "parse a hg.conf style file, return as dict key -> value (all strings)"
    logging.debug("Parsing %s", fname)
    conf: dict[str, str] = {}
    for line in open(fname):
        line = line.strip()
        if line.startswith("#"):
            continue
        elif line.startswith("include "):
            inclFname = line.split()[1]
            absFname = normpath(join(dirname(fname), inclFname))
            if os.path.isfile(absFname):
                inclDict = parseConf(absFname)
                conf.update(inclDict)
        elif "=" in line:  # string search for "="
            key, value = line.split("=", 1)
            conf[key] = value
    return conf


def main() -> None:
    args = parseArgs()

    table = args.table

    useFields = maybeCommaSep(args.useFields)
    indexFields = maybeCommaSep(args.index)
    intFields = maybeCommaSep(args.intFields)
    floatFields = maybeCommaSep(args.floatFields)
    noDupl = args.noDupl

    dbName = args.dbName
    inFname = args.inFname
    fieldNames, rows = parseTsv(inFname)
    fieldNames = cleanFieldNames(fieldNames)
    conn = openSqlite(dbName)

    if table is None:
        table = os.path.basename(inFname).split(".")[0]

    print(f"db={dbName}")
    print(f"table={table}")

    useFields, rows = filterRows(fieldNames, rows, useFields)

    loadRows(conn, table, rows, useFields, intFields, floatFields, noDupl)

    if indexFields is None:
        indexFields = [useFields[0]]  # index only first field by default

    createIndexes(conn, table, indexFields)

    conn.execute("PRAGMA analysis_limit=1000;")
    conn.execute("PRAGMA optimize;")
    conn.close()


main()
