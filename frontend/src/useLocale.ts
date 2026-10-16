import { useSyncExternalStore } from "react";
import { getLanguageSnapshot, getLocale, getPreference, setLanguagePreference, subscribeLanguage } from "./i18n";

export function useLocale() {
  useSyncExternalStore(subscribeLanguage, getLanguageSnapshot, getLanguageSnapshot);
  return { locale: getLocale(), preference: getPreference(), setPreference: setLanguagePreference };
}
