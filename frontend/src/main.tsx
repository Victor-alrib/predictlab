import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./index.css";
import Layout from "./components/Layout";
import { DatasetProvider } from "./lib/dataset";
import About from "./pages/About";
import Alerts from "./pages/Alerts";
import Analysis from "./pages/Analysis";
import Dashboard from "./pages/Dashboard";
import ImportPage from "./pages/Import";
import Maintenance from "./pages/Maintenance";
import Models from "./pages/Models";
import Reports from "./pages/Reports";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <DatasetProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/importacao" element={<ImportPage />} />
            <Route path="/analise" element={<Analysis />} />
            <Route path="/manutencao" element={<Maintenance />} />
            <Route path="/modelos" element={<Models />} />
            <Route path="/alertas" element={<Alerts />} />
            <Route path="/relatorios" element={<Reports />} />
            <Route path="/sobre" element={<About />} />
            <Route path="*" element={<Dashboard />} />
          </Routes>
        </Layout>
      </DatasetProvider>
    </BrowserRouter>
  </StrictMode>,
);
