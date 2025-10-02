#!/usr/bin/env python3

import logging, sys, optparse
import sqlite3, os
from collections import defaultdict, Counter
from os.path import join, basename, dirname, isfile

# ==== functions =====
    
def parseArgs():
    " setup logging, parse command line arguments and options. -h shows auto-generated help page "
    parser = optparse.OptionParser("""usage: %prog [options] dbFname tabSepFname - load a tab-file file into a database.
            
    Examples:
    wget https://ftp.ebi.ac.uk/pub/databases/genenames/hgnc/tsv/hgnc_complete_set.txt
    sqLoad genes.db hgnc_complete_set.txt -t hgnc -f hgnc_id,symbol,name,locus_group,alias_symbol,alias_name,prev_symbol,prev_name,gene_group,entrez_id,ensembl_gene_id,refseq_accession,uniprot_ids,mgd_id,cosmic,omim_id,orphanet,mane_select,gencc
    sqLoad genes.db  sfari.hgnc.tsv -f hgnc_id,genetic_category,gene_score,syndromic,eagle,number_of_reports --int gene_score,eagle,number_of_reports

    Field names cannot contain . or - and other special chars, so these are "cleaned" (usually: replaced with '_')
    Use the clean field names in the options below.""")

    parser.add_option("-d", "--debug", dest="debug", action="store_true", help="show debug messages")
    parser.add_option("-f", "--useFields", dest="useFields", action="store", help="subset of fields to load, comma-separated list, can be in format oldName=newName if fields should be renamed. By default all fields will be loaded.")
    parser.add_option("-i", "--index", dest="index", action="store", help="list of fields for which an index should be created, comma-separated list. By default only the first field is indexed.")
    parser.add_option("-t", "--table", dest="table", action="store", help="name of table, default is basename of infile")
    parser.add_option("", "--int", dest="intFields", action="store", help="comma-sep list of fields that are integers")
    parser.add_option("", "--float", dest="floatFields", action="store", help="comma-sep list of fields that are floats")
    parser.add_option("", "--noDupl", dest="noDupl", action="store_true", help="stop if first field is duplicated")
    #parser.add_option("", "--defaults", dest="defaults", action="store", help="comma-sep list of fieldName=value.")
    (options, args) = parser.parse_args()

    if args==[]:
        parser.print_help()
        exit(1)

    if options.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
        logging.getLogger().setLevel(logging.INFO)

    return args, options

def parseTsv(fname):
    " parse tsv in memory and return as headerNames, rows "
    ifh = open(fname, encoding="utf8")
    #data = gzip.GzipFile(fileobj=data).read()
    #data = data.replace("\\\n", "\a") # translate escaped mysql newline to \a
    #data = data.replace("\\\t", "\b") # translate escaped mysql tab to \b
    data = ifh.read()
    lines = data.split("\n")

    fieldNames = lines[0].split("\t")
    fieldNames = [x.strip('"') for x in fieldNames]
    lines = lines[1:]

    # convert tab-sep lines to namedtuples (=objects)
    rows = []
    for line in lines:
        if len(line)==0:
            continue
        row = line.split("\t")
        row = [f.replace("\a", "\n").replace("\b", "\t").strip('"') for f in row]
        if len(row)!=len(fieldNames):
            print("row %s has different field count than header" % repr(row))
            print("Headers are: %s" % repr(fieldNames))
            sys.exit(1)
        rows.append(row)

    return fieldNames, rows

def runSql(conn, sql):
    " execute sql and commit, handle errors "
    try:
        logging.debug(sql)
        conn.execute(sql)
        conn.commit()
    except sqlite3.OperationalError as ex:
        print("SQL error")
        print(sql)
        print(repr(ex))
        sys.exit(1)

def checkDupl(rows):
    "stop if any row contains a duplicated value in the first field "
    counter = Counter()
    for row in rows:
        field0 = row[0]
        counter[field0] += 1
    duplRows = []
    for val, count in counter.items():
        if count>1:
            duplRows.append(val)
    if len(duplRows)>0:
        logging.error("Duplicate gene IDs: %s" % ", ".join(duplRows))
        assert(False)

def loadRows(conn, table, fields, rows, loadFields, intFields, floatFields, noDupl):
    " load rows into sqlite database using prepared statement and bulk load "
    sql = "DROP TABLE IF EXISTS %s;" % table
    runSql(conn, sql)
    print("Dropped table %s" % table)

    fieldDefs = []
    for field in loadFields:
        fieldType = "text"
        if intFields and field in intFields:
            fieldType = "int"
        if floatFields and field in floatFields:
            fieldType = "float"
        fieldDefs.append(" "+field+" "+fieldType)
    fieldStr = ", ".join(fieldDefs)

    sqlParts = ["CREATE TABLE %s (" % table, fieldStr, ")"]
    sql = "".join(sqlParts)

    runSql(conn, sql)
    print("Created table %s with: %s" % (table, sql))

    if noDupl:
        checkDupl(rows)
    
    print("Loading rows")
    questMarkStr = ",".join(["?"]*len(loadFields))
    sql = 'INSERT INTO %s VALUES (%s)' % (table, questMarkStr)
    conn.executemany(sql, rows)
    print("Loaded %d rows" % len(rows))
    conn.commit()

