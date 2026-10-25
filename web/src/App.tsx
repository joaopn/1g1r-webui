import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { DatSourcesPage } from "@/pages/DatSourcesPage";
import { FolderConversionPage } from "@/pages/FolderConversionPage";
import { FolderDiscardedPage } from "@/pages/FolderDiscardedPage";
import { FolderIgnoredPage } from "@/pages/FolderIgnoredPage";
import { FolderMatchingPage } from "@/pages/FolderMatchingPage";
import { FolderRenamePage } from "@/pages/FolderRenamePage";
import { FolderUpdatesPage } from "@/pages/FolderUpdatesPage";
import { HomePage } from "@/pages/HomePage";
import { RomsetManagementPage } from "@/pages/RomsetManagementPage";
import { AdvancedSettingsPage, DatsSettingsPage, LookupsSettingsPage } from "@/pages/SettingsPages";
import { StatisticsPage } from "@/pages/StatisticsPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="statistics" element={<StatisticsPage />} />
        <Route path="folders/:label" element={<Navigate to="matching" replace />} />
        <Route path="folders/:label/matching" element={<FolderMatchingPage />} />
        <Route path="folders/:label/conversion" element={<FolderConversionPage />} />
        <Route path="folders/:label/discarded" element={<FolderDiscardedPage />} />
        <Route path="folders/:label/ignored" element={<FolderIgnoredPage />} />
        <Route path="folders/:label/updates" element={<FolderUpdatesPage />} />
        <Route path="folders/:label/rename" element={<FolderRenamePage />} />
        <Route path="settings" element={<Navigate to="/settings/dat-sources" replace />} />
        <Route path="settings/dat-sources" element={<DatSourcesPage />} />
        <Route path="settings/romsets" element={<RomsetManagementPage />} />
        {/* The pages' former addresses. */}
        {["sets", "folders", "platforms", "conversion-targets"].map((old) => (
          <Route
            key={old}
            path={`settings/${old}`}
            element={<Navigate to="/settings/romsets" replace />}
          />
        ))}
        <Route path="settings/dats" element={<DatsSettingsPage />} />
        <Route path="settings/lookups" element={<LookupsSettingsPage />} />
        <Route path="settings/advanced" element={<AdvancedSettingsPage />} />
        <Route path="*" element={<p className="text-muted-foreground">Page not found.</p>} />
      </Route>
    </Routes>
  );
}
