import Head from "next/head";
import Link from "next/link";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

/* Reusable inline styles — same look as /methods. */
const sectionStyle: React.CSSProperties = {
  marginBottom: 32,
  borderLeft: "3px solid #d1d5db",
  paddingLeft: 20,
};

const h2Style: React.CSSProperties = {
  fontSize: 20,
  fontWeight: 700,
  color: "#1f2937",
  marginBottom: 12,
};

const codeStyle: React.CSSProperties = {
  fontFamily: "monospace",
  fontSize: "0.88em",
  background: "#f3f4f6",
  borderRadius: 3,
  padding: "1px 5px",
};

const preStyle: React.CSSProperties = {
  background: "#1f2937",
  color: "#e5e7eb",
  borderRadius: 6,
  padding: "12px 16px",
  overflowX: "auto",
  fontFamily: "monospace",
  fontSize: 13,
  lineHeight: 1.55,
  margin: "10px 0",
};

const noteStyle: React.CSSProperties = {
  background: "#f9fafb",
  border: "1px solid #e5e7eb",
  borderRadius: 6,
  padding: "10px 14px",
  margin: "10px 0",
  fontSize: 14,
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 14,
};

const thStyle: React.CSSProperties = {
  padding: "8px 10px",
  textAlign: "left",
  borderBottom: "2px solid #d1d5db",
};

const tdStyle: React.CSSProperties = {
  padding: "6px 10px",
  borderBottom: "1px solid #e5e7eb",
  verticalAlign: "top",
};

