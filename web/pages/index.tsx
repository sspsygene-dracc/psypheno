import Link from 'next/link';

export default function PhenoHome() {
  return (
    <div style={{ padding: 12 }}>
      <h1>SSPsyGene Phenotype Knowledgebase</h1>
      <h3>Individual assays:</h3>
      <p>
        <Link href="/pheno/deg">Xin Jin: Mouse Perturb-Seq Gene/Gene expression changes</Link>
      </p>
      <p>
        <Link href="/pheno/comp">Xin Jin: Mouse Perturb-Seq Gene/Cell type composition changes</Link>
      </p>
      <p>
        <Link href="/pheno/sizes">Ellen Hoffman: Zebrafish Brain Region Sizes - Gene/Brain Size</Link>
      </p>
      <p>
        <Link href="/pheno/perturbFishAstr">Sami Farhi: Human Astrocyte Perturb-Fish Expr Changes - Gene/Gene</Link>
      </p>
      <h3>All assays:</h3>
      <p>
        <Link href="/pheno/all">Integrated assays</Link>
      </p>
    </div>
  );
}
