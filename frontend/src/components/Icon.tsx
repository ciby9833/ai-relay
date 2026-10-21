// 线性图标（24 网格，1.75 描边），风格参照 lucide
const PATHS: Record<string, string> = {
  chart: "M4 3v17h17 M8 16v-5 M13 16V7 M18 16V4",
  mail: "M4 6h16v12H4z M4 7l8 6 8-6",
  calendar: "M5 5h14v15H5z M5 10h14 M9 3v4 M15 3v4",
  approval: "M9 4h6v3H9z M7 5H5v16h14V5h-2 M9 13l2 2 4-4",
  doc: "M7 3h7l5 5v13H7z M14 3v5h5 M10 13h6 M10 17h6",
  bell: "M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z M10 20a2 2 0 0 0 4 0",
  draft: "M4 20h4L19 9l-4-4L4 16z M13.5 6.5l4 4",
  check: "M5 12l4.5 4.5L19 7",
  copy: "M9 9h11v11H9z M5 15H4V4h11v1",
  x: "M6 6l12 12 M18 6L6 18",
  arrowUp: "M12 19V5 M6 11l6-6 6 6",
  plus: "M12 5v14 M5 12h14",
  home: "M4 11l8-7 8 7 M6 10v10h12V10",
  menu: "M4 7h16 M4 12h16 M4 17h16",
  memory: "M12 4a5 5 0 0 0-5 5c0 1.6.8 3 2 4v3h6v-3c1.2-1 2-2.4 2-4a5 5 0 0 0-5-5z M10 20h4",
  clock: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16z M12 8v4l3 2",
  settings: "M4 7h10 M18 7h2 M4 17h4 M12 17h8 M14 5v4 M8 15v4",
  refresh: "M20 11a8 8 0 0 0-14.5-4.5L4 8 M4 4v4h4 M4 13a8 8 0 0 0 14.5 4.5L20 16 M20 20v-4h-4",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z M12 2v2 M12 20v2 M4.9 4.9l1.4 1.4 M17.7 17.7l1.4 1.4 M2 12h2 M20 12h2 M4.9 19.1l1.4-1.4 M17.7 6.3l1.4-1.4",
  external: "M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6",
  video: "M3 7h12v10H3z M15 10l6-3v10l-6-3",
  pin: "M12 21s-6-5.5-6-10a6 6 0 0 1 12 0c0 4.5-6 10-6 10z M12 9a2 2 0 1 0 0 4 2 2 0 0 0 0-4z",
  alert: "M12 4l9 16H3z M12 10v4 M12 17v.5",
  logout: "M14 4h5v16h-5 M10 8l-4 4 4 4 M6 12h10",
  trash: "M5 7h14 M9 7V4h6v3 M7 7l1 13h8l1-13",
  chevron: "M9 6l6 6-6 6",
};

export default function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg
      className="icon-svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name] ?? ""} />
    </svg>
  );
}

/** Relay 标识：一个四芒星，暗示“替你留意” */
export function RelayMark({ size = 20 }: { size?: number }) {
  return (
    <svg className="relay-mark" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2c.6 4.8 2.6 8.8 10 10-7.4 1.2-9.4 5.2-10 10-.6-4.8-2.6-8.8-10-10 7.4-1.2 9.4-5.2 10-10z" fill="currentColor" />
    </svg>
  );
}
