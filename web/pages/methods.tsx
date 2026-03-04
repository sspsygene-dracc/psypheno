import Head from "next/head";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

/* Reusable inline styles */
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

const mathBlock: React.CSSProperties = {
  background: "#f9fafb",
  border: "1px solid #e5e7eb",
  borderRadius: 6,
  padding: "12px 16px",
  margin: "12px 0",
  fontSize: 15,
  textAlign: "center",
  lineHeight: 2.2,
  overflowX: "auto",
  fontFamily: "'Times New Roman', Georgia, serif",
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

const refStyle: React.CSSProperties = {
  fontSize: 13,
  color: "#6b7280",
  fontStyle: "italic",
  marginTop: 8,
};

/* Fraction helper */
function Frac({ num, den }: { num: React.ReactNode; den: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: "center",
        verticalAlign: "middle",
        margin: "0 2px",
        fontSize: "0.92em",
      }}
    >
      <span
        style={{
          borderBottom: "1.5px solid #1f2937",
          padding: "0 4px",
          lineHeight: 1.35,
        }}
      >
        {num}
      </span>
      <span style={{ padding: "0 4px", lineHeight: 1.35 }}>{den}</span>
    </span>
  );
}

function V({ children }: { children: React.ReactNode }) {
  return (
    <span
      style={{
        fontStyle: "italic",
        fontFamily: "'Times New Roman', Georgia, serif",
      }}
    >
      {children}
    </span>
  );
}

