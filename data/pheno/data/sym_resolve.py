#!/usr/bin/env python3

import logging, sys, optparse, gzip
from collections import defaultdict
from os.path import join, basename, dirname, isfile

# ==== functions =====
    
def parseArgs():
    " setup logging, parse command line arguments and options. -h shows auto-generated help page "
    parser = optparse.OptionParser("""usage: %prog [options] -g hgncFile inputTsv outputTsv - convert human symbols to more stable HGNC identifiers.
    Recognizes outdated or deprecrated symbols and gene names. Input file must have a header line.
    By default, assumes that the first field is the symbol and converts that field to a HGNC:ID.

    Examplex:
       symResolve -g ../../hgnc_complete_set.txt brennan.tsv brennan.hgnc.tsv -m ensembl_id=ensembl -r brennan.dropped.txt 
       symResolve -m gene_id=ensembl schema.tsv schema.hgnc.tsv -r schema.dropped.tsv
       symResolve ../hgnc/hgnc_complete_set.txt sfari.tsv sfari.hgnc.tsv -f 1
    """)

    parser.add_option("-d", "--debug", dest="debug", action="store_true", help="show debug messages")
    parser.add_option("-f", "--outField", dest="outField", action="store", help="Write HGNC to this field, default is first field. A number, 0-based.", default="0")
    parser.add_option("-i", "--insert", dest="insert", action="store_true", help="Instead of replacing the value in field -f, insert a new column in front of it with the HGNC-ID")
    parser.add_option("-r", "--removed", dest="removedFname", action="store", help="Write genes that were removed to this file")
    parser.add_option("-m", "--mapFields", dest="mapFields", action="store", help="process this field from the input file, default is first field. If file has a header line, can be a comma-sep list of field names. Can have format <fieldName>=<idName>, with <idName> being one of the HGNC ID names, e.g. 'ensembl'."
        "For each column, you can specify the content of the field, e.g. ens=ensembl,uip=uniprot,symbol=sym", default=None)
    parser.add_option("-g", "--hgncInfo", dest="hgncFname", action="store", help="read hgnc_complete_set.txt from this file, default is %default. "
            "Grab one with wget https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt",
            default="/hive/data/outside/hgnc/current/hgnc_complete_set.txt")
    parser.add_option("", "--mgi", dest="mgi", action="store", help="To map mouse symbols. Read HGNC_AllianceHomology.rpt from this file. "
            "Get this file with wget https://www.informatics.jax.org/downloads/reports/HGNC_AllianceHomology.rpt. Use key 'mgiSym' in -m.")
            #default="/hive/data/outside/mgi/HGNC_AllianceHomology.rpt")
 
    parser.add_option("", "--zfin", dest="zfin", action="store", help="To map zebrafish symbols. Read human-orthos.tsv. "
            "Get this file with wget https://zfin.org/downloads/human_orthos.txt. Use key 'zfinSym' if using -m.")
            #default="/hive/data/outside/zfin/human_orthos.txt")
    #parser.add_option("-f", "--file", dest="file", action="store", help="run on file") 
    #parser.add_option("", "--test", dest="test", action="store_true", help="do something") 
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

def getSyms(row, indexMap, fieldNames):
    " return list of syms from row "
    syms = set()

    for fieldName in fieldNames:
        fieldIdx = indexMap[fieldName]
        aliasStr = row[fieldIdx]
        if aliasStr!="":
            aliasList = aliasStr.split("|")
            aliasList = [x.upper() for x in aliasList]
            for alSym in aliasList:
                syms.add(alSym)

    return syms

def addSyms(row, syms, fieldIdx):
    aliasStr = row[fieldIdx]
    if aliasStr!="":
        aliasList = aliasStr.split("|")
        aliasList = [x.upper() for x in aliasList]
        for alSym in aliasList:
            if alSym in syms:
                logging.error("sym %s is already in the list" % alSym)
                sys.exit(1)
            else:
                syms.append(alSym)

# ----------- main --------------
accTypes = ["ensembl_gene_id", "entrez_id", "uniprot_ids"]
accTypeNames = ["ensembl", "entrez", "uniprot"]

def parseZfin(fname):
    " parse zfin human_orthos.txt, return symbol -> HGNC-ID "
    # ZFIN has no headers!! The headers are on the website as:
    # ZFIN ID	ZFIN Symbol	ZFIN Name	Human Symbol	Human Name	OMIM ID	Gene ID	HGNC ID	Evidence	Pub ID 
    skipped = []
    logging.info("Parsing %s" % fname)
    lines = openSplit(fname)
    symToId = {}
    for l in lines:
        row = l.split("\t")
        sym = row[1]
        hgncId = row[7]
        if hgncId=="":
            skipped.append(sym)
        symToId[hgncId] = sym
    logging.info("No HGNC for these genes in zfin file: %s" % repr(skipped))
    return symToId

