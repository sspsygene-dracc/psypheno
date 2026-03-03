import Link from "next/link";
import { useRouter } from "next/router";
import { useState, useEffect, useRef } from "react";

const NAV_LINKS = [
  { href: "/", label: "Home" },
  { href: "/all-datasets", label: "All Datasets" },
  { href: "/all-genes", label: "All Genes" },
  { href: "/combined-pvalues", label: "Combined P-values" },
  { href: "/dataset-changelog", label: "Changelog" },
];

const MOBILE_BREAKPOINT = 700;

export default function Header() {
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // Close menu on route change
  useEffect(() => {
    setMenuOpen(false);
  }, [router.pathname]);

  // Close menu when clicking outside
  useEffect(() => {
    if (!menuOpen) return;
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [menuOpen]);

  const linkStyle = (path: string) => ({
    padding: "10px 20px",
    color: router.pathname === path ? "#2563eb" : "#374151",
    textDecoration: "none",
    fontWeight: 600,
    borderBottom:
      router.pathname === path ? "2px solid #2563eb" : "2px solid transparent",
    transition: "all 0.2s ease",
  });

  const mobileLinkStyle = (path: string) => ({
    display: "block",
    padding: "12px 20px",
    color: router.pathname === path ? "#2563eb" : "#374151",
    textDecoration: "none",
    fontWeight: 600,
    background: router.pathname === path ? "#eff6ff" : "transparent",
    borderLeft:
      router.pathname === path ? "3px solid #2563eb" : "3px solid transparent",
  });

  return (
    <header
      style={{
        background: "#ffffff",
        borderBottom: "1px solid #e5e7eb",
        padding: "16px 0",
        position: "relative",
      }}
    >
      <style>{`
        .header-nav-desktop { display: flex; gap: 8px; }
        .header-menu-btn { display: none; }
        @media (max-width: ${MOBILE_BREAKPOINT}px) {
          .header-nav-desktop { display: none !important; }
          .header-menu-btn { display: flex !important; }
        }
      `}</style>
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
          <Link href="/" style={{ textDecoration: "none", cursor: "pointer" }}>
            <img
              src="/1763-ssPsyGeneLogo_v2_A.png"
              alt="SSPsyGene Logo"
              style={{
                width: 120,
                height: "auto",
                borderRadius: 8,
                transition: "opacity 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.opacity = "0.8";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.opacity = "1";
              }}
            />
          </Link>
        </div>

        {/* Desktop nav */}
        <nav className="header-nav-desktop">
          {NAV_LINKS.map(({ href, label }) => (
            <Link key={href} href={href} style={linkStyle(href)}>
              {label}
            </Link>
          ))}
        </nav>

        {/* Mobile hamburger button */}
        <div ref={menuRef} style={{ position: "relative" }}>
          <button
            className="header-menu-btn"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Toggle navigation menu"
            aria-expanded={menuOpen}
            style={{
              background: "none",
              border: "1px solid #d1d5db",
              borderRadius: 6,
              padding: "8px 10px",
              cursor: "pointer",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#374151"
              strokeWidth="2"
              strokeLinecap="round"
            >
              {menuOpen ? (
                <>
                  <line x1="6" y1="6" x2="18" y2="18" />
                  <line x1="6" y1="18" x2="18" y2="6" />
                </>
              ) : (
                <>
                  <line x1="3" y1="6" x2="21" y2="6" />
                  <line x1="3" y1="12" x2="21" y2="12" />
                  <line x1="3" y1="18" x2="21" y2="18" />
                </>
              )}
            </svg>
          </button>

          {/* Mobile dropdown menu */}
          {menuOpen && (
            <nav
              style={{
                position: "absolute",
                top: "calc(100% + 8px)",
                right: 0,
                background: "#ffffff",
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                boxShadow: "0 4px 12px rgba(0,0,0,0.1)",
                minWidth: 200,
                zIndex: 1000,
                overflow: "hidden",
              }}
            >
              {NAV_LINKS.map(({ href, label }) => (
                <Link key={href} href={href} style={mobileLinkStyle(href)}>
                  {label}
                </Link>
              ))}
            </nav>
          )}
        </div>
      </div>
    </header>
  );
}
