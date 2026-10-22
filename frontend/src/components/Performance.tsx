import { useEffect, useState } from "react";
import { api, type PerformanceData, type PerformanceSeries } from "../api";
import { intlLocale, t } from "../i18n";
import Icon from "./Icon";

const numeric = (v: number | null | undefined, unit = "") => v == null ? "—" : `${v.toLocaleString(intlLocale(), { maximumFractionDigits: 1 })}${unit}`;
function bytes(value: number | null | undefined, rate = false): string {
  if (value == null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let n = value, i = 0;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return numeric(n, ` ${units[i]}${rate ? "/s" : ""}`);
}
const seconds = (v: number | null | undefined) => v == null ? "—" : v > 0 && v < 1 ? numeric(v * 1000, " ms") : v < 60 ? numeric(v, " s") : v < 3600 ? numeric(v / 60, " min") : numeric(v / 3600, " h");
const stamp = (v: number) => new Date(v * 1000).toLocaleString(intlLocale());
const last = (row?: PerformanceSeries) => row?.points.at(-1)?.[1] ?? null;

function Card({ title, value, note }: { title: string; value: string; note?: string }) {
  return <article className="admin-metric"><h3>{title}</h3><div className="admin-metric-value"><strong>{value}</strong></div>{note && <p className="muted small">{note}</p>}</article>;
}

function Trend({ title, rows = [], start, end, step, format }: { title: string; rows?: PerformanceSeries[]; start: number; end: number; step: number; format: (v: number | null) => string }) {
  const values = rows.flatMap(r => r.points.map(p => p[1]).filter((v): v is number => v !== null));
  const max = Math.max(1, ...values), min = values.length ? Math.min(...values) : null;
  const paths = rows.map(row => {
    let previous = 0;
    return row.points.map(([at, value]) => {
      if (value === null) { previous = 0; return ""; }
      const command = previous && at - previous <= step * 1.5 ? "L" : "M";
      previous = at;
      return `${command}${((at - start) / Math.max(1, end - start) * 600).toFixed(1)},${(90 - value / max * 80).toFixed(1)}`;
    }).join(" ");
  });
  return <article className="perf-trend"><div className="admin-section-head"><h3>{title}</h3><span className="muted small">{values.length ? `${format(min)} – ${format(Math.max(...values))}` : t("adminNoSample")}</span></div>
    {values.length ? <svg viewBox="0 0 600 100" role="img" aria-label={title} preserveAspectRatio="none"><title>{title}</title>
      <path d="M0 90H600" className="perf-baseline" />{paths.map((d, i) => <path key={i} d={d} className="perf-line" />)}</svg> : <p className="empty-note">{t("perfNoHistory")}</p>}
    <div className="perf-chart-time muted small"><span>{stamp(start)}</span><span>{stamp(end)}</span></div>
  </article>;
}

export default function Performance() {
  const [window, setWindow] = useState("1h"), [revision, setRevision] = useState(0);
  const [data, setData] = useState<PerformanceData | null>(null), [error, setError] = useState("");
  const [disk, setDisk] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let busy = false;
    setData(null); setError("");
    async function refresh() {
      if (busy || controller.signal.aborted) return;
      busy = true;
      try {
        const next = await api.performance(window, controller.signal);
        if (!controller.signal.aborted) { setData(next); setError(""); }
      } catch (err) {
        if (!controller.signal.aborted) { setData(null); setError(err instanceof Error ? err.message : t("loadError")); }
      } finally {
        busy = false;
        if (!controller.signal.aborted) timer = setTimeout(() => { if (!document.hidden) void refresh(); }, 30000);
      }
    }
    const visible = () => { if (!document.hidden) { clearTimeout(timer); void refresh(); } };
    document.addEventListener("visibilitychange", visible);
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", visible); };
  }, [window, revision]);
  const rows = (key: string) => data?.current[key] ?? [];
  const value = (key: string, label?: string, match?: string) => last(rows(key).find(r => !label || r.labels[label] === match));
  const appComplete = ["api", "worker", "feishu"].every(job => data?.targets[job] === "up" && (value("heartbeat_age", "job", job) ?? Infinity) < 45);
  const services = ["api", "worker", "feishu", "db", "web", "prometheus", "node-exporter", "cadvisor"];
  const disks = [...new Set([...rows("disk_read"), ...rows("disk_write"), ...(data?.history.disk_read ?? []), ...(data?.history.disk_write ?? [])].map(r => r.labels.device).filter(Boolean))].sort();
  const selectedDisk = disks.includes(disk) ? disk : disks[0];
  const providers = [...new Set([...rows("llm_p95"), ...rows("llm_calls")].map(r => r.labels.provider))].sort();
  const sumCalls = (provider: string, outcomes?: string[]) => {
    const found = rows("llm_calls").filter(r => r.labels.provider === provider && (!outcomes || outcomes.includes(r.labels.outcome)));
    if (!found.length || found.some(r => last(r) === null)) return null;
    return found.reduce((n, r) => n + last(r)!, 0);
  };
  const failureRate = (provider: string) => {
    const completed = sumCalls(provider, ["success", "error", "timeout", "limited"]);
    const failures = sumCalls(provider, ["error", "timeout", "limited"]);
    return completed && failures !== null ? numeric(100 * failures / completed, "%") : "—";
  };
  const chart = { start: data?.start ?? 0, end: data?.end ?? 0, step: data?.step ?? 30 };
  return <main className="thread"><div className="thread-scroll"><div className="admin-page perf-page">
    <header className="admin-header"><h1>{t("perfTitle")}</h1><div className="admin-controls">
      <select aria-label={t("perfWindow")} value={window} onChange={e => setWindow(e.target.value)}>{["1h", "24h", "7d"].map(w => <option value={w} key={w}>{t(`perfWindow.${w}`)}</option>)}</select>
      <button className="btn secondary" onClick={() => setRevision(n => n + 1)}><Icon name="refresh" />{t("adminRefresh")}</button>
    </div></header>
    {error ? <div role="alert"><p className="error-text">{error}</p><button className="btn secondary" onClick={() => setRevision(n => n + 1)}>{t("retry")}</button></div>
      : !data ? <p role="status" className="muted">{t("loading")}</p>
      : data.status === "disabled" ? <div className="perf-notice" role="status"><p>{t("perfDisabled")}</p><p className="muted small">{t("perfEnableHint")}</p></div> : <>
        <p className="muted small">{t("perfRefreshHint")} · {data.collected_at ? stamp(data.collected_at) : "—"}</p>
        {data.status !== "ok" && <p className="perf-notice" role="status">{t(`perfStatus.${data.status}`)}</p>}
        <section aria-label={t("perfHost")}>
          <div className="admin-section-head"><h2>{t("perfHost")}</h2><span className="muted small">{t("perfHostSample")}: {value("host_sample") ? stamp(value("host_sample")!) : "—"}</span></div>
          <div className="admin-metrics">
            <Card title="CPU" value={numeric(value("cpu"), "%")} note={`${t("perfCores")}: ${numeric(value("cores"))} · ${t("perfLoad")}: ${numeric(value("load"))}`} />
            <Card title={t("perfMemory")} value={numeric(value("memory"), "%")} note={`${t("perfAvailable")}: ${bytes(value("memory_available"))} / ${bytes(value("memory_total"))}`} />
            <Card title="Swap" value={bytes(value("swap_used"))} note={`${t("perfTotal")}: ${bytes(value("swap_total"))}`} />
            <Card title="GPU" value="—" note={t("perfGpu")} />
          </div>
          <div className="perf-charts">
            <Trend title={t("perfCpuTrend")} rows={data.history.cpu} {...chart} format={v => numeric(v, "%")} />
            <Trend title={t("perfMemoryTrend")} rows={data.history.memory} {...chart} format={v => numeric(v, "%")} />
          </div>
          <details className="perf-details"><summary>{t("perfCpuDetails")}</summary><div className="perf-core-list">{rows("cpu_core").map(r => <span key={r.labels.cpu}>CPU {r.labels.cpu}: {numeric(last(r), "%")}</span>)}</div>
            <p className="muted small">I/O wait: {numeric(value("iowait"), "%")} · {t("perfOom")}: {numeric(value("oom"))}</p></details>
        </section>
        <section><div className="admin-section-head"><h2>{t("perfDisks")}</h2></div>
          <div className="admin-table-wrap" tabIndex={0} role="region" aria-label={t("perfDisks")}><table><thead><tr><th>{t("perfMount")}</th><th>{t("perfAvailable")}</th><th>{t("perfTotal")}</th></tr></thead>
            <tbody>{rows("disk_total").map((r, i) => <tr key={i}><th scope="row">{r.labels.mountpoint}<small className="muted perf-device">{r.labels.device}</small></th><td>{bytes(last(rows("disk_free").find(f => f.labels.mountpoint === r.labels.mountpoint && f.labels.device === r.labels.device)))}</td><td>{bytes(last(r))}</td></tr>)}</tbody></table></div>
          {!rows("disk_total").length && <p className="empty-note">{t("adminNoSample")}</p>}
          <div className="admin-section-head"><label>{t("perfDiskDevice")}<select aria-label={t("perfDiskDevice")} value={selectedDisk ?? ""} onChange={e => setDisk(e.target.value)} disabled={!disks.length}>
            {!disks.length && <option value="">{t("adminNoSample")}</option>}{disks.map(device => <option key={device} value={device}>{device}</option>)}</select></label>
            <span className="muted small">{t("perfDiskLatency")}: {seconds(selectedDisk ? value("disk_latency", "device", selectedDisk) : null)}</span></div>
          <p className="muted small">{t("perfDiskDeviceHint")}</p>
          <div className="perf-charts"><Trend title={`${t("perfDiskRead")}${selectedDisk ? ` · ${selectedDisk}` : ""}`} rows={(data.history.disk_read ?? []).filter(r => r.labels.device === selectedDisk)} {...chart} format={v => bytes(v, true)} /><Trend title={`${t("perfDiskWrite")}${selectedDisk ? ` · ${selectedDisk}` : ""}`} rows={(data.history.disk_write ?? []).filter(r => r.labels.device === selectedDisk)} {...chart} format={v => bytes(v, true)} /></div>
          <details className="perf-details"><summary>{t("perfDiskHistory")}</summary>{(data.history.disk_free ?? []).map((r, i) => <Trend key={i} title={r.labels.mountpoint || r.labels.device} rows={[r]} {...chart} format={bytes} />)}</details>
        </section>
        <section><div className="admin-section-head"><h2>{t("perfServices")}</h2></div><p className="muted small">{t("perfServiceHint")}</p>
          <div className="admin-table-wrap" tabIndex={0} role="region" aria-label={t("perfServices")}><table><thead><tr><th>{t("perfService")}</th><th>{t("perfCpuCores")}</th><th>{t("perfMemory")}</th><th>{t("perfObserved")}</th><th>{t("perfHeartbeat")}</th></tr></thead><tbody>{services.map(service => {
            const seen = value("service_seen", "service", service), age = value("heartbeat_age", "job", service);
            const observed = seen != null && data.collected_at != null && data.collected_at - seen < 90 && data.targets.cadvisor === "up";
            return <tr key={service}><th scope="row">{service}</th><td>{observed ? numeric(value("service_cpu", "service", service)) : "—"}</td><td>{observed ? bytes(value("service_memory", "service", service)) : "—"}</td><td>{t(observed ? "perfSeen" : "perfMissing")}</td><td>{["api", "worker", "feishu"].includes(service) ? <span className={age == null || age > 45 || data.targets[service] !== "up" ? "error-text" : ""}>{data.targets[service] === "up" ? seconds(age) : t("perfMissing")}</span> : "—"}</td></tr>;
          })}</tbody></table></div>
          <div className="perf-charts"><Trend title={t("perfNetworkRx")} rows={data.history.network_rx} {...chart} format={v => bytes(v, true)} /><Trend title={t("perfNetworkTx")} rows={data.history.network_tx} {...chart} format={v => bytes(v, true)} /></div>
        </section>
        <section><div className="admin-section-head"><h2>{t("perfTasks")}</h2><span className="muted small">{t("perfLastCycle")}: {data.targets.worker === "up" ? seconds(value("worker_cycle_age")) : "—"}</span></div>
          {!appComplete && <p className="muted small">{t("perfIncomplete")}</p>}
          <div className="admin-metrics">
            <Card title={t("perfTurns")} value={appComplete ? numeric(value("inflight", "kind", "turn")) : "—"} note={`P95 (5 min): ${seconds(value("turn_p95"))}`} />
            <Card title={t("perfLlmActive")} value={appComplete ? numeric(value("inflight", "kind", "llm")) : "—"} note={`${t("perfToolP95")}: ${seconds(value("tool_p95"))}`} />
            {(["scheduled", "missions"] as const).map(kind => <Card key={kind} title={t(`perfDue.${kind}`)} value={numeric(data.queue?.[kind]?.due)} note={`${t("perfOldest")}: ${seconds(data.queue?.[kind]?.oldest_seconds)}`} />)}
          </div><p className="muted small">{t("perfQueueHint")}</p>
        </section>
        <section><div className="admin-section-head"><h2>{t("perfModels")}</h2></div><p className="muted small">{t("perfModelHint")}</p>
          <div className="admin-table-wrap" tabIndex={0} role="region" aria-label={t("perfModels")}><table><thead><tr><th>{t("perfProvider")}</th><th>{t("perfCalls")}</th><th>{t("perfErrors")}</th><th>{t("perfFailureRate")}</th><th>{t("perfLimited")}</th><th>{t("perfTimeout")}</th><th>{t("perfFirst")}</th><th>{t("perfDuration")}</th><th>{t("perfTokens")}</th></tr></thead><tbody>{providers.map(provider => <tr key={provider}><th scope="row">{provider}</th><td>{numeric(sumCalls(provider))}</td><td>{numeric(sumCalls(provider, ["error", "timeout", "limited"]))}</td><td>{failureRate(provider)}</td><td>{numeric(sumCalls(provider, ["limited"]))}</td><td>{numeric(sumCalls(provider, ["timeout"]))}</td><td>{seconds(value("llm_first", "provider", provider))}</td><td>{seconds(value("llm_p95", "provider", provider))}</td><td>{numeric(last(rows("tokens").find(r => r.labels.provider === provider && r.labels.direction === "input")))} / {numeric(last(rows("tokens").find(r => r.labels.provider === provider && r.labels.direction === "output")))}</td></tr>)}</tbody></table></div>
          {!providers.length && <p className="empty-note">{t("adminNoSample")}</p>}
        </section>
        <details className="perf-details"><summary>{t("perfCollection")}</summary><ul>{Object.entries(data.targets).map(([job, state]) => <li key={job}>{job}: {t(`perfTarget.${state}`)}</li>)}{rows("node_collectors").map(row => <li key={row.labels.collector}>node / {row.labels.collector}: {t(last(row) === 1 ? "perfCollectorOk" : "perfCollectorFailed")}</li>)}</ul><p className="muted small">{t("perfDefinitions")}</p></details>
      </>}
  </div></div></main>;
}
