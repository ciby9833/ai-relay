import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Blog from "./blog/Blog";
import Invite from "./components/Invite";
import { lazy, Suspense } from 'react';
const MascotGallery = lazy(() => import('./mascot/Gallery'));
// 衬线字体随前端一起打包，不依赖 Google Fonts（国内经常加载不到）
import "@fontsource/source-serif-4/latin-500.css";
import "@fontsource/source-serif-4/latin-600.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/^\/mascot\/?$/.test(window.location.pathname) ? <Suspense fallback={null}><MascotGallery /></Suspense>
      : /^\/blog\/?$/.test(window.location.pathname) ? <Blog />
      : /^\/invite\/[\w-]+$/.test(window.location.pathname) ? <Invite token={window.location.pathname.split("/")[2]} /> : <App />}
  </StrictMode>,
);
