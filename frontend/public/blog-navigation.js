// Shared by the React blog index and original HTML articles.
// Shadow DOM keeps article CSS and navigation CSS independent.
(() => {
  const copy = {
    zh: ["文章", "打开 Relay", "博客导航"],
    en: ["Articles", "Open Relay", "Blog navigation"],
    id: ["Artikel", "Buka Relay", "Navigasi blog"],
  };
  class BlogNavigation extends HTMLElement {
    static get observedAttributes() { return ["lang", "current", "full-bleed"]; }
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
            position: sticky;
            top: 0;
            z-index: 100;
            flex-shrink: 0;
            --nav-bg: var(--bg, #faf9f5);
            --nav-text: var(--text, #141413);
            --nav-border: var(--border, #e8e6dc);
            --nav-accent: var(--accent, #c96442);
            --nav-accent-hover: var(--accent-hover, #b4583a);
            --nav-accent-text: var(--accent-text, #fff);
          }
          @media (prefers-color-scheme: dark) {
            :host {
              --nav-bg: var(--bg, #262624);
              --nav-text: var(--text, #f5f4ef);
              --nav-border: var(--border, #3e3e38);
              --nav-accent: var(--accent, #d97757);
              --nav-accent-hover: var(--accent-hover, #e38a6c);
              --nav-accent-text: var(--accent-text, #1f1e1d);
            }
          }
          * { box-sizing: border-box; }
          header {
            background: var(--nav-bg); color: var(--nav-text);
            border-bottom: 1px solid var(--nav-border);
            font: 15px/1.65 -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif;
            -webkit-font-smoothing: antialiased;
          }
          .inner {
            width: min(100% - 80px, 1280px); margin-inline: auto; min-height: 88px;
            display: flex; justify-content: space-between; align-items: center; gap: 24px;
          }
          a { color: inherit; text-decoration: none; }
          .brand { display: inline-flex; align-items: center; gap: 10px; font: 600 25px/1 "Source Serif 4", "Songti SC", "Noto Serif SC", Georgia, serif; }
          .mark { color: var(--nav-accent); width: 26px; height: 26px; flex-shrink: 0; }
          nav { display: flex; align-items: center; gap: 32px; }
          .open {
            display: inline-flex; align-items: center; gap: 6px; height: 42px; padding: 0 18px;
            border: 1px solid transparent; border-radius: 8px; font-size: 14px; font-weight: 500;
            white-space: nowrap; background: var(--nav-accent); color: var(--nav-accent-text);
          }
          .open:hover { background: var(--nav-accent-hover); }
          .external { width: 15px; height: 15px; flex-shrink: 0; }
          a:focus-visible { outline: 2px solid var(--nav-accent); outline-offset: 4px; }
          @media (max-width: 760px) {
            .inner { width: calc(100% - 32px); min-height: 76px; gap: 14px; flex-wrap: wrap; padding-block: 16px; }
            nav { gap: 16px; }
            .open { padding-inline: 12px; }
          }
        </style>
        <header>
          <div class="inner">
            <a class="brand" href="/">
              <svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c.6 4.8 2.6 8.8 10 10-7.4 1.2-9.4 5.2-10 10-.6-4.8-2.6-8.8-10-10 7.4-1.2 9.4-5.2 10-10z" fill="currentColor"/></svg>
              <span>Relay</span>
            </a>
            <nav>
              <a class="articles" href="/blog/"></a>
              <a class="open" href="/"><span></span><svg class="external" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6 M20 4l-9 9 M18 14v6H4V6h6"/></svg></a>
            </nav>
          </div>
        </header>`;
      this.update = this.update.bind(this);
      this.fit = this.fit.bind(this);
      this.resizeObserver = new ResizeObserver(() => this.updateScrollOffset());
    }
    connectedCallback() {
      this.previousScrollPadding = document.documentElement.style.scrollPaddingTop;
      this.update();
      this.fit();
      this.resizeObserver.observe(this);
      this.updateScrollOffset();
      window.addEventListener("storage", this.update);
      window.addEventListener("languagechange", this.update);
      window.addEventListener("resize", this.fit);
    }
    disconnectedCallback() {
      this.resizeObserver.disconnect();
      document.documentElement.style.scrollPaddingTop = this.previousScrollPadding ?? "";
      window.removeEventListener("storage", this.update);
      window.removeEventListener("languagechange", this.update);
      window.removeEventListener("resize", this.fit);
    }
    attributeChangedCallback() { this.update(); this.fit(); }
    updateScrollOffset() {
      // Keep in-page links and keyboard-focused content clear of the persistent header.
      document.documentElement.style.scrollPaddingTop = `${this.getBoundingClientRect().height + 16}px`;
    }
    update() {
      let language = this.getAttribute("lang");
      if (!language) {
        try { language = localStorage.getItem("relay.ui-language"); } catch { /* Use system preference. */ }
      }
      if (!["zh", "en", "id"].includes(language)) language = navigator.languages?.[0] || navigator.language;
      language = (language || "en").toLowerCase().split(/[-_]/)[0];
      const [articles, open, navigation] = copy[language] || copy.en;
      this.shadowRoot.querySelector(".articles").textContent = articles;
      this.shadowRoot.querySelector(".open span").textContent = open;
      this.shadowRoot.querySelector("nav").setAttribute("aria-label", navigation);
      this.shadowRoot.querySelector("header").lang = copy[language] ? language : "en";
      const link = this.shadowRoot.querySelector(".articles");
      if (this.getAttribute("current") === "articles") link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    fit() {
      if (!this.isConnected || !this.hasAttribute("full-bleed")) return;
      this.style.minHeight = "0";
      // Article bodies may have their own gutters. Leave them intact and make only the nav full width.
      this.style.marginLeft = "0";
      this.style.width = "100%";
      const left = this.getBoundingClientRect().left;
      this.style.marginLeft = `${-left}px`;
      this.style.width = `${document.documentElement.clientWidth}px`;
    }
  }
  if (!customElements.get("relay-blog-navigation")) customElements.define("relay-blog-navigation", BlogNavigation);
})();
