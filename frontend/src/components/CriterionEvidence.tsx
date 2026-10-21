import type { MissionCriterion } from "../api";
import { t } from "../i18n";

function comparison(item: MissionCriterion): string | null {
  if (!item.rule) return null;
  const target = item.rule.operator === "decrease" ? item.baseline?.value : item.rule.target;
  if (target === null || target === undefined) return null;
  const sign = { decrease: "<", lt: "<", lte: "≤", eq: "=", gte: "≥", gt: ">" }[item.rule.operator];
  return `${sign} ${target}`;
}

/** Display each observation once; technical references remain available beside evidence. */
export default function CriterionEvidence({ item }: { item: MissionCriterion }) {
  const observed = item.outcome?.observation;
  const evidence = item.outcome?.detail || item.evidence;
  const threshold = comparison(item);
  return <div className="criterion-proof">
    {item.rule && <p className="muted small">{item.rule.scope} · {item.rule.cell}{threshold && ` · ${threshold}`}</p>}
    {observed ? <p className="small">{item.baseline
      ? t("proofReading", { baseline: item.baseline.value, value: observed.value })
      : t("proofCurrent", { value: observed.value })} · {t(item.outcome?.ok ? "proofPassed" : "proofFailed")}</p>
      : evidence && <p className="small">{evidence}</p>}
    {item.requirement === "business" && !item.rule && <p className="small error-text">{t("proofUnbound")}</p>}
    {item.rule?.operator === "decrease" && !item.baseline && <p className="small error-text">{t("proofBaselineMissing")}</p>}
    {item.ref && <span className="muted small">{item.ref}</span>}
  </div>;
}