export default function GeneParserPage() {
  return (
    <>
      <Head>
        <title>Gene-symbol parser — SSPsyGene</title>
      </Head>
      <Header />
      <main
        style={{
          maxWidth: 800,
          margin: "0 auto",
          padding: "24px 16px",
          color: "#1f2937",
          fontSize: 15,
          lineHeight: 1.7,
        }}
      >
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 4 }}>
          How the Gene-Symbol Parser Works
        </h1>
        <p style={{ color: "#6b7280", fontSize: 14, marginBottom: 24 }}>
          What the SSPsyGene loader does to the gene-name column of every
          published table — and what the <code style={codeStyle}>_raw</code> and{" "}
          <code style={codeStyle}>_resolution</code> columns next to it mean.
        </p>

        {/* Table of Contents */}
        <nav
          style={{
            background: "#f9fafb",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: "14px 20px",
            marginBottom: 32,
          }}
        >
          <div
            style={{
              fontWeight: 600,
              fontSize: 13,
              color: "#6b7280",
              textTransform: "uppercase",
              marginBottom: 8,
            }}
          >
            Contents
          </div>
          <ol style={{ paddingLeft: 20, margin: 0, fontSize: 14 }}>
            {[
              ["why", "Why this is hard"],
              ["pipeline", "What we run, in order"],
              ["columns", "The _raw and _resolution columns"],
              ["preference", "Resolution preference order"],
              ["species", "Species-specific notes"],
              ["slip", "What still slips through"],
              ["history", "Implementation history"],
            ].map(([id, label]) => (
              <li key={id} style={{ marginBottom: 2 }}>
                <a
                  href={`#sec-${id}`}
                  style={{ color: "#2563eb", textDecoration: "none" }}
                  onClick={(e) => {
                    e.preventDefault();
                    document
                      .getElementById(`sec-${id}`)
                      ?.scrollIntoView({ behavior: "smooth" });
                  }}
                >
                  {label}
                </a>
              </li>
            ))}
          </ol>
        </nav>

        {/* 1. Why this is hard */}
        <section
          id="sec-why"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Why this is hard</h2>
          <p>
            Most published gene tables contain at least one column of
            &ldquo;gene names&rdquo; that nobody fully cleaned. By the time a
            spreadsheet has travelled from the lab through Excel, R, a Python
            notebook, a supplementary PDF, and our import script, the same
            gene can show up as <code style={codeStyle}>BRCA1</code>,{" "}
            <code style={codeStyle}>brca1</code>,{" "}
            <code style={codeStyle}>HGNC:1100</code>,{" "}
            <code style={codeStyle}>ENSG00000012048.18</code>,{" "}
            <code style={codeStyle}>BRCA1.1</code>, or
            even — for SEPTIN9 — the literal string{" "}
            <code style={codeStyle}>9-Sep</code>.
          </p>
          <p>
            A short, incomplete list of the things that go wrong:
          </p>
          <ul>
            <li>
              <strong>Excel date coercion.</strong> A symbol like{" "}
              <code style={codeStyle}>SEPT9</code> opens in Excel as the date
              &ldquo;September 9&rdquo; and gets re-saved as{" "}
              <code style={codeStyle}>9-Sep</code> or{" "}
              <code style={codeStyle}>2023-09-09</code>. Affects roughly
              one in five published gene-list papers despite HGNC&apos;s
              SEPTIN renames.
            </li>
            <li>
              <strong>HGNC alias churn.</strong> Symbols are renamed (e.g.{" "}
              <code style={codeStyle}>NOV → CCN3</code>,{" "}
              <code style={codeStyle}>QARS → QARS1</code>), and old papers
              keep using the retired form.
            </li>
            <li>
              <strong>R&apos;s <code style={codeStyle}>make.unique</code>.</strong>{" "}
              When a data frame has duplicate row names, R appends{" "}
              <code style={codeStyle}>.1</code>,{" "}
              <code style={codeStyle}>.2</code>, etc., turning{" "}
              <code style={codeStyle}>MATR3</code> into{" "}
              <code style={codeStyle}>MATR3.1</code>.
            </li>
            <li>
              <strong>Mixed Ensembl IDs.</strong> Some tables interleave
              symbols with raw <code style={codeStyle}>ENSG…</code>/{" "}
              <code style={codeStyle}>ENSMUSG…</code> identifiers, sometimes
              with version suffixes
              (<code style={codeStyle}>ENSG00000012048.18</code>) and sometimes
              without.
            </li>
            <li>
              <strong>Legacy GENCODE clone names.</strong> Older annotations
              (GENCODE pre-v22) used BAC/PAC/cosmid clone labels like{" "}
              <code style={codeStyle}>RP11-783K16.5</code>. Many of these now
              have HGNC symbols; some only have a current Ensembl gene ID;
              some only a GenBank accession.
            </li>
            <li>
              <strong>Non-gene rows mixed in.</strong> RNA-family labels
              (<code style={codeStyle}>Y_RNA</code>,{" "}
              <code style={codeStyle}>U6</code>,{" "}
              <code style={codeStyle}>SNORA74</code>,{" "}
              <code style={codeStyle}>MIR5096</code>), assembly contig
              accessions (<code style={codeStyle}>AC012345.6</code>), and bare
              GenBank accessions (<code style={codeStyle}>KC877982</code>) all
              show up where a gene symbol is expected.
            </li>
          </ul>
          <p>
            We&apos;re not aware of an off-the-shelf tool that handles every
            one of these in a single pass. The SSPsyGene loader does, and
            keeps a per-row audit trail of which rule fired so you can verify
            any rescue after the fact. The rest of this page walks through
            what each rule does.
          </p>
        </section>

        {/* 2. Pipeline */}
        <section
          id="sec-pipeline"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>What we run, in order</h2>
          <p>
            For every value in a gene column, the parser tries the following
            rules in order. The first rule that produces a current approved
            symbol wins; the parser then tags the row with the rule&apos;s
            name and moves on. The tag names match the values you&apos;ll see
            in the <code style={codeStyle}>_resolution</code> column described
            in the next section.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            1. Direct lookup &mdash;{" "}
            <code style={codeStyle}>passed_through</code>
          </h3>
          <p>
            The most common case. The raw value is already a current HGNC
            symbol (human) or MGI symbol (mouse), or an unambiguous alias /
            previous symbol. We map it to the current canonical form and move
            on. Empty / NaN cells are also tagged{" "}
            <code style={codeStyle}>passed_through</code>.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            2. HGNC ID rescue &mdash;{" "}
            <code style={codeStyle}>rescued_hgnc_id</code>
          </h3>
          <p>
            If the value is a literal HGNC identifier like{" "}
            <code style={codeStyle}>HGNC:1100</code>, we look it up in HGNC
            and substitute the current approved symbol.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            3. Excel demangle &mdash;{" "}
            <code style={codeStyle}>rescued_excel</code>
          </h3>
          <p>
            Repairs the two date-coercion forms Excel produces — classic
            (<code style={codeStyle}>9-Sep</code>,{" "}
            <code style={codeStyle}>1-Mar</code>) and ISO
            (<code style={codeStyle}>2023-09-04</code>) — back to the intended
            symbol (<code style={codeStyle}>SEPTIN9</code>,{" "}
            <code style={codeStyle}>MARCHF1</code>, …). Each candidate is
            verified against the live HGNC/MGI table before substitution, so
            we never invent a symbol the org doesn&apos;t recognise.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            4. <code style={codeStyle}>make.unique</code> suffix strip &mdash;{" "}
            <code style={codeStyle}>rescued_make_unique</code>
          </h3>
          <p>
            Strips the trailing <code style={codeStyle}>.N</code> R{" "}
            <code style={codeStyle}>make.unique()</code> appends to
            disambiguate duplicate row names (e.g.{" "}
            <code style={codeStyle}>MATR3.1 → MATR3</code>). Only fires when
            the unsuffixed form resolves and the original does not, so we
            don&apos;t accidentally clobber GENCODE clone names like{" "}
            <code style={codeStyle}>RP11-783K16.5</code> that legitimately
            end in <code style={codeStyle}>.5</code>.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            5. Symbol/ENSG split &mdash;{" "}
            <code style={codeStyle}>rescued_symbol_ensg</code>
          </h3>
          <p>
            Some tools concatenate <code style={codeStyle}>SYMBOL_ENSG…</code>{" "}
            into a single column value. We split on{" "}
            <code style={codeStyle}>_ENSG</code> and resolve the symbol
            portion.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            6. Manual aliases &mdash;{" "}
            <code style={codeStyle}>rescued_manual_alias</code>
          </h3>
          <p>
            A small wrangler-curated successor map for retired symbols whose
            current name HGNC&apos;s alias table doesn&apos;t resolve
            automatically. Cross-dataset entries today:{" "}
            <code style={codeStyle}>NOV → CCN3</code>,{" "}
            <code style={codeStyle}>MUM1 → PWWP3A</code>,{" "}
            <code style={codeStyle}>QARS → QARS1</code>,{" "}
            <code style={codeStyle}>SARS → SARS1</code>,{" "}
            <code style={codeStyle}>TAZ → TAFAZZIN</code>. The target is
            verified through HGNC before substitution, so a typo in the
            successor name fails loudly rather than silently corrupting the
            data.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            7. Ensembl gene ID map &mdash;{" "}
            <code style={codeStyle}>rescued_ensembl_map</code>
          </h3>
          <p>
            Resolves bare <code style={codeStyle}>ENSG…</code> /{" "}
            <code style={codeStyle}>ENSMUSG…</code> identifiers to their
            current symbol via HGNC&apos;s <code style={codeStyle}>
              hgnc_complete_set.txt
            </code>{" "}
            (human) and Alliance{" "}
            <code style={codeStyle}>HGNC_AllianceHomology.rpt</code> (mouse).
            Versioned IDs like{" "}
            <code style={codeStyle}>ENSG00000012048.18</code> are handled by
            stripping the version suffix before lookup. If an Ensembl ID has
            no symbol mapping, it falls through to the silencer below
            (it&apos;s kept as a stable identifier, just not promoted to a
            gene symbol).
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            8. GENCODE clone-name resolver &mdash;{" "}
            <code style={codeStyle}>rescued_gencode_clone_*</code>
          </h3>
          <p>
            Looks up legacy GENCODE/HAVANA clone identifiers
            (<code style={codeStyle}>RP11-…</code>,{" "}
            <code style={codeStyle}>CTD-…</code>,{" "}
            <code style={codeStyle}>KB-…</code>,{" "}
            <code style={codeStyle}>XXbac-…</code>, etc.) in a prebuilt
            cross-reference table assembled from GENCODE v38 (Ensembl 104,
            May 2021). Each clone resolves to one of three things, in
            preference order:
          </p>
          <ul>
            <li>
              its current <strong>HGNC symbol</strong>, if HGNC has assigned
              one (tag{" "}
              <code style={codeStyle}>rescued_gencode_clone_hgnc_symbol</code>);
            </li>
            <li>
              otherwise its current <strong>Ensembl gene ID</strong>{" "}
              (tag{" "}
              <code style={codeStyle}>rescued_gencode_clone_current_ensg</code>);
            </li>
            <li>
              otherwise its current <strong>AC/AL/AP accession</strong>{" "}
              (tag{" "}
              <code style={codeStyle}>
                rescued_gencode_clone_current_ac_accession
              </code>
              ).
            </li>
          </ul>
          <p>
            The verbose clone label is replaced with the resolved value, so
            downstream queries find the locus under its modern identifier.
            Clones absent from the table fall through to the silencer.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            9. Non-symbol silencer &mdash;{" "}
            <code style={codeStyle}>non_symbol_*</code>
          </h3>
          <p>
            Catches values that recognisably aren&apos;t gene symbols, so the
            loader stops warning about them. Six categories:
          </p>
          <div style={{ overflowX: "auto", margin: "10px 0" }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Category</th>
                  <th style={thStyle}>Matches</th>
                  <th style={thStyle}>Examples</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["ensembl_human", "ENSG\\d+(\\.\\d+)?", "ENSG00000123456, ENSG00000123456.5"],
                  ["ensembl_mouse", "ENSMUSG\\d+(\\.\\d+)?", "ENSMUSG00000071265"],
                  ["contig", "Sanger / WGS contig accessions", "AC012345.6, AUXG01000058.1"],
                  ["gencode_clone", "BAC / PAC / cosmid clone names", "RP11-783K16.5, CTD-2331H12.4"],
                  ["genbank_accession", "[A-Z]{1,2}\\d{5,6}(\\.\\d+)?", "KC877982, L29074.1"],
                  ["rna_family", "RNA-family labels (not loci)", "Y_RNA, U6, SNORA74, MIR5096"],
                ].map(([cat, matches, examples]) => (
                  <tr key={cat}>
                    <td style={{ ...tdStyle, fontWeight: 600 }}>
                      <code style={codeStyle}>{cat}</code>
                    </td>
                    <td style={tdStyle}>{matches}</td>
                    <td style={tdStyle}>
                      <code style={codeStyle}>{examples}</code>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Silenced values are kept in the table as-is (with the original
            value preserved in <code style={codeStyle}>_raw</code>), but they
            don&apos;t produce a &ldquo;not in gene maps&rdquo; warning at
            load time, and they aren&apos;t inserted into the central gene
            table as if they were genuine gene records.
          </p>

          <h3 style={{ fontSize: 16, fontWeight: 700, marginTop: 20, marginBottom: 6 }}>
            10. Unresolved fallback &mdash;{" "}
            <code style={codeStyle}>unresolved</code>
          </h3>
          <p>
            Anything that fell through every rule above. The original value
            is kept in the table (and in{" "}
            <code style={codeStyle}>_raw</code>), but it&apos;s the only tag
            that still triggers a warning at load time. Values landing here
            are usually dataset-specific noise (lab nicknames, sample IDs
            misfiled into the gene column) or genuinely retired symbols whose
            successor isn&apos;t in HGNC&apos;s automatic alias table; the
            latter become candidates for a manual-alias entry.
          </p>
        </section>

        {/* 3. _raw and _resolution columns */}
        <section
          id="sec-columns"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>The <code style={codeStyle}>_raw</code> and{" "}
            <code style={codeStyle}>_resolution</code> columns</h2>
          <p>
            Every cleaned table keeps two extra columns next to each
            gene-name column:
          </p>
          <ul>
            <li>
              <code style={codeStyle}>&lt;col&gt;_raw</code> — the original
              value before any cleaning. Always populated, even for rows that
              passed through unchanged.
            </li>
            <li>
              <code style={codeStyle}>_&lt;col&gt;_resolution</code> — the
              per-row tag identifying which rule fired (or that the value is
              still unresolved).
            </li>
          </ul>
          <p>
            Together they let you audit any row in a published table without
            cross-referencing the source. Example:
          </p>
          <pre style={preStyle}>
            <code>{`target_gene  target_gene_raw   _target_gene_resolution
BRCA1        BRCA1             passed_through
SEPTIN9      9-Sep             rescued_excel
MATR3        MATR3.1           rescued_make_unique
CCN3         NOV               rescued_manual_alias
ENSG00000…   ENSG00000…        non_symbol_ensembl_human
NOTAGENE     NOTAGENE          unresolved`}</code>
          </pre>
          <p>
            The full set of resolution tags:
          </p>
          <div style={{ overflowX: "auto", margin: "10px 0" }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>Tag</th>
                  <th style={thStyle}>Meaning</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["passed_through", "Resolved via the live HGNC/MGI table (or the value was empty/NaN)."],
                  ["rescued_hgnc_id", "Literal HGNC:NNNNN identifier resolved."],
                  ["rescued_excel", "Excel-mangled date repaired to its original symbol."],
                  ["rescued_make_unique", "R make.unique .N suffix stripped."],
                  ["rescued_symbol_ensg", "<symbol>_ENSG… composite split."],
                  ["rescued_manual_alias", "Wrangler-curated retired-symbol successor used."],
                  ["rescued_ensembl_map", "Bare ENSG/ENSMUSG identifier resolved to a current symbol."],
                  ["rescued_gencode_clone_hgnc_symbol", "GENCODE clone resolved to its current HGNC symbol."],
                  ["rescued_gencode_clone_current_ensg", "GENCODE clone resolved to a stable Ensembl gene ID (no HGNC symbol assigned)."],
                  ["rescued_gencode_clone_current_ac_accession", "GENCODE clone resolved to an AC/AL/AP accession (no HGNC or Ensembl available)."],
                  ["non_symbol_ensembl_human / _ensembl_mouse / _contig / _gencode_clone / _genbank_accession / _rna_family", "Recognisably not a gene symbol — kept as-is, silenced, classified by which pattern matched."],
                  ["unresolved", "Genuinely unknown; kept as raw text and warned at load time."],
                ].map(([tag, meaning]) => (
                  <tr key={tag}>
                    <td
                      style={{
                        ...tdStyle,
                        fontWeight: 600,
                        width: 300,
                        maxWidth: 300,
                        wordBreak: "break-word",
                      }}
                    >
                      <code style={codeStyle}>{tag}</code>
                    </td>
                    <td style={tdStyle}>{meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={noteStyle}>
            <strong>Tip:</strong> if you suspect a rescue has gone wrong,{" "}
            <code style={codeStyle}>_raw</code> is your audit trail —
            it preserves exactly what the wrangler&apos;s preprocessing
            script saw before any of these rules fired.
          </div>
        </section>

        {/* 4. Resolution preference order */}
        <section
          id="sec-preference"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Resolution preference order</h2>
          <p>
            When a single locus could plausibly resolve to multiple stable
            identifiers — typically a GENCODE clone that has both a current
            ENSG and an AC accession, or an ENSG that has both a symbol and a
            raw ID — we always prefer:
          </p>
          <ol>
            <li>
              <strong>HGNC symbol</strong> — the canonical, human-curated
              identifier; the only form most biologists recognise on sight.
            </li>
            <li>
              <strong>Ensembl gene ID</strong>{" "}
              (<code style={codeStyle}>ENSG…</code> /{" "}
              <code style={codeStyle}>ENSMUSG…</code>) — stable across
              releases, machine-readable, supported by every downstream
              lookup we use.
            </li>
            <li>
              <strong>AC / AL / AP accession</strong> — last-resort but
              unambiguous; used only for legacy clones that have no symbol
              and no current Ensembl gene ID.
            </li>
            <li>
              <strong>Silenced as non-symbol</strong> — for values that
              recognisably aren&apos;t loci at all (RNA families, contigs,
              GenBank accessions).
            </li>
          </ol>
          <p>
            The same ordering governs the GENCODE clone resolver
            (<code style={codeStyle}>rescued_gencode_clone_*</code>), the
            Ensembl-map rescue
            (<code style={codeStyle}>rescued_ensembl_map</code>), and the
            silencer&apos;s classification — pick the most-curated form that
            still uniquely identifies the locus.
          </p>
        </section>

        {/* 5. Species */}
        <section
          id="sec-species"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Species-specific notes</h2>
          <p>
            <strong>Human (HGNC).</strong> The parser uses HGNC&apos;s{" "}
            <code style={codeStyle}>hgnc_complete_set.txt</code>: approved
            symbols, their alias and previous symbols (with ambiguous
            many-to-one aliases dropped to avoid false rescues), and the
            literal <code style={codeStyle}>HGNC:NNNNN</code> identifiers.
            ENSG → symbol mappings come from the same file.
          </p>
          <p>
            <strong>Mouse (MGI / Ensembl).</strong> The parser uses{" "}
            <code style={codeStyle}>MGI_EntrezGene.rpt</code>: approved MGI
            symbols, withdrawn-to-current mappings, synonyms, plus a
            case-insensitive fallback (<code style={codeStyle}>Slc30A3</code>{" "}
            → <code style={codeStyle}>Slc30a3</code>). ENSMUSG → MGI symbol
            mappings come from the Alliance{" "}
            <code style={codeStyle}>HGNC_AllianceHomology.rpt</code> file,
            which also gives us mouse → human ortholog links used elsewhere
            in the database.
          </p>
          <p>
            <strong>Zebrafish.</strong> Only one dataset (<em>zebraAsd</em>)
            uses zebrafish. There&apos;s no full ZFIN normalizer; the
            wrangler&apos;s preprocessing script up-cases the gene token and
            applies a manual paralog mapping
            (<code style={codeStyle}>SCN1LAB → SCN1A</code>) before the
            symbol reaches the central gene table.
          </p>
        </section>

        {/* 6. What still slips through */}
        <section
          id="sec-slip"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>What still slips through</h2>
          <p>
            Rows tagged <code style={codeStyle}>unresolved</code> are rare
            but not zero — the most recent full rebuild left ~75 across the
            entire database. They&apos;re kept in the table as raw text;
            the parser doesn&apos;t guess.
          </p>
          <p>
            If you want to look at them, every dataset&apos;s <em>
              Preprocessing (YAML)
            </em>{" "}
            file (downloadable from the{" "}
            <Link href="/download" style={{ color: "#2563eb" }}>
              Downloads page
            </Link>
            ) lists the first ~10 unresolved values per gene column under{" "}
            <code style={codeStyle}>sample_unresolved</code>, alongside the
            counts of every rescue rule that fired. That&apos;s the place to
            start when you suspect a particular paper&apos;s gene column
            wasn&apos;t cleanly imported.
          </p>
        </section>

        {/* 7. Implementation history */}
        <section
          id="sec-history"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Implementation history</h2>
          <p>
            Two GitHub issues track the bulk of the technical history if
            you&apos;d like the development backstory:
          </p>
          <ul>
            <li>
              <a
                href="https://github.com/sspsygene-dracc/psypheno/issues/119"
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "#2563eb" }}
              >
                psypheno #119
              </a>{" "}
              — moving ENSG → symbol resolution from runtime into the
              preprocessing step, so cleaned tables ship with a real symbol
              already in place and an audit trail beside it.
            </li>
            <li>
              <a
                href="https://github.com/sspsygene-dracc/psypheno/issues/139"
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "#2563eb" }}
              >
                psypheno #139
              </a>{" "}
              — building the GENCODE clone-name resolver and pinning the
              clone table to GENCODE v38.
            </li>
          </ul>
          <p>
            For statistical methods used elsewhere on the site (Fisher,
            Cauchy, harmonic-mean p-value combination), see{" "}
            <Link href="/methods" style={{ color: "#2563eb" }}>
              Meta-analysis methods
            </Link>
            .
          </p>
        </section>
      </main>
      <Footer />
    </>
  );
}
