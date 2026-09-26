/*
  RichTextEditor — éditeur de texte « comme Word » (lot 7), sans dépendance.

  Barre de mise en forme :
    annuler / rétablir · style (paragraphe, titres) · police · taille ·
    gras, italique, souligné, barré · couleur du texte, surlignage ·
    alignements (gauche, centre, droite, justifié) · puces, numéros ·
    retrait − / + · tableau (insertion + ajout/suppression de lignes et de
    colonnes) · image (redimensionnée, largeur réglable) · ligne horizontale ·
    effacer la mise en forme · « Variable » (modèles : {{client.nom}}…).

  Le texte est du HTML ; le serveur le nettoie (liste blanche) à l'enregistrement.
  Props : value, onChange(html), variables [{key, label, group}], minHeight, testId, placeholder
*/
import React, { useEffect, useRef, useState } from "react";
import {
  Undo2, Redo2, Bold, Italic, Underline, Strikethrough, AlignLeft, AlignCenter, AlignRight, AlignJustify,
  List, ListOrdered, IndentDecrease, IndentIncrease, Table as TableIcon, Image as ImageIcon, Minus, Eraser,
  Braces, Rows3, Columns3, Trash2, Palette, Highlighter,
} from "lucide-react";

// Polices proposées (le PDF utilise la famille la plus proche : sans empattement / avec empattement)
const FONTS = [["Arial", "Arial, sans-serif"], ["Calibri", "Calibri, sans-serif"], ["Times New Roman", "'Times New Roman', serif"],
  ["Book Antiqua", "'Book Antiqua', serif"], ["Courier New", "'Courier New', monospace"]];
// Tailles : valeur de execCommand("fontSize") 1 à 7
const SIZES = [["8", 1], ["10", 2], ["12", 3], ["14", 4], ["18", 5], ["24", 6], ["32", 7]];
const BLOCKS = [["p", "Paragraphe"], ["h1", "Titre 1"], ["h2", "Titre 2"], ["h3", "Titre 3"]];

// Bouton de la barre d'outils (mousedown empêché : la sélection reste dans le texte)
function Tool({ title, onClick, children, active, testId }) {
  return (
    <button type="button" title={title} aria-label={title} data-testid={testId}
      onMouseDown={(e) => e.preventDefault()} onClick={onClick}
      className={`inline-flex h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-slate-700 hover:bg-slate-100 ${active ? "bg-slate-200" : ""}`}>
      {children}
    </button>
  );
}
const Sep = () => <span className="mx-1 h-6 w-px bg-slate-200" />;

