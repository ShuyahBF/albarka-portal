// Application du pilote ALBARKA : routage minimal (login + espace client
// + vue cabinet), séparé de l'App.js hérité de Sawali qui reste en place
// comme référence pour les prochaines phases du portail.
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider, useAuth } from "@/pilot/AuthContext";
import Login from "@/pilot/pages/Login";
import ClientPortal from "@/pilot/pages/ClientPortal";
import StaffOverview from "@/pilot/pages/StaffOverview";

function Home() {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  const isClient = (user.roles || []).includes("client");
  return isClient ? <ClientPortal /> : <StaffOverview />;
}

function RequireAuth({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function PilotApp() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<RequireAuth><Home /></RequireAuth>} />
        </Routes>
      </BrowserRouter>
      <Toaster />
    </AuthProvider>
  );
}
