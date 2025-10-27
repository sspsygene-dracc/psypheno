export default function Footer() {
  return (
    <footer
      style={{
        background: "#ffffff",
        borderTop: "1px solid #e5e7eb",
        padding: "24px 16px",
        marginTop: "auto",
        textAlign: "center",
        color: "#6b7280",
      }}
    >
      <p style={{ margin: 0, fontSize: 14 }}>
        © {new Date().getFullYear()} The SSPsyGene Project
      </p>
    </footer>
  );
}

