import type { CSSProperties } from "react";
import {
  IN_VITRO,
  ROLE,
  STATUS,
  TAG,
  TAG_DESCRIPTION,
  TAG_NAME,
  type TagDimension,
} from "@/lib/palette";

const pill: CSSProperties = {
  borderRadius: 9999,
  padding: "0 7px",
  fontSize: 11,
  lineHeight: 1.6,
  whiteSpace: "nowrap",
  cursor: "help",
};

/**
 * One-line key to the pill colours, built from the same palette constants as
 * the pills themselves. Each sample's tooltip starts with its dimension name.
 */
export default function PillLegend({
  dimensions,
  inVitro = false,
  roles = false,
  status = false,
  style,
}: {
  /** Tag dimensions shown on this page, in display order. */
  dimensions: TagDimension[];
  /** Add the dashed "in vitro" model-system sample. */
  inVitro?: boolean;
  /** Add the perturbed / measured gene-role samples. */
  roles?: boolean;
  /** Add an outlined "status" sample (badges like "SSPsyGene", "int"). */
  status?: boolean;
  style?: CSSProperties;
}) {
  return (
    <div
      data-pill-legend
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 4,
        fontSize: 11,
        color: "#6b7280",
        ...style,
      }}
    >
      <span style={{ marginRight: 2 }}>Pill colours:</span>
      {dimensions.map((d) => (
        <span key={d} title={TAG_DESCRIPTION[d]} style={{ ...pill, ...TAG[d] }}>
          {TAG_NAME[d]}
        </span>
      ))}
      {inVitro && (
        <span
          title={`${TAG_NAME.modelSystem}: in vitro (organoids, cultured cells), drawn with a dashed border, here and on the brain drawing`}
          style={{ ...pill, ...IN_VITRO.pill }}
        >
          In vitro
        </span>
      )}
      {roles && (
        <>
          <span
            title="Gene role: perturbed, the gene a dataset knocked out / down, activated or mutated"
            style={{ ...pill, ...ROLE.perturbed }}
          >
            Perturbed gene
          </span>
          <span
            title="Gene role: target, a gene measured as a readout"
            style={{ ...pill, ...ROLE.measured }}
          >
            Target / measured gene
          </span>
        </>
      )}
      {status && (
        <span
          title="Status: outlined badges mark a state, not a property of the data (e.g. SSPsyGene-funded, not on the public site)"
          style={{ ...pill, ...STATUS.funded }}
        >
          Status
        </span>
      )}
    </div>
  );
}