export default function MethodsPage() {
  return (
    <>
      <Head>
        <title>Methods — SSPsyGene</title>
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
          Combined P-Value Methods
        </h1>
        <p style={{ color: "#6b7280", fontSize: 14, marginBottom: 24 }}>
          Statistical methods for aggregating evidence across datasets in
          SSPsyGene
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
              ["overview", "Overview & Pipeline"],
              [
                "precollapse",
                "Pre-Collapse: Bonferroni Within-Table Correction",
              ],
              ["fisher", "Fisher\u2019s Method"],
              ["stouffer", "Stouffer\u2019s Method"],
              ["cauchy", "Cauchy Combination Test (CCT)"],
              ["hmp", "Harmonic Mean P-Value (HMP)"],
              ["rationale", "Why All Four Methods?"],
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

        {/* 0. Overview */}
        <section
          id="sec-overview"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Overview &amp; Pipeline</h2>
          <p>
            Each gene in the SSPsyGene database can appear in multiple datasets
            and, within a single dataset, can have multiple associated p-values
            (e.g., one per perturbation experiment that affected it). Our goal
            is to combine these p-values into a single summary statistic per
            gene that captures total evidence across all experiments.
          </p>
          <p>The pipeline for each gene proceeds as follows:</p>
          <ol>
            <li>
              <strong>Collect raw p-values</strong> from every dataset table
              that declares a <span style={codeStyle}>pvalue_column</span>. A
              single gene may contribute multiple p-values per table and across
              many tables.
            </li>
            <li>
              <strong>Pre-collapse</strong> (for Fisher/Stouffer only): reduce
              each table&apos;s p-values for that gene down to a single
              per-table p-value using min(<V>p</V>)&thinsp;&times;&thinsp;
              <V>n</V>, capped at 1.0.
            </li>
            <li>
              <strong>Combine</strong> using four methods: Fisher and Stouffer
              operate on the collapsed per-table p-values; CCT and HMP operate
              directly on all raw p-values.
            </li>
          </ol>
          <p>
            Fisher and Stouffer require at least 2 collapsed table p-values
            (both &lt; 1.0) to produce a result. CCT and HMP can operate on any
            number of p-values &ge; 1. All statistical computations are
            performed in R using reference implementations.
          </p>
        </section>

        {/* 1. Pre-Collapse */}
        <section
          id="sec-precollapse"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>
            Pre-Collapse: Bonferroni Within-Table Correction
          </h2>
          <p>
            <strong>Problem:</strong> A gene may appear in multiple rows of the
            same data table. For instance, in a perturbation screen, gene{" "}
            <V>G</V> might be a differentially expressed target in experiments
            where 5 different risk genes were knocked down. That gives us 5
            p-values for <V>G</V> from a single table. These p-values are{" "}
            <em>not independent</em>; they all come from the same assay
            measuring the same gene, and we should not feed them individually
            into Fisher or Stouffer as though they were independent studies.
          </p>
          <p>
            <strong>Solution:</strong> For each gene-table combination, we
            compute a single representative p-value:
          </p>
          <div style={mathBlock}>
            <V>p</V>
            <sub>table</sub> = min( min(<V>p</V>
            <sub>1</sub>, &hellip;, <V>p</V>
            <sub>
              <V>n</V>
            </sub>
            ) &times; <V>n</V>,&ensp;1.0 )
          </div>
          <p>
            where <V>n</V> is the number of rows for that gene in that table.
            This is the{" "}
            <strong>Bonferroni correction applied to the minimum</strong>: we
            take the best p-value but penalize it by the number of looks. This
            is conservative but guarantees we do not inflate significance from
            within-table multiplicity. Pre-collapse uses arbitrary-precision
            arithmetic (mpmath) to avoid precision loss with very small
            p-values.
          </p>
          <p>
            <strong>Who uses it:</strong> Fisher&apos;s method and
            Stouffer&apos;s method. The CCT and HMP, being robust to
            correlation, operate on the full set of raw p-values directly.
          </p>
        </section>

        {/* 2. Fisher */}
        <section
          id="sec-fisher"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Fisher&apos;s Method</h2>
          <p>
            Fisher&apos;s method (1932) is the oldest and most widely used
            p-value combination technique. Under the null hypothesis, each
            p-value is Uniform(0,&thinsp;1), so &minus;2&thinsp;ln(<V>p</V>) is
            distributed as &chi;&sup2;(2). Sums of independent chi-squared
            variables are themselves chi-squared.
          </p>
          <p>
            <strong>Test statistic:</strong>
          </p>
          <div style={mathBlock}>
            <V>X</V>&sup2; = &minus;2 &sum;
            <sub>
              <V>i</V>=1
            </sub>
            <sup>
              <V>k</V>
            </sup>{" "}
            ln(<V>p</V>
            <sub>
              <V>i</V>
            </sub>
            )
          </div>
          <p>
            where <V>k</V> is the number of tables (after pre-collapse).
          </p>
          <p>
            <strong>Null distribution:</strong>
          </p>
          <div style={mathBlock}>
            <V>X</V>&sup2; ~ &chi;&sup2;(2<V>k</V>)
          </div>
          <p>
            The combined p-value is P(&chi;&sup2;(2<V>k</V>) &ge; <V>X</V>
            &sup2;).
          </p>
          <p>
            <strong>Why it works:</strong>
          </p>
          <ol>
            <li>
              If <V>p</V> ~ Uniform(0,1), then &minus;ln(<V>p</V>) ~
              Exponential(1).
            </li>
            <li>
              An Exponential(1) variable equals Gamma(1,1), and
              2&times;Exponential(1) = &chi;&sup2;(2).
            </li>
            <li>
              Therefore &minus;2&thinsp;ln(<V>p</V>) ~ &chi;&sup2;(2) for each{" "}
              <V>p</V>.
            </li>
            <li>
              Sums of independent &chi;&sup2; variables: &chi;&sup2;(<V>d</V>
              <sub>1</sub>) + &chi;&sup2;(<V>d</V>
              <sub>2</sub>) = &chi;&sup2;(<V>d</V>
              <sub>1</sub>+<V>d</V>
              <sub>2</sub>).
            </li>
            <li>
              Hence <V>X</V>&sup2; ~ &chi;&sup2;(2<V>k</V>).
            </li>
          </ol>
          <p>
            <strong>Independence assumption:</strong> Step 4 requires the
            p-values to be independent. When p-values are positively correlated,
            Fisher&apos;s method tends to be anti-conservative. This is why we
            use the pre-collapse step to reduce inputs to one per table.
          </p>
          <p>
            Computed using <span style={codeStyle}>poolr::fisher()</span>.
          </p>
          <p style={refStyle}>
            Fisher, R.A. (1932).{" "}
            <em>Statistical Methods for Research Workers</em>, 4th ed.
          </p>
        </section>

        {/* 3. Stouffer */}
        <section
          id="sec-stouffer"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Stouffer&apos;s Method</h2>
          <p>
            Stouffer&apos;s method (1949) converts each p-value to a Z-score via
            the inverse normal CDF, then sums and normalizes.
          </p>
          <p>
            <strong>Test statistic:</strong>
          </p>
          <div style={mathBlock}>
            <V>Z</V> ={" "}
            <Frac
              num={
                <>
                  &sum;
                  <sub>
                    <V>i</V>=1
                  </sub>
                  <sup>
                    <V>k</V>
                  </sup>{" "}
                  &Phi;<sup>&minus;1</sup>(1 &minus; <V>p</V>
                  <sub>
                    <V>i</V>
                  </sub>
                  )
                </>
              }
              den={
                <>
                  &radic;<V>k</V>
                </>
              }
            />
          </div>
          <p>
            Under H<sub>0</sub> with independent p-values, <V>Z</V> ~
            Normal(0,&thinsp;1). The combined p-value is P(<V>Z</V> &ge;{" "}
            <V>Z</V>
            <sub>obs</sub>).
          </p>
          <p>
            <strong>Comparison with Fisher:</strong> Fisher is more sensitive to
            one very small p-value; Stouffer responds more evenly to moderate
            signals across many studies.
          </p>
          <p>
            Computed using <span style={codeStyle}>poolr::stouffer()</span>.
          </p>
          <p style={refStyle}>
            Stouffer, S.A. et al. (1949). <em>The American Soldier</em>, Vol. 1.
          </p>
        </section>

        {/* 4. CCT */}
        <section
          id="sec-cauchy"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Cauchy Combination Test (CCT)</h2>
          <p>
            The CCT (Liu &amp; Xie, 2020) was designed for settings where input
            p-values may be correlated. It exploits a special property of the
            Cauchy distribution.
          </p>
          <p>
            <strong>Test statistic:</strong>
          </p>
          <div style={mathBlock}>
            <V>T</V> = &sum;
            <sub>
              <V>i</V>=1
            </sub>
            <sup>
              <V>L</V>
            </sup>{" "}
            <V>w</V>
            <sub>
              <V>i</V>
            </sub>{" "}
            &middot; tan((0.5 &minus; <V>p</V>
            <sub>
              <V>i</V>
            </sub>
            ) &middot; &pi;)
          </div>
          <p>
            where <V>L</V> is the total number of raw p-values and <V>w</V>
            <sub>
              <V>i</V>
            </sub>{" "}
            = 1/<V>L</V> (equal weights summing to 1).
          </p>
          <p>
            <strong>The key transform: Uniform to Cauchy:</strong>
          </p>
          <ol>
            <li>
              <V>p</V> ~ Uniform(0,1).
            </li>
            <li>
              0.5 &minus; <V>p</V> ~ Uniform(&minus;0.5, 0.5).
            </li>
            <li>
              (0.5 &minus; <V>p</V>) &middot; &pi; ~ Uniform(&minus;&pi;/2,
              &pi;/2).
            </li>
            <li>
              tan((0.5 &minus; <V>p</V>) &middot; &pi;) ~{" "}
              <strong>Cauchy(0,&thinsp;1)</strong>.
            </li>
          </ol>
          <p>
            Step 4 is a classical result: if <V>U</V> ~ Uniform(&minus;&pi;/2,
            &pi;/2), then tan(<V>U</V>) follows a standard Cauchy distribution.
          </p>
          <p>
            <strong>Why the Cauchy distribution is special:</strong> Any
            weighted sum of independent Cauchy random variables is again Cauchy.
            With our weights summing to 1, <V>T</V> ~ Cauchy(0,1) under
            independence. More importantly,{" "}
            <strong>even under dependency</strong>, Liu &amp; Xie proved
            (Theorem 1) that the tail behavior of <V>T</V> is well-approximated
            by Cauchy(0,1). Formally, the theorem requires that the underlying
            test statistics follow bivariate normal distributions for each pair
            (Condition C.1), but permits arbitrary correlation matrices.
            Simulations show the approximation is robust well beyond this
            assumption. The heavy tails of the Cauchy &ldquo;absorb&rdquo; the
            effect of correlation.
          </p>
          <p>
            <strong>Combined p-value:</strong>
          </p>
          <div style={mathBlock}>
            <V>p</V>
            <sub>combined</sub> = P(Cauchy(0,1) &gt; <V>T</V>) ={" "}
            <Frac num="1" den="2" /> &minus;{" "}
            <Frac
              num={
                <>
                  arctan(<V>T</V>)
                </>
              }
              den={<>&pi;</>}
            />
          </div>
          <p>
            For very small p-values (&lt; 10<sup>&minus;15</sup>), the transform
            tan((0.5&thinsp;&minus;&thinsp;<V>p</V>
            )&thinsp;&middot;&thinsp;&pi;) is replaced by its asymptotic
            equivalent 1/(<V>p</V>&thinsp;&middot;&thinsp;&pi;) for numerical
            stability. Computed using the reference implementation from the
            method&apos;s authors (<span style={codeStyle}>ACAT::ACAT</span>).
          </p>
          <p style={refStyle}>
            Liu, Y. &amp; Xie, J. (2019). Cauchy combination test: a powerful
            test with analytic p-value calculation under arbitrary dependency
            structures. <em>Journal of the American Statistical Association</em>
            , 115(529), 393&ndash;402.{" "}
            <a
              href="https://doi.org/10.1080/01621459.2018.1554485"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "#2563eb" }}
            >
              doi:10.1080/01621459.2018.1554485
            </a>
          </p>
        </section>

        {/* 5. HMP */}
        <section id="sec-hmp" style={{ ...sectionStyle, scrollMarginTop: 16 }}>
          <h2 style={h2Style}>Harmonic Mean P-Value (HMP)</h2>
          <p>
            The HMP (Wilson, 2019) is a dependency-robust method that uses the
            harmonic mean. It was developed for combining p-values from
            genome-wide studies where correlation structures are complex and
            unknown.
          </p>
          <p>
            <strong>Definition:</strong>
          </p>
          <div style={mathBlock}>
            HMP ={" "}
            <Frac
              num={
                <>
                  &sum;
                  <sub>
                    <V>i</V>
                  </sub>{" "}
                  <V>w</V>
                  <sub>
                    <V>i</V>
                  </sub>
                </>
              }
              den={
                <>
                  &sum;
                  <sub>
                    <V>i</V>
                  </sub>{" "}
                  <V>w</V>
                  <sub>
                    <V>i</V>
                  </sub>{" "}
                  / <V>p</V>
                  <sub>
                    <V>i</V>
                  </sub>
                </>
              }
            />{" "}
            ={" "}
            <Frac
              num={<V>L</V>}
              den={
                <>
                  &sum;
                  <sub>
                    <V>i</V>
                  </sub>{" "}
                  1/<V>p</V>
                  <sub>
                    <V>i</V>
                  </sub>
                </>
              }
            />
          </div>
          <p>
            with equal weights <V>w</V>
            <sub>
              <V>i</V>
            </sub>{" "}
            = 1/<V>L</V>. This is the <strong>harmonic mean</strong> of the
            p-values, strongly influenced by small values, which is exactly the
            behavior we want for combining p-values.
          </p>
          <p>
            <strong>Landau distribution calibration:</strong>
          </p>
          <p>
            Under H<sub>0</sub>, Wilson (2019) showed that 1/HMP follows a{" "}
            <strong>Landau distribution</strong> (a heavy-tailed,
            positively-skewed stable distribution with characteristic exponent
            &alpha;&thinsp;=&thinsp;1). Rather than using the raw harmonic mean
            directly as a p-value, we use R&apos;s{" "}
            <span style={codeStyle}>harmonicmeanp::p.hmp()</span> function,
            which calibrates the HMP against the Landau distribution to obtain
            an exact p-value. This accounts for the finite-sample behavior of
            the harmonic mean and provides better calibration than the
            asymptotic approximation, especially for moderate p-values.
          </p>
          <p>
            <strong>Robustness to dependency:</strong>
          </p>
          <p>
            Wilson&apos;s Theorem 1 shows that the HMP is an asymptotically
            valid p-value under <em>arbitrary dependency</em> when weights are
            normalized. The proof leverages the fact that 1/<V>p</V> has a
            Pareto(1) distribution (heavy-tailed, infinite mean), and sums of
            such variables converge to a stable law whose tail behavior is
            controlled regardless of the dependency structure, analogous to why
            the CCT works.
          </p>
          <p style={refStyle}>
            Wilson, D.J. (2019). The harmonic mean <em>p</em>-value for
            combining dependent tests.{" "}
            <em>Proceedings of the National Academy of Sciences</em>, 116(4),
            1195&ndash;1200.{" "}
            <a
              href="https://doi.org/10.1073/pnas.1814092116"
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: "#2563eb" }}
            >
              doi:10.1073/pnas.1814092116
            </a>
          </p>
        </section>

        {/* 7. Why All Four Methods? */}
        <section
          id="sec-rationale"
          style={{ ...sectionStyle, scrollMarginTop: 16 }}
        >
          <h2 style={h2Style}>Why All Four Methods?</h2>
          <p>
            We compute all four combination methods because they have
            complementary strengths and the &ldquo;true&rdquo; dependency
            structure among our p-values is unknown:
          </p>
          <div style={{ overflowX: "auto", margin: "12px 0" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: 14,
              }}
            >
              <thead>
                <tr
                  style={{
                    borderBottom: "2px solid #d1d5db",
                    textAlign: "left",
                  }}
                >
                  <th style={{ padding: "8px 10px" }}>Method</th>
                  <th style={{ padding: "8px 10px" }}>Input</th>
                  <th style={{ padding: "8px 10px" }}>Dependency</th>
                  <th style={{ padding: "8px 10px" }}>Sensitivity</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    "Fisher",
                    "Collapsed (per-table)",
                    "Requires independence",
                    "Driven by strongest single signal",
                  ],
                  [
                    "Stouffer",
                    "Collapsed (per-table)",
                    "Requires independence",
                    "Responds evenly to moderate signals",
                  ],
                  [
                    "CCT",
                    "All raw p-values",
                    "Robust to arbitrary dependency",
                    "Tail-driven (heavy-tail property)",
                  ],
                  [
                    "HMP",
                    "All raw p-values",
                    "Robust to arbitrary dependency",
                    "Driven by small p-values (harmonic mean)",
                  ],
                ].map(([method, input, dep, sens], i) => (
                  <tr
                    key={method}
                    style={{
                      borderBottom: "1px solid #e5e7eb",
                      background: i % 2 === 0 ? "#f9fafb" : undefined,
                    }}
                  >
                    <td style={{ padding: "6px 10px", fontWeight: 600 }}>
                      {method}
                    </td>
                    <td style={{ padding: "6px 10px" }}>{input}</td>
                    <td style={{ padding: "6px 10px" }}>{dep}</td>
                    <td style={{ padding: "6px 10px" }}>{sens}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            <strong>Fisher and Stouffer</strong> are canonical and
            well-understood. By using pre-collapsed per-table p-values, we
            approximate independence. However, subtle dependencies may still
            exist across datasets.
          </p>
          <p>
            <strong>CCT and HMP</strong> are newer methods designed for unknown
            or complex dependency structures. They use all raw p-values and do
            not require pre-collapse. The trade-off is that they are
            asymptotically valid (accurate for small combined p-values) rather
            than exactly valid at all significance levels.
          </p>
          <p>
            <strong>In practice</strong>, all four methods tend to produce
            similar gene rankings, especially at the top. When they diverge,
            examining which method ranks a gene differently can provide insight:
            for instance, a gene significant under Fisher but not HMP may be
            driven by a single very small p-value from one table.
          </p>
        </section>
        <p style={{ marginTop: 36, textAlign: "right", fontFamily: "serif" }}>
          Johannes Birgmeier, March 3rd, 2026
        </p>
      </main>
      <Footer />
    </>
  );
}
