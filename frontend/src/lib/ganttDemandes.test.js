// Tests du diagramme de Gantt des demandes à SAWALI (logique pure).
import { barreGantt, bornesGantt, dateEstimee, enMs, positionAujourdhui } from "./ganttDemandes";

const NOW = new Date("2026-11-17T12:00:00").getTime();
const J = 86400000;
const demande = (extra) => ({ id: "d", demandee_le: "2026-11-10T08:00:00", statut: "remontee", ...extra });

test("dates : jour seul, datetime, illisible", () => {
  expect(enMs("2026-11-17")).toBe(new Date("2026-11-17T12:00:00").getTime());
  expect(enMs("2026-11-10T08:00:00")).toBe(new Date("2026-11-10T08:00:00").getTime());
  expect(enMs("n'importe quoi")).toBeNull();
  expect(enMs(null)).toBeNull();
});

test("date estimée selon le statut", () => {
  expect(dateEstimee(demande({ prevue_le: "2026-11-30" }))).toBe(enMs("2026-11-30"));
  expect(dateEstimee(demande({ statut: "realisee", realisee_le: "2026-11-15", prevue_le: "2026-11-30" }))).toBe(enMs("2026-11-15"));
  expect(dateEstimee(demande({ statut: "refusee", prevue_le: "2026-11-30" }))).toBeNull();
  expect(dateEstimee(demande({}))).toBeNull();
});

test("axe commun : de la plus ancienne demande à la plus lointaine date, aujourd'hui compris", () => {
  const ds = [demande({ prevue_le: "2026-12-10" }), demande({ demandee_le: "2026-11-01T08:00:00", prevue_le: "2026-11-20" })];
  const b = bornesGantt(ds, NOW);
  expect(b.debut).toBe(new Date("2026-11-01T08:00:00").getTime());
  expect(b.fin).toBeGreaterThan(enMs("2026-12-10"));
  expect(positionAujourdhui(b, NOW)).toBeGreaterThan(0);
  expect(positionAujourdhui(b, NOW)).toBeLessThan(100);
  expect(bornesGantt([], NOW).fin - bornesGantt([], NOW).debut).toBeGreaterThanOrEqual(7 * J);      // axe jamais nul
});

test("barre « prévue » : bleue, dans N jours", () => {
  const d = demande({ prevue_le: "2026-11-27" });
  const b = bornesGantt([d], NOW);
  const r = barreGantt(d, b, NOW);
  expect(r.etat).toBe("prevue"); expect(r.jours).toBe(10); expect(r.libelle).toContain("dans 10 j");
  expect(r.gauche).toBe(0); expect(r.largeur).toBeGreaterThan(50);
});

test("barre en retard : date prévue dépassée", () => {
  const d = demande({ prevue_le: "2026-11-14" });
  const r = barreGantt(d, bornesGantt([d], NOW), NOW);
  expect(r.etat).toBe("en_retard"); expect(r.jours).toBeLessThan(0); expect(r.libelle).toContain("dépassée");
});

test("barre réalisée : verte jusqu'à la date de réalisation", () => {
  const d = demande({ statut: "realisee", realisee_le: "2026-11-15" });
  const r = barreGantt(d, bornesGantt([d], NOW), NOW);
  expect(r.etat).toBe("realisee"); expect(r.libelle).toContain("Réalisée le");
});

test("sans date, refusée, à remonter", () => {
  const ds = [demande({}), demande({ statut: "refusee" }), demande({ statut: "a_remonter" })];
  const b = bornesGantt(ds, NOW);
  expect(barreGantt(ds[0], b, NOW).etat).toBe("sans_date");
  expect(barreGantt(ds[1], b, NOW).etat).toBe("refusee");
  const r = barreGantt(ds[2], b, NOW);
  expect(r.etat).toBe("a_remonter"); expect(r.largeur).toBe(0);
});

test("une barre reste visible même très courte et dans les bornes", () => {
  const d = demande({ demandee_le: "2026-11-17T08:00:00", prevue_le: "2026-11-17" });
  const r = barreGantt(d, bornesGantt([d], NOW), NOW);
  expect(r.largeur).toBeGreaterThanOrEqual(1.5); expect(r.gauche + r.largeur).toBeLessThanOrEqual(100.0001);
});
