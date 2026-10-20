import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Blog from "./blog/Blog";
// 衬线字体随前端一起打包，不依赖 Google Fonts（国内经常加载不到）
import "@fontsource/source-serif-4/latin-500.css";
import "@fontsource/source-serif-4/latin-600.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/^\/blog\/?$/.test(window.location.pathname) ? <Blog /> : <App />}
  </StrictMode>,
);
