import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DatSourcesPage } from "@/pages/DatSourcesPage";
import { FolderConversionPage } from "@/pages/FolderConversionPage";
import { FolderDiscardedPage } from "@/pages/FolderDiscardedPage";
import { FolderMatchingPage } from "@/pages/FolderMatchingPage";
import { HomePage } from "@/pages/HomePage";
import { SetsSettingsPage } from "@/pages/SetsSettingsPage";
import {
  AdvancedSettingsPage,
  DatsSettingsPage,
  LookupsSettingsPage,
  PlatformsSettingsPage,
} from "@/pages/SettingsPages";
import { StatisticsPage } from "@/pages/StatisticsPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="statistics" element={<StatisticsPage />} />
        <Route path="folders/:label/matching" element={<FolderMatchingPage />} />
        <Route path="folders/:label/conversion" element={<FolderConversionPage />} />
        <Route path="folders/:label/discarded" element={<FolderDiscardedPage />} />
        <Route path="settings" element={<Navigate to="/settings/dat-sources" replace />} />
        <Route path="settings/dat-sources" element={<DatSourcesPage />} />
        <Route path="settings/folders" element={<SetsSettingsPage />} />
        <Route path="settings/conversion-targets" element={<PlatformsSettingsPage />} />
        {/* The pages' former addresses. */}
        <Route path="settings/sets" element={<Navigate to="/settings/folders" replace />} />
        <Route
          path="settings/platforms"
          element={<Navigate to="/settings/conversion-targets" replace />}
        />
        <Route path="settings/dats" element={<DatsSettingsPage />} />
        <Route path="settings/lookups" element={<LookupsSettingsPage />} />
        <Route path="settings/advanced" element={<AdvancedSettingsPage />} />
        <Route path="*" element={<p className="text-muted-foreground">Page not found.</p>} />
      </Route>
    </Routes>
  );
}
