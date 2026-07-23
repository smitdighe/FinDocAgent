import { createBrowserRouter } from "react-router-dom";
import { App } from "./App";
import { EvalDashboard } from "@/features/eval/EvalDashboard";

export const router = createBrowserRouter([
  { path: "/", element: <App /> },
  { path: "/eval", element: <EvalDashboard /> },
]);
