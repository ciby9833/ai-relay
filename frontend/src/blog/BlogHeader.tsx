import { createElement } from "react";
import { useLocale } from "../useLocale";

export default function BlogHeader() {
  const { locale } = useLocale();
  return createElement("relay-blog-navigation", { lang: locale, current: "articles" });
}