// Réduit une image (largeur max 1000 px) et la renvoie en data URL
function shrinkImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const img = new window.Image();
      img.onload = () => {
        const scale = Math.min(1, 1000 / img.width);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        const type = file.type === "image/png" ? "image/png" : "image/jpeg";
        resolve({ src: canvas.toDataURL(type, 0.85), width: canvas.width });
      };
      img.onerror = reject;
      img.src = reader.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export default function RichTextEditor({ value, onChange, variables = [], minHeight = 320, testId = "rte", placeholder = "Saisissez le texte…" }) {
  const ref = useRef(null);
  const lastHtml = useRef(null);
  const savedRange = useRef(null);
  const imgInput = useRef(null);
  const [tableDlg, setTableDlg] = useState(false);
  const [rowsCols, setRowsCols] = useState({ rows: 3, cols: 3 });
  const [varMenu, setVarMenu] = useState(false);
  const [inTable, setInTable] = useState(false);
  const [selectedImg, setSelectedImg] = useState(null);

  // Contenu initial / remplacé depuis l'extérieur (ex. ouverture d'un autre modèle)
  useEffect(() => {
    if (ref.current && value !== lastHtml.current) {
      ref.current.innerHTML = value || "";
      // Les pastilles de variables restent insécables (attribut retiré par le serveur)
      ref.current.querySelectorAll(".tpl-var").forEach((el) => el.setAttribute("contenteditable", "false"));
      lastHtml.current = value || "";
    }
  }, [value]);

  // Styles en CSS (spans) plutôt qu'en balises <font> quand c'est possible
  useEffect(() => { try { document.execCommand("styleWithCSS", false, true); } catch { /* ancien navigateur */ } }, []);

  // Transmet le HTML à chaque modification
  const emit = () => {
    const html = ref.current?.innerHTML || "";
    lastHtml.current = html;
    onChange?.(html);
  };

  // Mémorise / restaure la position du curseur (les menus lui font perdre le focus)
  const saveRange = () => {
    const sel = window.getSelection();
    if (sel && sel.rangeCount && ref.current?.contains(sel.anchorNode)) savedRange.current = sel.getRangeAt(0).cloneRange();
  };
  const restoreRange = () => {
    ref.current?.focus();
    const sel = window.getSelection();
    if (savedRange.current && sel) { sel.removeAllRanges(); sel.addRange(savedRange.current); }
  };

  // Commande d'édition standard du navigateur
  const exec = (cmd, arg = null) => { restoreRange(); document.execCommand(cmd, false, arg); emit(); refreshState(); };
  const insertHtml = (html) => { restoreRange(); document.execCommand("insertHTML", false, html); emit(); };
  // Insertion directe dans la page (les styles sont gardés tels quels : la
  // commande insertHTML du navigateur perd par exemple le style des bordures)
  const insertNodes = (html) => {
    restoreRange();
    const sel = window.getSelection();
    const tpl = document.createElement("template");
    tpl.innerHTML = html;
    const last = tpl.content.lastChild;
    if (sel && sel.rangeCount && ref.current.contains(sel.anchorNode)) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(tpl.content);
      if (last) { range.setStartAfter(last); range.collapse(true); sel.removeAllRanges(); sel.addRange(range); }
    } else {
      ref.current.appendChild(tpl.content);
    }
    emit();
  };

  // Le curseur est-il dans un tableau ? (affiche les outils de tableau)
  const currentCell = () => {
    const sel = window.getSelection();
    let n = sel && sel.anchorNode;
    while (n && n !== ref.current) { if (n.nodeName === "TD" || n.nodeName === "TH") return n; n = n.parentNode; }
    return null;
  };
  const refreshState = () => { saveRange(); setInTable(Boolean(currentCell())); };

  // ---- Tableaux
  const cellStyle = "border: 1px solid #000; padding: 4px 6px; vertical-align: top;";
  const insertTable = () => {
    const r = Math.max(1, Math.min(30, Number(rowsCols.rows) || 1));
    const c = Math.max(1, Math.min(12, Number(rowsCols.cols) || 1));
    const row = `<tr>${Array.from({ length: c }, () => `<td style="${cellStyle}">&nbsp;</td>`).join("")}</tr>`;
    insertNodes(`<table border="1" style="border-collapse: collapse; width: 100%;"><tbody>${row.repeat(r)}</tbody></table><p><br></p>`);
    setTableDlg(false);
  };
  const tableOp = (op) => {
    restoreRange();
    const cell = currentCell();
    if (!cell) return;
    const tr = cell.parentNode;
    const table = tr.closest("table");
    const idx = Array.from(tr.children).indexOf(cell);
    if (op === "addRow") {
      const copy = tr.cloneNode(true);
      copy.querySelectorAll("td,th").forEach((td) => { td.innerHTML = "&nbsp;"; });
      tr.after(copy);
    } else if (op === "addCol") {
      table.querySelectorAll("tr").forEach((row) => {
        const ref2 = row.children[idx];
        const td = document.createElement(ref2?.nodeName === "TH" ? "th" : "td");
        td.setAttribute("style", cellStyle); td.innerHTML = "&nbsp;";
        if (ref2) ref2.after(td); else row.appendChild(td);
      });
    } else if (op === "delRow") {
      if (table.querySelectorAll("tr").length > 1) tr.remove(); else table.remove();
    } else if (op === "delCol") {
      const rows = table.querySelectorAll("tr");
      if (rows[0].children.length > 1) rows.forEach((row) => row.children[idx]?.remove()); else table.remove();
    } else if (op === "delTable") {
      table.remove();
    }
    emit(); refreshState();
  };

  // ---- Images
  const onImage = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const { src, width } = await shrinkImage(file);
    insertHtml(`<img src="${src}" style="max-width: 100%; width: ${Math.min(width, 600)}px;" alt="">`);
  };
  const setImgWidth = (pct) => {
    if (!selectedImg) return;
    selectedImg.style.width = `${pct}%`;
    emit();
  };

  // ---- Variables (modèles)
  const insertVariable = (key) => {
    insertHtml(`<span class="tpl-var" data-var="${key}" contenteditable="false">{{${key}}}</span>&nbsp;`);
    setVarMenu(false);
  };
  const groups = variables.reduce((acc, v) => { (acc[v.group || "Variables"] ||= []).push(v); return acc; }, {});

  return (
    <div className="rounded-xl border border-slate-300 bg-white" data-testid={testId}>
      {/* Styles de l'éditeur : pastilles de variables, tableaux visibles */}
      <style>{`
        [data-rte] .tpl-var { background:#E0F2FE; color:#0369A1; border-radius:4px; padding:0 3px; font-family: ui-monospace, monospace; font-size: .85em; white-space: nowrap; }
        [data-rte] table td, [data-rte] table th { min-width: 40px; }
        [data-rte] img.rte-selected { outline: 2px solid #0F6B4A; }
        [data-rte]:empty:before { content: attr(data-placeholder); color: #94A3B8; }
        [data-rte] h1 { font-size: 1.6em; font-weight: 700; } [data-rte] h2 { font-size: 1.35em; font-weight: 700; } [data-rte] h3 { font-size: 1.15em; font-weight: 700; }
        [data-rte] ul { list-style: disc; padding-left: 1.6em; } [data-rte] ol { list-style: decimal; padding-left: 1.6em; }
        [data-rte] blockquote { margin: 0 0 0 40px; }
      `}</style>

      {/* Barre de mise en forme */}
      <div className="flex flex-wrap items-center gap-0.5 border-b border-slate-200 bg-slate-50 px-2 py-1.5 rounded-t-xl sticky top-0 z-10">
        <Tool title="Annuler" onClick={() => exec("undo")}><Undo2 className="h-4 w-4" /></Tool>
        <Tool title="Rétablir" onClick={() => exec("redo")}><Redo2 className="h-4 w-4" /></Tool>
        <Sep />
        <select title="Style" className="h-8 rounded-md border border-slate-200 bg-white px-1 text-xs" defaultValue=""
          onMouseDown={saveRange} onChange={(e) => { exec("formatBlock", e.target.value); e.target.value = ""; }} data-testid={`${testId}-block`}>
          <option value="" disabled>Style</option>
          {BLOCKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select title="Police" className="h-8 rounded-md border border-slate-200 bg-white px-1 text-xs" defaultValue=""
          onMouseDown={saveRange} onChange={(e) => { exec("fontName", e.target.value); e.target.value = ""; }}>
          <option value="" disabled>Police</option>
          {FONTS.map(([l, v]) => <option key={l} value={v}>{l}</option>)}
        </select>
        <select title="Taille" className="h-8 rounded-md border border-slate-200 bg-white px-1 text-xs" defaultValue=""
          onMouseDown={saveRange} onChange={(e) => { exec("fontSize", e.target.value); e.target.value = ""; }}>
          <option value="" disabled>Taille</option>
          {SIZES.map(([l, v]) => <option key={l} value={v}>{l}</option>)}
        </select>
        <Sep />
        <Tool title="Gras (Ctrl+B)" onClick={() => exec("bold")} testId={`${testId}-bold`}><Bold className="h-4 w-4" /></Tool>
        <Tool title="Italique (Ctrl+I)" onClick={() => exec("italic")}><Italic className="h-4 w-4" /></Tool>
        <Tool title="Souligné (Ctrl+U)" onClick={() => exec("underline")}><Underline className="h-4 w-4" /></Tool>
        <Tool title="Barré" onClick={() => exec("strikeThrough")}><Strikethrough className="h-4 w-4" /></Tool>
        {/* Couleurs : un sélecteur de couleur caché derrière l'icône */}
        <label title="Couleur du texte" className="relative inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md hover:bg-slate-100" onMouseDown={saveRange}>
          <Palette className="h-4 w-4 text-slate-700" />
          <input type="color" className="absolute inset-0 cursor-pointer opacity-0" onChange={(e) => exec("foreColor", e.target.value)} />
        </label>
        <label title="Surlignage" className="relative inline-flex h-8 w-8 cursor-pointer items-center justify-center rounded-md hover:bg-slate-100" onMouseDown={saveRange}>
          <Highlighter className="h-4 w-4 text-slate-700" />
          <input type="color" defaultValue="#FFFF00" className="absolute inset-0 cursor-pointer opacity-0" onChange={(e) => exec("hiliteColor", e.target.value)} />
        </label>
        <Sep />
        <Tool title="Aligner à gauche" onClick={() => exec("justifyLeft")}><AlignLeft className="h-4 w-4" /></Tool>
        <Tool title="Centrer" onClick={() => exec("justifyCenter")}><AlignCenter className="h-4 w-4" /></Tool>
        <Tool title="Aligner à droite" onClick={() => exec("justifyRight")}><AlignRight className="h-4 w-4" /></Tool>
        <Tool title="Justifier" onClick={() => exec("justifyFull")} testId={`${testId}-justify`}><AlignJustify className="h-4 w-4" /></Tool>
        <Sep />
        <Tool title="Liste à puces" onClick={() => exec("insertUnorderedList")}><List className="h-4 w-4" /></Tool>
        <Tool title="Liste numérotée" onClick={() => exec("insertOrderedList")}><ListOrdered className="h-4 w-4" /></Tool>
        <Tool title="Diminuer le retrait" onClick={() => exec("outdent")}><IndentDecrease className="h-4 w-4" /></Tool>
        <Tool title="Augmenter le retrait" onClick={() => exec("indent")} testId={`${testId}-indent`}><IndentIncrease className="h-4 w-4" /></Tool>
        <Sep />
        <div className="relative">
          <Tool title="Insérer un tableau" onClick={() => { saveRange(); setTableDlg((v) => !v); }} testId={`${testId}-table`}><TableIcon className="h-4 w-4" /></Tool>
          {tableDlg && (
            <div className="absolute left-0 top-9 z-20 w-52 rounded-lg border border-slate-200 bg-white p-3 shadow-lg space-y-2 text-xs">
              <p className="font-semibold text-slate-700">Nouveau tableau</p>
              <div className="flex items-center gap-2">
                <label className="flex-1">Lignes<input type="number" min="1" max="30" value={rowsCols.rows} onChange={(e) => setRowsCols({ ...rowsCols, rows: e.target.value })} className="mt-0.5 w-full rounded border border-slate-300 px-1.5 py-1" data-testid={`${testId}-rows`} /></label>
                <label className="flex-1">Colonnes<input type="number" min="1" max="12" value={rowsCols.cols} onChange={(e) => setRowsCols({ ...rowsCols, cols: e.target.value })} className="mt-0.5 w-full rounded border border-slate-300 px-1.5 py-1" data-testid={`${testId}-cols`} /></label>
              </div>
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={insertTable} className="w-full rounded-md bg-primary py-1.5 text-primary-foreground" data-testid={`${testId}-table-insert`}>Insérer</button>
            </div>
          )}
        </div>
        <Tool title="Insérer une image" onClick={() => { saveRange(); imgInput.current?.click(); }}><ImageIcon className="h-4 w-4" /></Tool>
        <input ref={imgInput} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={onImage} />
        <Tool title="Ligne horizontale" onClick={() => exec("insertHorizontalRule")}><Minus className="h-4 w-4" /></Tool>
        <Tool title="Effacer la mise en forme" onClick={() => exec("removeFormat")}><Eraser className="h-4 w-4" /></Tool>
        {variables.length > 0 && (
          <div className="relative">
            <button type="button" onMouseDown={(e) => { e.preventDefault(); saveRange(); }} onClick={() => setVarMenu((v) => !v)} data-testid={`${testId}-var`}
              className="inline-flex h-8 items-center gap-1 rounded-md bg-sky-600 px-2 text-xs font-medium text-white hover:bg-sky-700">
              <Braces className="h-3.5 w-3.5" /> Variable
            </button>
            {varMenu && (
              <div className="absolute left-0 top-9 z-30 max-h-80 w-72 overflow-y-auto rounded-lg border border-slate-200 bg-white p-1 shadow-lg">
                {Object.entries(groups).map(([g, list]) => (
                  <div key={g}>
                    <p className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-wider text-slate-400 font-semibold">{g}</p>
                    {list.map((v) => (
                      <button key={v.key} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => insertVariable(v.key)}
                        className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-sky-50" data-testid={`${testId}-var-${v.key}`}>
                        <span className="text-slate-800">{v.label}</span> <code className="text-[10px] text-sky-700">{`{{${v.key}}}`}</code>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {/* Outils visibles quand le curseur est dans un tableau */}
        {inTable && (
          <>
            <Sep />
            <Tool title="Ajouter une ligne" onClick={() => tableOp("addRow")}><Rows3 className="h-4 w-4" /></Tool>
            <Tool title="Ajouter une colonne" onClick={() => tableOp("addCol")}><Columns3 className="h-4 w-4" /></Tool>
            <Tool title="Supprimer la ligne" onClick={() => tableOp("delRow")}><span className="text-[10px] font-semibold">−L</span></Tool>
            <Tool title="Supprimer la colonne" onClick={() => tableOp("delCol")}><span className="text-[10px] font-semibold">−C</span></Tool>
            <Tool title="Supprimer le tableau" onClick={() => tableOp("delTable")}><Trash2 className="h-4 w-4 text-rose-600" /></Tool>
          </>
        )}
        {/* Largeur de l'image sélectionnée */}
        {selectedImg && (
          <>
            <Sep />
            {[25, 50, 75, 100].map((p) => <Tool key={p} title={`Largeur ${p} %`} onClick={() => setImgWidth(p)}><span className="text-[10px]">{p}%</span></Tool>)}
          </>
        )}
      </div>

      {/* Zone de saisie */}
      <div
        ref={ref}
        data-rte
        data-placeholder={placeholder}
        contentEditable
        suppressContentEditableWarning
        className="prose-sm max-w-none px-6 py-5 text-[15px] leading-relaxed text-slate-900 focus:outline-none"
        style={{ minHeight, fontFamily: "Arial, sans-serif" }}
        onInput={emit}
        onKeyUp={refreshState}
        onMouseUp={refreshState}
        onBlur={saveRange}
        onClick={(e) => {
          // Clic sur une image : sélection (réglage de la largeur)
          ref.current.querySelectorAll("img.rte-selected").forEach((i) => i.classList.remove("rte-selected"));
          if (e.target.nodeName === "IMG") { e.target.classList.add("rte-selected"); setSelectedImg(e.target); } else setSelectedImg(null);
        }}
        data-testid={`${testId}-area`}
      />
    </div>
  );
}
