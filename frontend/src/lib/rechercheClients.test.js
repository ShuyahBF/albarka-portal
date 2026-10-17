/* Lot 29 — recherche dans la liste des clients : société, téléphone, responsable. */
import { filtrerClients } from "./rechercheClients";

const CLIENTS = [
  { id: "1", full_name: "DR DEHAINSALA HAIENGDA", company: "MEDIPHARM SARL", phone: "0022678049669", whatsapp_number: "0022678049669" },
  { id: "2", full_name: "Aïcha Ouédraogo", company: "Société Étoile du Faso", phone: "+226 70 11 22 33", whatsapp_number: "" },
  { id: "3", full_name: "Boukary Zongo", company: "", phone: "", whatsapp_number: "+226 76 55 44 33" },
];
const ids = (q) => filtrerClients(CLIENTS, q).map((c) => c.id);

test("recherche vide : tous les clients", () => {
  expect(ids("")).toEqual(["1", "2", "3"]);
  expect(ids("   ")).toEqual(["1", "2", "3"]);
});

test("par nom de société, sans tenir compte des accents ni des majuscules", () => {
  expect(ids("medipharm")).toEqual(["1"]);
  expect(ids("societe etoile")).toEqual(["2"]);
  expect(ids("ÉTOILE FASO")).toEqual(["2"]);
});

test("par nom du responsable (plusieurs mots, dans n'importe quel ordre)", () => {
  expect(ids("aicha")).toEqual(["2"]);
  expect(ids("zongo boukary")).toEqual(["3"]);
  expect(ids("dehainsala")).toEqual(["1"]);
});

test("par numéro de téléphone ou WhatsApp, écrit comme on veut", () => {
  expect(ids("78 04 96 69")).toEqual(["1"]);
  expect(ids("+226 78049669")).toEqual(["1"]);
  expect(ids("0022670112233")).toEqual(["2"]);
  expect(ids("76-55-44")).toEqual(["3"]);        // numéro WhatsApp seul
  expect(ids("999")).toEqual([]);
});

test("un chiffre isolé n'est pas pris pour un numéro", () => {
  expect(ids("3")).toEqual([]);                   // ni « Société 3 » ni un numéro : trop court pour être un numéro
});