def parseMgi(fname):
    " parse MGI HGNC_AllianceHomology.rpt file, return symbol -> HGNC-ID "
    logging.info("Parsing %s" % fname)
    lines = openSplit(fname)
    headers = lines[0].split("\t")
    assert(headers[-1]=="HGNC ID")
    assert(headers[1]=="Marker Symbol")
    fieldIdx = dict([(h, i) for i, h in enumerate(headers)])
    symToId = {}
    hgncIdx = headers.index("HGNC ID")

    for l in lines[1:]:
        row = l.split("\t")
        row = [x.strip('"') for x in row]

        mainSym = row[1]
        geneId = row[hgncIdx]

        if geneId=="null":
            continue

        assert(mainSym not in symToId)
        symToId[mainSym] = geneId

    return symToId

def openSplit(fname):
    if fname.endswith(".gz"):
        fh = gzip.open(fname, "rt")
    else:
        fh = open(fname)
    lines = fh.read().splitlines()
    return lines

def parseHgnc(fname):
    """ parse HGNC return two dictionaries with symbol -> HGNC ID and another dict with accession -> HGNC ID.
    Make sure that these are unique, so remove all symbols and accessions that point to two HGNC IDs
    """
    logging.info("Parsing %s" % fname)
    lines = openSplit(fname)
    headers = lines[0].split("\t")
    assert(headers[1]=="symbol")
    fieldIdx = dict([(h, i) for i, h in enumerate(headers)])

    symToId = {}
    altSymToId = {}
    removeSyms = set()

    accToSym = {}
    for accType in accTypes:
        accToSym[accType] = {}
    remAccs = defaultdict(set)

    for l in lines:
        row = l.split("\t")
        row = [x.strip('"') for x in row]

        geneId = row[0]
        mainSym = row[1]

        # grab all the accessions
        for accType in accTypes:
            idx = fieldIdx[accType]
            acc = row[idx]
            #print(accType, acc, geneId)
            if acc=="":
                continue
            accDict = accToSym[accType]

            accs = acc.split("|")
            for acc in accs:
                if acc in accDict:
                    remAccs[accType].add(acc)
                accDict[acc] = geneId

        # ... the main symbol
        symToId[mainSym] = geneId

        aliasList = getSyms(row, fieldIdx, ["alias_symbol", "prev_symbol", "prev_name"])

        # and the alternate symbols
        for alSym in aliasList:
            if alSym in altSymToId:
                removeSyms.add(alSym)
            else:
                altSymToId[alSym] = geneId

    logging.info("%d alt symbols are non-unique and cannot be used" % len(removeSyms))
    logging.debug("The following alt symbols are non-unique and cannot be used: %s" % repr(removeSyms))
    assert("ATP6C" in altSymToId)
    for rs in removeSyms:
        del altSymToId[rs]

    altsAreMains = set(altSymToId).intersection(symToId)
    logging.info("%d alt symbols are identical to main symbols and are used as mains only" % len(altsAreMains))
    logging.debug("The following alt symbols are identical to main symbols and cannot be used as alts anymore: %s" % repr(altsAreMains))
    for rs in altsAreMains:
        del altSymToId[rs]

    # now merge the alternates into the main symbols
    symToId.update(altSymToId)

    newAccToSym = {}
    for accType in accTypes:
        delAccs = remAccs[accType]
        logging.info("Removing %d non-unique %s-accessions" % (len(delAccs), accType))
        logging.debug("Removing %s-accessions: %s" % (accType, repr(delAccs)))
        newAccs = accToSym[accType].copy()
        for acc in delAccs:
            del newAccs[acc]
        newAccToSym[accType.split("_")[0]] = newAccs

    logging.info("HGNC symbols: %d genes / main symbols, %d alternate unique symbols" % (len(symToId), len(altSymToId)))
    for accType, accDict in newAccToSym.items():
        logging.info("HGNC %s: %d accessions" % (accType, len(accDict)))

    assert("ENSG00000204446" in newAccToSym["ensembl"])
    return symToId, newAccToSym

def findSolidSyms(syms):
    " remove the weird symbols and return new list "
    solidSyms = []
    for sym in syms:
        if not "orf" in sym and not "." in sym:
            solidSyms.append(sym)

    return solidSyms

