export default function Footer() {
  return (
    <footer
      style={{
        background: "#0f172a",
        borderTop: "1px solid #334155",
        padding: "24px 16px",
        marginTop: "auto",
        textAlign: "center",
        color: "#94a3b8",
      }}
    >
      <p style={{ margin: 0, fontSize: 14 }}>
        © {new Date().getFullYear()} The SSPsyGene Project
      </p>
    </footer>
  );
}