def cleanFieldNames(fields):
    " remove chars that are not valid in sql field names "
    newFields = []
    for f in fields:
        f = f.replace(".", "_")
        f = f.replace("-", "_")
        newFields.append(f)
    return newFields

def openMysql(dbName):
    " open connection to mysql db " 
    import pymysql
    user = cfgOption("db.user")
    password = cfgOption("db.password")
    host = cfgOption("db.host")
    conn = pymysql.connect(host=host, user=user, password=password, database="pheno")
    return conn

def openDb(dbName):
    " open connect to db "
    if dbName.endswith(".db"):
        return openSqlite(dbName)
    else:
        return openMysql(dbName)

def openSqlite(dbName):
    " set super fast sqlite options "
    #conn.set_trace_callback(print) # for debugging: print all sql statements
    conn = sqlite3.connect(dbName)
    conn.execute("PRAGMA journal_mode = OFF;")
    conn.execute("PRAGMA synchronous = 0;")
    conn.execute("PRAGMA cache_size = 10000000;")
    conn.execute("PRAGMA locking_mode = EXCLUSIVE;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    return conn

def createIndexes(conn, table, idxFields):
    " create the SQLite indexes. Always must make them at the end, otherwise the db file will be fragmented "
    logging.debug("Fields to index "+ repr(idxFields))
    for field in idxFields:
        print("Creating index for "+field)
        sql = "CREATE INDEX %s_%s_idx ON %s (%s)" % (table, field, table, field)
        runSql(conn, sql)

def filterRows(fields, rows, useFields):
    " only keep useFields of the rows. 'fields' is a comma-sep string. "
    doClean = False
    # if we use the raw input fields, make sure to remove the non-sql characters below
    if useFields is None:
        useFields = fields
        doClean = True

    fieldIdxList = []
    newNames = []
    for fieldName in useFields:
        if "=" in fieldName:
            parts = fieldName.split("=")
            assert(len(parts)==2)
            fieldName = parts[0]
            newName = parts[1]
        else:
            newName = fieldName

        newNames.append(newName)

        try:
            idx = fields.index(fieldName)
        except:
            print("Error: field %s not in input file. Possible fields are: %s" % (repr(fieldName), repr(fields)))
            sys.exit(1)

        fieldIdxList.append(idx)

    newRows = []
    for row in rows:
        newRow = [row[x] for x in fieldIdxList]
        newRows.append(newRow)

    #if doClean:
        #newNames = cleanFieldNames(newNames)

    fields[0] = fields[0].strip("#")
    newNames[0] = newNames[0].strip("#")

    print("Using these fields from input file: %s" % ", ".join(fields))
    print("Field names in SQL are: %s" % ", ".join(newNames))
    return newNames, newRows

def maybeCommaSep(s):
    if s is not None:
        s = s.split(",")
        s = [s.strip() for s in s]

    return s

def parseConf(fname):
    " parse a hg.conf style file, return as dict key -> value (all strings) "
    logging.debug("Parsing "+fname)
    conf = {}
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
        elif "=" in line: # string search for "="
            key, value = line.split("=",1)
            conf[key] = value
    return conf

# cache of hg.conf contents
hgConf = None

def parseHgConf():
    """ return hg.conf as dict key:value. """
    global hgConf
    if hgConf is not None:
        return hgConf

    hgConf = dict() # python dict = hash table

    fname = os.path.expanduser("~/.hubtools.conf")
    if isfile(fname):
        hgConf = parseConf(fname)
    else:
        fname = os.path.expanduser("~/.hg.conf")
        if isfile(fname):
            hgConf = parseConf(fname)

def cfgOption(name, default=None):
    " return hg.conf option or default "
    global hgConf

    if not hgConf:
        parseHgConf()

    return hgConf.get(name, default)

# ----------- main --------------
def main():
    args, options = parseArgs()

    table = options.table

    useFields = maybeCommaSep(options.useFields)
    indexFields = maybeCommaSep(options.index)
    intFields = maybeCommaSep(options.intFields)
    floatFields = maybeCommaSep(options.floatFields)
    noDupl = options.noDupl

    dbName, inFname = args
    fieldNames, rows = parseTsv(inFname)
    fieldNames = cleanFieldNames(fieldNames)
    conn = openDb(dbName)

    if table is None:
        table = os.path.basename(inFname).split('.')[0]

    print("db=%s" % dbName)
    print("table=%s" % table)

    useFields, rows = filterRows(fieldNames, rows, useFields)

    loadRows(conn, table, fieldNames, rows, useFields, intFields, floatFields, noDupl)

    if indexFields is None:
        indexFields = [useFields[0]] # index only first field by default

    createIndexes(conn, table, indexFields)

    conn.execute("PRAGMA analysis_limit=1000;")
    conn.execute("PRAGMA optimize;")
    conn.close()

main()
