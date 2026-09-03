import React, { useEffect } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";

import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import PortalLayout from "@/components/PortalLayout";

// Public
import Home from "@/pages/public/Home";
import Missions from "@/pages/public/Missions";
import Contact from "@/pages/public/Contact";

// Auth
import Login from "@/pages/auth/Login";

// Portal (client)
import Dashboard from "@/pages/portal/Dashboard";
import Documents from "@/pages/portal/Documents";
import ClientMissions from "@/pages/portal/Missions";
import ClientEcheances from "@/pages/portal/Echeances";
import Historique from "@/pages/portal/Historique";

// Admin (staff)
import AdminClients from "@/pages/admin/AdminClients";
import AdminStaff from "@/pages/admin/AdminStaff";
import AdminClientDetail from "@/pages/admin/AdminClientDetail";
import AdminReports from "@/pages/admin/AdminReports";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminContacts from "@/pages/admin/AdminContacts";
import { AdminDashboard, AdminDocuments, AdminMissions, AdminEcheances } from "@/pages/admin/AdminShared";

function RootRedirect() {
  const { user, loading, isStaff } = useAuth();
  if (loading) return null;
  if (!user) return <Home />;
  return <Navigate to={isStaff ? "/admin" : "/portal"} replace />;
}

function App() {
  useEffect(() => {
    const APP_TITLE = "ALBARKA Consulting BF";
    document.title = APP_TITLE;
    // Re-assert the title if any external script rewrites it (Emergent injects at runtime).
    const observer = new MutationObserver(() => {
      if (document.title !== APP_TITLE) document.title = APP_TITLE;
    });
    const titleEl = document.querySelector("title");
    if (titleEl) observer.observe(titleEl, { childList: true });
    return () => observer.disconnect();
  }, []);
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster richColors position="top-right" />
        <Routes>
          {/* Public */}
          <Route path="/" element={<RootRedirect />} />
          <Route path="/missions" element={<Missions />} />
          <Route path="/services" element={<Missions />} />
          <Route path="/contact" element={<Contact />} />
          <Route path="/login" element={<Login />} />

          {/* Client portal */}
          <Route path="/portal" element={<ProtectedRoute><PortalLayout admin={false} /></ProtectedRoute>}>
            <Route index element={<Dashboard />} />
            <Route path="documents" element={<Documents />} />
            <Route path="missions" element={<ClientMissions />} />
            <Route path="echeances" element={<ClientEcheances />} />
            <Route path="historique" element={<Historique />} />
          </Route>

          {/* Admin */}
          <Route path="/admin" element={<ProtectedRoute staffOnly><PortalLayout admin /></ProtectedRoute>}>
            <Route index element={<AdminDashboard />} />
            <Route path="clients" element={<AdminClients />} />
            <Route path="clients/:id" element={<AdminClientDetail />} />
            <Route path="contacts" element={<AdminContacts />} />
            <Route path="staff" element={<AdminStaff />} />
            <Route path="documents" element={<AdminDocuments />} />
            <Route path="missions" element={<AdminMissions />} />
            <Route path="echeances" element={<AdminEcheances />} />
            <Route path="rapports" element={<AdminReports />} />
            <Route path="settings" element={<AdminSettings />} />
            <Route path="paie" element={<AdminEcheances />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
