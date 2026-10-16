import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { FolderInfoPage } from "@/pages/FolderInfoPage";
import { FolderMatchingPage } from "@/pages/FolderMatchingPage";
import { HomePage } from "@/pages/HomePage";
import {
  AdvancedSettingsPage,
  DatsSettingsPage,
  PlatformsSettingsPage,
} from "@/pages/SettingsPages";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="folders/:label/matching" element={<FolderMatchingPage />} />
        <Route path="folders/:label/conversion" element={<FolderInfoPage section="Conversion" />} />
        <Route path="folders/:label/discarded" element={<FolderInfoPage section="Discarded" />} />
        <Route path="settings" element={<Navigate to="/settings/platforms" replace />} />
        <Route path="settings/platforms" element={<PlatformsSettingsPage />} />
        <Route path="settings/dats" element={<DatsSettingsPage />} />
        <Route path="settings/advanced" element={<AdvancedSettingsPage />} />
        <Route path="*" element={<p className="text-muted-foreground">Page not found.</p>} />
      </Route>
    </Routes>
  );
}
