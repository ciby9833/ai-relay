import { useEffect, useRef, useState } from "react";
import Icon, { RelayMark } from "../components/Icon";
import LanguageSelect from "../components/LanguageSelect";
import { useLocale } from "../useLocale";
import { downloadCopy } from "./copy";
import { fetchMacRelease, type MacArchitecture, type MacRelease } from "./release";
import "./download.css";

type Feature = "files" | "notifications" | "permissions";
const featureOrder: Feature[] = ["files", "notifications", "permissions"];

function MotionControl({ playing, label, onClick }: { playing: boolean; label: string; onClick: () => void }) {
  return <button className="download-motion-control" type="button" onClick={onClick} aria-label={label} title={label}>
    <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      {playing ? <path d="M4 3h3v10H4zM9 3h3v10H9z" /> : <path d="m5 3 8 5-8 5z" />}
    </svg>
  </button>;
}

export default function Download() {
  const { locale } = useLocale();
  const c = downloadCopy(locale);
  const [architecture, setArchitecture] = useState<MacArchitecture>("arm64");
  const [release, setRelease] = useState<MacRelease | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [feature, setFeature] = useState<Feature>("files");
  const [paused, setPaused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  const [visible, setVisible] = useState(() => !document.hidden);
  const [previewVisible, setPreviewVisible] = useState(false);
  const preview = useRef<HTMLElement>(null);
  const playing = !paused && !reducedMotion;
  useEffect(() => {
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(preference.matches);
    const updateVisibility = () => setVisible(!document.hidden);
    const observer = new IntersectionObserver(([entry]) => setPreviewVisible(entry.isIntersecting), { threshold: .25 });
    if (preview.current) observer.observe(preview.current);
    preference.addEventListener("change", updateMotion);
    document.addEventListener("visibilitychange", updateVisibility);
    return () => {
      observer.disconnect();
      preference.removeEventListener("change", updateMotion);
      document.removeEventListener("visibilitychange", updateVisibility);
    };
  }, []);
  useEffect(() => {
    if (!playing || !visible || !previewVisible) return;
    const timer = window.setTimeout(() => setFeature(featureOrder[(featureOrder.indexOf(feature) + 1) % featureOrder.length]), 6500);
    return () => window.clearTimeout(timer);
  }, [feature, playing, visible, previewVisible]);
  useEffect(() => { document.title = c("title"); }, [locale]);
  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 12_000);
    let active = true;
    setFailed(false);
    setRelease(null);
    void fetchMacRelease(controller.signal).then(value => { if (active) setRelease(value); })
      .catch(() => { if (active) setFailed(true); })
      .finally(() => window.clearTimeout(timeout));
    return () => { active = false; controller.abort(); window.clearTimeout(timeout); };
  }, [attempt]);
  const installer = release?.installers[architecture];
  const chip = c(architecture === "arm64" ? "apple" : "intel");
  const features = [
    { id: "files", icon: "file", label: c("tabFiles"), title: c("local"), body: c("localBody") },
    { id: "notifications", icon: "bell", label: c("tabNotifications"), title: c("notice"), body: c("noticeBody") },
    { id: "permissions", icon: "settings", label: c("tabPermissions"), title: c("access"), body: c("accessBody") },
  ] as const;
  const selected = features.find(item => item.id === feature)!;

  const motionControl = !reducedMotion && <MotionControl playing={playing} label={c(playing ? "pauseMotion" : "playMotion")} onClick={() => setPaused(value => !value)} />;

  return <div className="download-page" data-motion={playing && visible}>
    <header className="download-header">
      <a className="download-brand" href="/" aria-label="Relay"><RelayMark size={34} /><span>Relay</span></a>
      <nav aria-label={c("nav")}>
        <a href="#features" className="download-nav-features">{c("features")}</a>
        <a href="/" className="download-web">{c("web")} <Icon name="external" size={14} /></a>
      </nav>
    </header>

    <main>
      <section className="download-hero" aria-labelledby="download-title" data-mascot-theme="dark">
        <div className="download-hero-grid" aria-hidden="true" />
        <div className="download-hero-content">
          <p className="download-eyebrow"><span />{c("eyebrow")}</p>
          <h1 id="download-title">{c("headline")}<br /><span>{c("headlineAccent")}</span></h1>
          <p className="download-intro">{c("intro")}</p>
          <fieldset className="download-chip-picker">
            <legend className="download-sr-only">{c("architecture")}</legend>
            {(["arm64", "x64"] as const).map(arch => <label key={arch}>
              <input type="radio" name="architecture" value={arch} checked={architecture === arch} onChange={() => setArchitecture(arch)} />
              <span>{c(arch === "arm64" ? "apple" : "intel")}</span>
            </label>)}
          </fieldset>
          <div className="download-action" aria-live="polite">
            {installer ? <a className="download-primary" href={installer.href} aria-label={`${c("downloadMac")} · ${chip}`}>
              <Icon name="download" size={20} />{c("downloadMac")}<Icon name="chevron" size={16} />
            </a> : failed ? <div className="download-error" role="alert">
              <span>{c("unavailable")}</span><button onClick={() => setAttempt(value => value + 1)}>{c("retry")}</button>
            </div> : <button className="download-primary" disabled>{c("loading")}</button>}
            <p className="download-release">{release && installer ? `v${release.version} · ${chip} · ${Math.round(installer.size / 1_000_000)} MB · ` : ""}macOS 13+</p>
          </div>
          <details className="download-chip-help"><summary>{c("chipHelp")}</summary><p>{c("chipAnswer")}</p></details>
        </div>
        <div className="download-orbit" aria-hidden="true">
          <div className="download-orbit-ring" /><div className="download-orbit-ring inner" />
          <div className="download-orbit-mascot"><RelayMark size={240} emotionId="idle" animated={playing && visible} /></div>
          <span className="download-orbit-file file-pdf"><Icon name="file" size={20} />PDF</span>
          <span className="download-orbit-file file-xlsx"><Icon name="chart" size={20} />XLSX</span>
          <span className="download-orbit-file file-docx"><Icon name="doc" size={20} />DOCX</span>
          <div className="download-orbit-spark spark-one" /><div className="download-orbit-spark spark-two" />
        </div>
        <div className="download-hero-controls">{motionControl}</div>
      </section>

      <section ref={preview} className="download-features download-section" id="features" aria-label={c("features")} data-preview-motion={playing && visible && previewVisible}>
        <div className="download-feature-layout">
          <div className="download-feature-copy">
            <div className="download-feature-switch" role="group" aria-label={c("demo")}>
              {features.map(item => <button key={item.id} aria-pressed={feature === item.id} aria-controls="feature-preview" onClick={() => { setFeature(item.id); setPaused(true); }}>
                <Icon name={item.icon} size={18} />{item.label}
              </button>)}
            </div>
            <h2>{selected.title}</h2><p>{selected.body}</p>
          </div>
          <div className="download-showcase" id="feature-preview" role="region" aria-label={`${c("demo")} · ${selected.label}`}>
            <div className="download-demo-label">{c("demo")}{motionControl}</div>
            <div className="download-demo-window" key={feature}>
              <div className="download-demo-titlebar"><span className="download-traffic" aria-hidden="true"><i /><i /><i /></span><span>Relay</span><Icon name="panel" size={15} /></div>
              {feature === "files" ? <div className="download-demo-chat">
                <span className="download-folder"><Icon name="file" />{c("folder")}</span>
                <div className="download-demo-request">{c("request")}</div>
                <div className="download-demo-reply"><RelayMark size={32} /><div><strong>Relay</strong><p>{c("response")}</p>
                  <div className="download-demo-output"><Icon name="chart" size={22} /><span>{c("output")}<small>XLSX</small></span><Icon name="check" /></div>
                </div></div>
              </div> : feature === "notifications" ? <div className="download-demo-notifications">
                <div className="download-demo-menubar"><span>{c("menu")}</span><RelayMark size={21} /><span>09:45</span></div>
                <div className="download-demo-notification"><RelayMark size={42} /><div><strong>Relay</strong><p>{c("notification")}</p></div><small>{c("now")}</small></div>
                <RelayMark size={90} emotionId="idle" />
              </div> : <div className="download-demo-access">
                <h4>{c("thisMac")}</h4><div className="download-folder"><Icon name="file" />{c("folder")}</div>
                <div className="download-permission-row">{c("read")}<span className="download-demo-toggle" aria-hidden="true" /></div>
                <div className="download-permission-row">{c("write")}<span className="download-demo-toggle" aria-hidden="true" /></div>
                <p><Icon name="check" size={15} />{c("accessNote")}</p>
              </div>}
            </div>
            <div className="download-scene-progress" aria-hidden="true" key={`progress-${feature}`}><span /></div>
          </div>
        </div>
      </section>

    </main>
    <footer className="download-footer">
      <a href="/" className="download-brand"><RelayMark size={30} /><span>Relay</span></a>
      <LanguageSelect />
    </footer>
  </div>;
}
