import { messages } from "./locales/messages";
import { common } from "./locales/common";

export type Locale = "en" | "zh" | "id";
export type LanguagePreference = Locale | "auto";
export interface LocalizedText { key: string; values?: Record<string, string | number> }
const STORAGE_KEY = "relay.ui-language";
const listeners = new Set<() => void>();

export function resolveLocale(language?: string | null): Locale {
  const base = language?.trim().toLowerCase().split(/[-_]/)[0];
  return base === "zh" || base === "id" || base === "en" ? base : "en";
}

function validPreference(value: unknown): value is LanguagePreference {
  return value === "auto" || value === "en" || value === "zh" || value === "id";
}

function readPreference(): LanguagePreference {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return validPreference(value) ? value : "auto";
  } catch {
    return "auto";
  }
}

let preference = readPreference();
const systemLocale = () => resolveLocale(typeof navigator === "undefined" ? null : navigator.languages?.[0] || navigator.language);
let locale: Locale = preference === "auto" ? systemLocale() : preference;

export const getLocale = () => locale;
export const getPreference = () => preference;
export const getLanguageSnapshot = () => `${preference}:${locale}`;
export const intlLocale = () => ({ en: "en-US", zh: "zh-CN", id: "id-ID" })[locale];

function notify() {
  locale = preference === "auto" ? systemLocale() : preference;
  if (typeof document !== "undefined") document.documentElement.lang = locale === "zh" ? "zh-CN" : locale;
  listeners.forEach((listener) => listener());
}

export function setLanguagePreference(next: LanguagePreference) {
  if (!validPreference(next)) return;
  preference = next;
  try { localStorage.setItem(STORAGE_KEY, next); } catch { /* Still apply for this session. */ }
  notify();
}

export function subscribeLanguage(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

if (typeof window !== "undefined") {
  window.addEventListener("languagechange", notify);
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY || event.key === null) {
      preference = readPreference();
      notify();
    }
  });
}
notify();

/** Translate application copy only; never pass user-authored content here. */
export function t(key: string, values: Record<string, string | number> = {}): string {
  const pluralKey = typeof values.count === "number" ? `${key}.${new Intl.PluralRules(intlLocale()).select(values.count)}` : key;
  const entry = common[pluralKey] ?? common[key];
  const source = entry
    ? entry[locale === "zh" ? 0 : locale === "en" ? 1 : 2]
    : locale === "zh" ? key : messages[key]?.[locale === "en" ? 0 : 1] ?? messages[key]?.[0] ?? key;
  return source.replace(/\{(\w+)\}/g, (placeholder, name: string) => {
    const value = values[name];
    return value === undefined ? placeholder : typeof value === "number" ? new Intl.NumberFormat(intlLocale()).format(value) : value;
  });
}

/** Optional server descriptors allow UI updates without translating stored business content. */
export function localize(message: LocalizedText | null | undefined, fallback: string): string {
  return message && (common[message.key] || messages[message.key]) ? t(message.key, message.values) : fallback;
}
