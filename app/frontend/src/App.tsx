import { Navigate, Route, Routes } from "react-router-dom";

import { ApiError } from "./api/client";
import { useCurrentUser } from "./api/hooks";
import { AppLayout } from "./components/AppLayout";
import { Spinner } from "./components/ui/primitives";
import { CampaignDetailPage } from "./pages/CampaignDetailPage";
import { CampaignListPage } from "./pages/CampaignListPage";
import { LoginPage } from "./pages/LoginPage";
import { NewCampaignPage } from "./pages/NewCampaignPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TemplatesPage } from "./pages/TemplatesPage";

export function App() {
  const { data: user, isPending, error } = useCurrentUser();

  if (isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Checking your session" />
      </div>
    );
  }

  // The session cookie is HttpOnly, so this request is the only way to know
  // whether one exists.
  if (error instanceof ApiError && error.isUnauthenticated) {
    return <LoginPage />;
  }

  if (!user) {
    return <LoginPage error="Could not reach the server. Try again." />;
  }

  return (
    <AppLayout user={user}>
      <Routes>
        <Route path="/" element={<CampaignListPage />} />
        <Route path="/campaigns/new" element={<NewCampaignPage />} />
        <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
        <Route path="/templates" element={<TemplatesPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
