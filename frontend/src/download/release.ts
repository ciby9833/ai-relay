import { parse } from "yaml";

export type MacArchitecture = "arm64" | "x64";
export interface MacInstaller { href: string; size: number }
export interface MacRelease {
  version: string;
  installers: Record<MacArchitecture, MacInstaller>;
}

// Use the same publication boundary as electron-updater. Never guess a version or
// offer a URL that wasn't included in the published manifest.
export function parseMacRelease(source: string): MacRelease {
  const data = parse(source, { maxAliasCount: 0 }) as unknown;
  if (!data || typeof data !== "object") throw new Error("Invalid release");
  const { version, files } = data as { version?: unknown; files?: unknown };
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(version) || !Array.isArray(files)) {
    throw new Error("Invalid release");
  }
  const installer = (architecture: MacArchitecture): MacInstaller => {
    const filename = `Relay-${version}${architecture === "arm64" ? "-arm64" : ""}.dmg`;
    const file = files.find((entry: unknown) => entry && typeof entry === "object" && "url" in entry && entry.url === filename);
    if (!file || !Number.isSafeInteger(file.size) || file.size <= 0) throw new Error("Incomplete release");
    return { href: `/desktop/${encodeURIComponent(filename)}`, size: file.size };
  };
  return { version, installers: { arm64: installer("arm64"), x64: installer("x64") } };
}

export async function fetchMacRelease(signal: AbortSignal): Promise<MacRelease> {
  const response = await fetch("/desktop/latest-mac.yml", { cache: "no-store", signal });
  if (!response.ok) throw new Error("Release unavailable");
  const source = await response.text();
  if (source.length > 64_000) throw new Error("Invalid release");
  return parseMacRelease(source);
}
