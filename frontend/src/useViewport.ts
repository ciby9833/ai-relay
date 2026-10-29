import { useLayoutEffect } from "react";

/** Keep app controls above the software keyboard, including iOS Safari where
 * the visual viewport shrinks without resizing the layout viewport. */
export function useViewport() {
  useLayoutEffect(() => {
    const viewport = window.visualViewport;
    const root = document.documentElement;
    const update = () => {
      // Pinch zoom is a viewing preference, not a keyboard/layout resize.
      if (viewport && Math.abs(viewport.scale - 1) > 0.01) return;
      const height = viewport?.height ?? window.innerHeight;
      root.style.setProperty("--app-height", `${height}px`);
      root.toggleAttribute("data-short-viewport", height <= 500);
    };
    update();
    viewport?.addEventListener("resize", update);
    window.addEventListener("resize", update);
    return () => {
      viewport?.removeEventListener("resize", update);
      window.removeEventListener("resize", update);
      root.style.removeProperty("--app-height");
      root.removeAttribute("data-short-viewport");
    };
  }, []);
}
