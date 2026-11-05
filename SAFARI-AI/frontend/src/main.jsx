import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

// The admin dashboard is its own bundle; visitors never download it.
const AdminApp = lazy(() => import("./admin/AdminApp"));
const isAdmin = /^\/admin(\/|$)/.test(window.location.pathname);

createRoot(document.getElementById("root")).render(
  <StrictMode>
    {isAdmin ? (
      <Suspense fallback={null}>
        <AdminApp />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>
);