def parseMapFields(mapFields, nameToIdx, accToId, inFieldIdx):
    " given a string with fieldName=accType,fieldName2=accType, etc, return a list of (fieldIdx,id) "
    mapStrategy = []
    if mapFields is None:
        for name, index in nameToIdx.items():
            if index==inFieldIdx:
                mapFields = name+"=sym"
                break

    fields = mapFields.split(",")
    for fieldAccType in fields:
        field, accType = fieldAccType.split("=")
        if field not in nameToIdx:
            logging.error("%s is not a valid field name in the input file" % field)
            sys.exit(1)
        if accType not in accToId and accType!="sym":
            logging.error("%s is not 'sym' or a valid accession type. Valid types are: %s" % (accType, repr(accTypeNames)))
            sys.exit(1)

        mapStrategy.append((nameToIdx[field], accType))
    return mapStrategy

def getHgncId(row, mapStrategy, symToId, accToId):
    " return hgnc ID given a row and a mapStrategy "
    triedIds = []
    triedSyms = []
    for fieldIdx, accType in mapStrategy:
        acc = row[fieldIdx]
        if "," in acc or "|" in acc or ";" in acc:
            print(acc)
            print("found comma/pipe/semicolon in %s accession" % accType)
            assert(False)
        triedIds.append(("field"+str(fieldIdx),accType,acc))
        if accType=="sym":
            triedSyms.append(acc)
            if acc in symToId:
                return symToId[acc], triedIds, triedSyms
        else:
            accDict = accToId[accType]
            if acc in accDict:
                return accDict[acc], triedIds, triedSyms
    return None, triedIds, triedSyms

def main():
    args, options = parseArgs()

    hgncFname = options.hgncFname

    inFname = args[0]
    outFname = args[1]
    if options.mgi:
        symToId = parseMgi(options.mgi)
        accToId = {}
    elif options.zfin:
        symToId = parseZfin(options.zfin)
        accToId = {}
    else:
        symToId, accToId = parseHgnc(hgncFname)
    outFieldIdx = int(options.outField)
    mapFields = options.mapFields

    ofh = open(outFname, "w")

    lineCount = 0
    duplCount = 0
    notFound = []
    notFoundSyms = []
    nameToIdx = None
    for line in open(inFname, encoding="utf8"):
        row = line.rstrip("\n\r").split("\t")
        if nameToIdx is None:
            # header line in input file
            headers = row
            logging.info("Treating %s as the header line. Fix file is this does not look like a header line!" % row)
            nameToIdx = dict([(h, i) for i, h in enumerate(headers)])
            mapStrategy = parseMapFields(mapFields, nameToIdx, accToId, outFieldIdx)
            if options.insert is not None:
                row.insert(outFieldIdx, "hgnc_id")
            else:
                row[outFieldIdx] = "hgnc_id"
        else:
            hgncId, triedIds, triedSyms = getHgncId(row, mapStrategy, symToId, accToId)
            if hgncId is None:
                logging.debug("Not resolved: %s" % line.rstrip())
                logging.debug("Tried accessions/symbols: %s" % repr(triedIds))
                notFound.append(triedIds)
                notFoundSyms.extend(triedSyms)
                continue
            else:
                if not options.insert:
                    row[outFieldIdx] = hgncId
                else:
                    row.insert(outFieldIdx, hgncId)

        # duplicate the few rows with multiple HGNC IDs
        if "|" in row[outFieldIdx]:
            hgncIds = row[outFieldIdx].split("|")
            for hid in hgncIds:
                row[outFieldIdx] = hid
                ofh.write("\t".join(row))
                ofh.write("\n")
                lineCount+=1
                duplCount +=1
        else:
            ofh.write("\t".join(row))
            ofh.write("\n")
            lineCount+=1

    if len(notFound)!=0:
        logging.info("%d symbols not found: skipped %d lines as their symbol could not be resolved" % (len(set(notFoundSyms)), len(notFound)))
        logging.debug(repr(notFound))
        if options.removedFname:
            rmfh = open(options.removedFname, "w")
            for s in notFound:
                rmfh.write("%s\n" % s[0][-1])
            logging.info("Wrote missing genes to %s" % options.removedFname)

        if len(notFoundSyms)!=0:
            solidSyms = set(findSolidSyms(notFoundSyms))
            logging.info("Of those, the following %d symbols are not BAC/Accession/Orf: %s" % (len(solidSyms), set(solidSyms)))

    if duplCount !=0:
        logging.info("%d lines in the input file had to be duplicated, as the gene mapping was 1:many" % duplCount)

main()
