/*
  Paie (lot 8) — petits éléments communs aux écrans de paie :
    - fcfa()          : montant en francs CFA sans décimales (« 297 000 ») ;
    - useEmployers()  : liste des employeurs (personnel du cabinet + clients) ;
    - EmployerSelect  : liste déroulante de l'employeur ;
    - MonthInput      : mois de paie (AAAA-MM), par défaut le mois précédent.
*/
import React, { useEffect, useState } from "react";
import { apiClient } from "@/lib/api";

export const GREEN = "#0F6B4A";

// Montant sans décimales, espaces de milliers
export const fcfa = (v) => (v === null || v === undefined || v === "" ? "—" : Math.round(Number(v)).toLocaleString("fr-FR"));

// Mois précédent au format AAAA-MM (période de paie la plus courante)
export const previousMonth = () => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export function useEmployers(reloadKey = 0) {
  const [items, setItems] = useState([]);
  useEffect(() => {
    apiClient.get("/hr/paie/employeurs").then(({ data }) => setItems(data.items || [])).catch(() => setItems([]));
  }, [reloadKey]);
  return items;
}

export function EmployerSelect({ value, onChange, employers, testId = "paie-employer" }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}
      className="h-10 rounded-md border border-input bg-white px-3 text-sm min-w-[16rem]">
      <option value="">— Choisir l'employeur —</option>
      {employers.map((e) => (
        <option key={e.employer_id} value={e.employer_id}>
          {e.kind === "cabinet" ? `🏢 ${e.name} (personnel du cabinet)` : e.name} · {e.employees_count} salarié(s)
        </option>
      ))}
    </select>
  );
}

export function MonthInput({ value, onChange, testId = "paie-month" }) {
  return (
    <input type="month" value={value} onChange={(e) => onChange(e.target.value)} data-testid={testId}
      className="h-10 rounded-md border border-input bg-white px-3 text-sm" />
  );
}
