import Link from "next/link";
import { useRouter } from "next/router";

export default function Header() {
  const router = useRouter();

  const linkStyle = (path: string) => ({
    padding: "10px 20px",
    color: router.pathname === path ? "#60a5fa" : "#e5e7eb",
    textDecoration: "none",
    fontWeight: 600,
    borderBottom: router.pathname === path ? "2px solid #60a5fa" : "2px solid transparent",
    transition: "all 0.2s ease",
  });

  return (
    <header
      style={{
        background: "#0f172a",
        borderBottom: "1px solid #334155",
        padding: "16px 0",
      }}
    >
      <div
        style={{
          maxWidth: "1200px",
          margin: "0 auto",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0 16px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <img
            src="/1763-ssPsyGeneLogo_v2_A.png"
            alt="SSPsyGene Logo"
            style={{
              width: 120,
              height: "auto",
              borderRadius: 8,
            }}
          />
        </div>
        <nav style={{ display: "flex", gap: 8 }}>
          <Link href="/" style={linkStyle("/")}>
            Home
          </Link>
          <Link href="/all-datasets" style={linkStyle("/all-datasets")}>
            All Datasets
          </Link>
          <Link href="/all-genes" style={linkStyle("/all-genes")}>
            All Genes
          </Link>
        </nav>
      </div>
    </header>
  );
}

