import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

export default function ProtectedRoute({ children, staffOnly = false, supervisorOnly = false }) {
  const { user, loading, isStaff, isSupervisor } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-8 h-8 rounded-full border-2 border-[hsl(var(--primary))] border-t-transparent animate-spin" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (supervisorOnly && !isSupervisor) return <Navigate to="/portal" replace />;
  if (staffOnly && !isStaff) return <Navigate to="/portal" replace />;
  return children;
}
