import Head from "next/head";
import Link from "next/link";

export default function Home() {
  return (
    <div style={{ padding: 12 }}>
      <Head>
        <title>SSPsyGene</title>
      </Head>
      <h1>SSPsyGene</h1>
      <p>Welcome. Explore phenotype data:</p>
      <ul>
        <li>
          <Link href="/pheno">Phenotypes Home</Link>
        </li>
        <li>
          <Link href="/pheno/deg">
            Mouse Perturb-Seq: Gene/Gene expression changes
          </Link>
        </li>
        <li>
          <Link href="/pheno/comp">
            Mouse Perturb-Seq: Cell type composition changes
          </Link>
        </li>
        <li>
          <Link href="/pheno/sizes">Zebrafish brain region sizes</Link>
        </li>
        <li>
          <Link href="/pheno/perturbFishAstr">
            Perturb-Fish astrocyte expression changes
          </Link>
        </li>
        <li>
          <Link href="/pheno/all">Integrated assays</Link>
        </li>
      </ul>
    </div>
  );
}
