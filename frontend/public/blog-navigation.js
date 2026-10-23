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
      // Keep in-page links and keyboard-focused content clear of the persistent header
      // (and of the collapsed table-of-contents bar on narrow screens).
      const toc = document.querySelector("relay-blog-toc");
      const extra = toc && typeof toc.stickyHeight === "function" ? toc.stickyHeight() : 0;
      document.documentElement.style.scrollPaddingTop = `${this.getBoundingClientRect().height + extra + 16}px`;
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

  // Table of contents for original HTML articles, built from the article's own <h2> headings.
  // Wide screens: fixed in the left margin. Narrow screens: a collapsible bar under the navigation.
  // The stored article is not changed; headings without an id get one at runtime.
  const tocCopy = { zh: ["目录", "展开目录", "收起目录"], en: ["Contents", "Show contents", "Hide contents"], id: ["Daftar isi", "Tampilkan daftar isi", "Sembunyikan daftar isi"] };
  const SIDEBAR = 200; // width of the left column
  const GAP = 32; // space between the column and the article text
  const MIN_HEADINGS = 4; // shorter (landing-style) pages read fine without contents
  class BlogToc extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: none; --toc-text: var(--ink, var(--text, #141413)); --toc-muted: var(--muted, #73726c);
            --toc-rule: var(--rule, var(--border, #e2dfd3)); --toc-accent: var(--accent, #c96442); --toc-bg: var(--paper, var(--bg, #faf9f5)); }
          @media (prefers-color-scheme: dark) {
            :host { --toc-text: var(--ink, var(--text, #f5f4ef)); --toc-muted: var(--muted, #a3a199);
              --toc-rule: var(--rule, var(--border, #3e3e38)); --toc-accent: var(--accent, #d97757); --toc-bg: var(--paper, var(--bg, #262624)); }
          }
          :host([mode="side"]) { display: block; height: 0; }
          :host([mode="bar"]) { display: block; position: sticky; z-index: 90; }
          * { box-sizing: border-box; }
          .root { font: 14px/1.5 -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", sans-serif;
            -webkit-font-smoothing: antialiased; color: var(--toc-muted); }
          .title { font-size: 12px; font-weight: 600; letter-spacing: .06em; color: var(--toc-muted); margin: 0 0 10px 14px; }
          ol { list-style: none; margin: 0; padding: 0; }
          li { margin: 0; }
          a { display: block; color: inherit; text-decoration: none; padding: 5px 0 5px 12px; border-left: 2px solid var(--toc-rule); }
          a:hover { color: var(--toc-text); }
          a[aria-current="true"] { color: var(--toc-text); font-weight: 600; border-left-color: var(--toc-accent); }
          a:focus-visible, button:focus-visible { outline: 2px solid var(--toc-accent); outline-offset: 2px; }
          /* Wide screens */
          .side { position: fixed; width: ${SIDEBAR}px; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; }
          :host(:not([mode="side"])) .side { display: none; }
          /* Narrow screens */
          .bar { display: none; background: var(--toc-bg); border-bottom: 1px solid var(--toc-rule); position: relative; }
          :host([mode="bar"]) .bar { display: block; }
          .toggle { all: unset; box-sizing: border-box; display: flex; align-items: center; gap: 10px; width: 100%; min-height: 44px;
            padding: 0 16px; cursor: pointer; color: var(--toc-text); }
          .toggle b { font-weight: 600; flex: none; }
          .toggle .current { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--toc-muted); }
          .chev { width: 16px; height: 16px; flex: none; transition: transform .15s; }
          .toggle[aria-expanded="true"] .chev { transform: rotate(180deg); }
          .panel { position: absolute; left: 0; right: 0; top: 100%; background: var(--toc-bg); border-bottom: 1px solid var(--toc-rule);
            padding: 8px 16px 14px; max-height: 60vh; overflow-y: auto; box-shadow: 0 8px 16px rgb(0 0 0 / .08); }
          .panel[hidden] { display: none; }
          .panel a { padding-block: 8px; }
          @media (prefers-reduced-motion: reduce) { .chev { transition: none; } }
        </style>
        <div class="root">
          <nav class="side"><p class="title"></p><ol></ol></nav>
          <div class="bar">
            <button class="toggle" type="button" aria-expanded="false">
              <b></b><span class="current"></span>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>
            </button>
            <nav class="panel" hidden><ol></ol></nav>
          </div>
        </div>`;
      this.layout = this.layout.bind(this);
      this.onScroll = this.onScroll.bind(this);
      this.onDocumentClick = this.onDocumentClick.bind(this);
      this.onKey = this.onKey.bind(this);
      this.headings = [];
      this.active = -1;
    }
    connectedCallback() {
      const lang = (document.documentElement.lang || "en").toLowerCase().split(/[-_]/)[0];
      const [title, show, hide] = tocCopy[lang] || tocCopy.en;
      this.labels = { show, hide };
      this.shadowRoot.querySelector(".title").textContent = title;
      this.shadowRoot.querySelector(".toggle b").textContent = title;
      this.shadowRoot.querySelector(".side").setAttribute("aria-label", title);
      this.shadowRoot.querySelector(".panel").setAttribute("aria-label", title);
      this.toggle = this.shadowRoot.querySelector(".toggle");
      this.toggle.setAttribute("aria-label", show);
      this.toggle.addEventListener("click", () => this.setOpen(this.toggle.getAttribute("aria-expanded") !== "true"));
      // Wait for the rest of the document so every heading exists.
      if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => this.build(), { once: true });
      else this.build();
    }
    disconnectedCallback() {
      window.removeEventListener("scroll", this.onScroll);
      window.removeEventListener("resize", this.layout);
      document.removeEventListener("click", this.onDocumentClick);
      document.removeEventListener("keydown", this.onKey);
      this.resizeObserver?.disconnect();
    }
    build() {
      this.headings = [...document.querySelectorAll("body h2")].filter(h => h.textContent.trim() && !h.closest("relay-blog-navigation, relay-blog-toc"));
      if (this.headings.length < MIN_HEADINGS) { this.removeAttribute("mode"); return; }
      const used = new Set([...document.querySelectorAll("[id]")].map(node => node.id));
      this.headings.forEach((heading, index) => {
        if (heading.id) return;
        let id = `section-${index + 1}`;
        while (used.has(id)) id += "-";
        used.add(id);
        heading.id = id;
      });
      for (const list of this.shadowRoot.querySelectorAll("ol")) {
        list.replaceChildren(...this.headings.map((heading, index) => {
          const item = document.createElement("li");
          const link = document.createElement("a");
          link.href = `#${encodeURIComponent(heading.id)}`;
          link.textContent = heading.textContent.replace(/\s+/g, " ").trim();
          link.addEventListener("click", event => { event.preventDefault(); this.go(index); });
          item.append(link);
          return item;
        }));
      }
      this.resizeObserver = new ResizeObserver(this.layout);
      this.resizeObserver.observe(document.body);
      const navigation = document.querySelector("relay-blog-navigation");
      if (navigation) this.resizeObserver.observe(navigation);
      window.addEventListener("scroll", this.onScroll, { passive: true });
      window.addEventListener("resize", this.layout);
      document.addEventListener("click", this.onDocumentClick);
      document.addEventListener("keydown", this.onKey);
      this.layout();
    }
    navHeight() {
      const navigation = document.querySelector("relay-blog-navigation");
      return navigation ? navigation.getBoundingClientRect().height : 0;
    }
    stickyHeight() {
      return this.getAttribute("mode") === "bar" ? this.shadowRoot.querySelector(".bar").getBoundingClientRect().height : 0;
    }
    layout() {
      if (this.headings.length < MIN_HEADINGS) return;
      // Measure where the article text starts; the column goes in the space to its left.
      const textLeft = Math.min(...this.headings.map(heading => heading.getBoundingClientRect().left));
      const side = textLeft >= SIDEBAR + GAP + 16;
      const mode = side ? "side" : "bar";
      if (this.getAttribute("mode") !== mode) {
        this.setAttribute("mode", mode);
        this.setOpen(false);
      }
      const top = this.navHeight();
      if (side) {
        this.style.cssText = "";
        const panel = this.shadowRoot.querySelector(".side");
        panel.style.left = `${textLeft - GAP - SIDEBAR}px`;
        panel.style.top = `${top + 40}px`;
        panel.style.maxHeight = `calc(100vh - ${top + 64}px)`;
      } else {
        // Full width like the navigation, even inside the article's own side gutters.
        this.style.top = `${top}px`;
        this.style.marginLeft = "0";
        this.style.width = "100%";
        const left = this.getBoundingClientRect().left;
        this.style.marginLeft = `${-left}px`;
        this.style.width = `${document.documentElement.clientWidth}px`;
      }
      document.querySelector("relay-blog-navigation")?.updateScrollOffset?.();
      this.onScroll();
    }
    onScroll() {
      if (this.frame) return;
      this.frame = requestAnimationFrame(() => {
        this.frame = 0;
        const line = this.navHeight() + this.stickyHeight() + 24;
        let active = 0;
        this.headings.forEach((heading, index) => { if (heading.getBoundingClientRect().top <= line) active = index; });
        const atBottom = innerHeight + scrollY >= document.documentElement.scrollHeight - 2;
        if (atBottom && scrollY > 0) active = this.headings.length - 1;
        this.setActive(active);
      });
    }
    setActive(index) {
      if (index === this.active) return;
      this.active = index;
      for (const list of this.shadowRoot.querySelectorAll("ol")) {
        [...list.querySelectorAll("a")].forEach((link, i) => {
          if (i === index) link.setAttribute("aria-current", "true"); else link.removeAttribute("aria-current");
        });
      }
      this.shadowRoot.querySelector(".toggle .current").textContent = this.headings[index]?.textContent.replace(/\s+/g, " ").trim() || "";
      // Keep the highlighted entry visible inside a long side column.
      const side = this.shadowRoot.querySelector(".side");
      const link = side.querySelectorAll("a")[index];
      if (this.getAttribute("mode") === "side" && link) {
        const box = side.getBoundingClientRect(), item = link.getBoundingClientRect();
        if (item.top < box.top || item.bottom > box.bottom) side.scrollTop += item.top - box.top - box.height / 2;
      }
    }
    go(index) {
      const heading = this.headings[index];
      if (!heading) return;
      this.setOpen(false);
      const smooth = !matchMedia("(prefers-reduced-motion: reduce)").matches;
      heading.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
      history.replaceState(null, "", `#${encodeURIComponent(heading.id)}`);
      this.setActive(index);
    }
    setOpen(open) {
      if (!this.toggle) return;
      this.toggle.setAttribute("aria-expanded", String(open));
      this.toggle.setAttribute("aria-label", open ? this.labels.hide : this.labels.show);
      this.shadowRoot.querySelector(".panel").hidden = !open;
    }
    onDocumentClick(event) {
      if (!event.composedPath().includes(this)) this.setOpen(false);
    }
    onKey(event) {
      if (event.key === "Escape" && this.toggle?.getAttribute("aria-expanded") === "true") { this.setOpen(false); this.toggle.focus(); }
    }
  }
  if (!customElements.get("relay-blog-toc")) customElements.define("relay-blog-toc", BlogToc);
})();
