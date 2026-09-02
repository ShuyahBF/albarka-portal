import React from "react";
import { DashboardShared } from "@/pages/portal/Dashboard";
import Documents from "@/pages/portal/Documents";
import Missions from "@/pages/portal/Missions";
import Echeances from "@/pages/portal/Echeances";

// Simple wrappers that reuse portal pages in staff mode (backend enforces scope).
export const AdminDashboard = () => <DashboardShared admin />;
export const AdminDocuments = () => <Documents />;
export const AdminMissions = () => <Missions staffMode />;
export const AdminEcheances = () => <Echeances staffMode />;
