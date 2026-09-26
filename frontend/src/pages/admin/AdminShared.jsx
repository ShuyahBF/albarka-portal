import React from "react";
import { DashboardShared } from "@/pages/portal/Dashboard";
import Documents from "@/pages/portal/Documents";
import Missions from "@/pages/portal/Missions";
import Echeances from "@/pages/portal/Echeances";
import RecentClientsCard from "@/components/RecentClientsCard";

// Simple wrappers that reuse portal pages in staff mode (backend enforces scope).
// Tableau de bord cabinet + « Derniers clients connectés » (Direction, Secrétariat, admin)
export const AdminDashboard = () => (
  <div className="space-y-6">
    <DashboardShared admin />
    <RecentClientsCard />
  </div>
);
export const AdminDocuments = () => <Documents />;
export const AdminMissions = () => <Missions staffMode />;
export const AdminEcheances = () => <Echeances staffMode />;
