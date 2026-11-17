import { FEEDBACK_EMAIL, FEEDBACK_MAILTO } from "@/lib/contact";

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
        Questions, corrections or feedback:{" "}
        <a href={FEEDBACK_MAILTO} style={{ color: "#2563eb" }}>
          {FEEDBACK_EMAIL}
        </a>
      </p>
      <p style={{ margin: "6px 0 0", fontSize: 14 }}>
        © {new Date().getFullYear()} The SSPsyGene Project
      </p>
    </footer>
  );
}
