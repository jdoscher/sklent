// Specs and sheets (area S): the spec and parts sections in the drawing sheet, the
// licence in the title block, labels for the sheet files, the settings group, and the
// contact-sheet button on each source row.
//
// Seams used: registerDetailSection, registerTitleBlockField (detail.js),
// registerSettingsGroup (settings.js), registerSourceAction (sidebar.js), api (api.js).
// The sheets themselves (spec card, parts sheet, views sheet + PDF, dimensions, assembly
// steps + assembly.md, bom.csv) are set files, so they appear in the schedule on their own.

import { api } from '../api.js';
import { registerDetailSection, registerTitleBlockField } from '../detail.js';
import { VARIANT_LABEL, fmtMass } from '../format.js';
import { registerSettingsGroup } from '../settings.js';
import { registerSourceAction } from '../sidebar.js';

Object.assign(VARIANT_LABEL, {
  'spec-card': 'Spec card',
  'bom-sheet': 'Parts sheet',
  'bom-csv': 'Parts list (CSV)',
  'views-sheet': 'Views sheet',
  'views-sheet-pdf': 'Views sheet (PDF)',
  dimensions: 'Dimensions',
  'assembly-md': 'Assembly guide (Markdown)',
});
for (let n = 1; n <= 60; n += 1) VARIANT_LABEL[`assembly-${n}`] = `Assembly step ${n}`;

const num = (v, digits = 3) => {
  if (v == null || Number.isNaN(Number(v))) return null;
  const x = Number(v);
  if (x === 0) return '0';
  const dec = Math.max(0, digits - 1 - Math.floor(Math.log10(Math.abs(x))));
  return x.toLocaleString('en-US', { maximumFractionDigits: dec, minimumFractionDigits: 0 });
};

// ---------------------------------------------------------------- the title block

registerTitleBlockField({ id: 'licence', label: 'Licence', order: 40, value: (d) => d.spec?.licence ?? null });

// ---------------------------------------------------------------- Spec

function specRows(s) {
  const rows = [];
  const vol = num(s.volume_mm3 != null ? s.volume_mm3 / 1000 : null);
  rows.push(['Volume', vol ? `${vol} cm³` : '—']);
  const mass = fmtMass(s.mass_g);
  rows.push(['Mass', mass ? `${mass} · ${s.material}` : 'no material set']);
  if (s.components) rows.push(['Components', `${s.components.toLocaleString('en-US')} parts · ${(s.occurrences || 0).toLocaleString('en-US')} placed`]);
  if (s.open_bodies) rows.push(['Open bodies', String(s.open_bodies)]);
  if (s.solidcraft) rows.push(['Measured by', `SolidCraft ${s.solidcraft}`]);
  return rows;
}

registerDetailSection({
  id: 'specs-spec',
  title: 'Spec',
  order: 20,
  when: (d) => !!d.spec,
  render(el, d, ctx) {
    const s = d.spec;
    const params = (s.parameters || []).map((p) => {
      const v = typeof p.value === 'number' ? num(p.value, 6) : (p.expression ?? '—');
      const unit = p.unit && p.unit !== 'none' ? ` ${p.unit}` : '';
      return `<li><span class="sk-specs-k">${ctx.esc(p.name)}</span><span class="sk-data">${ctx.esc(`${v}${unit}`)}</span></li>`;
    }).join('');
    el.innerHTML = `<dl class="sk-specs-dl">${specRows(s).map(([k, v]) => `<dt>${ctx.esc(k)}</dt><dd class="sk-data">${ctx.esc(v)}</dd>`).join('')}</dl>
      ${params ? `<details class="sk-specs-params"><summary>Parameters <span class="sk-data">${s.parameters.length}</span></summary><ul>${params}</ul></details>` : ''}`;
  },
});

// ---------------------------------------------------------------- Parts (BOM)

const bomCache = new Map();

async function loadBom(d) {
  const key = `${d.id}@${d.rendered_at}`;
  if (!bomCache.has(key)) bomCache.set(key, api(`/designs/${d.id}/bom`).catch((err) => { bomCache.delete(key); throw err; }));
  return bomCache.get(key);
}

const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : null);

registerDetailSection({
  id: 'specs-parts',
  title: 'Parts',
  order: 30,
  when: (d) => d.files.some((f) => f.variant === 'bom-csv'),
  async render(el, d, ctx) {
    el.innerHTML = '<p class="sk-specs-note">Loading…</p>';
    let b;
    try { b = await loadBom(d); } catch (err) { el.innerHTML = `<p class="sk-specs-note">${ctx.esc(err.message)}</p>`; return; }
    const csv = d.files.find((f) => f.variant === 'bom-csv');
    const sm = b.summary || {};
    const rows = (b.rows || []).map((r) => {
      const url = safeUrl(r.url);
      const who = r.supplier ? (url ? `<a href="${ctx.esc(url)}" target="_blank" rel="noopener noreferrer">${ctx.esc(r.supplier)}</a>` : ctx.esc(r.supplier)) : '';
      return `<li class="sk-specs-part">
        <span class="sk-data sk-specs-qty">${ctx.esc(String(r.qty))}×</span>
        <span class="sk-specs-name">${ctx.esc(r.name)}${r.part_number ? ` <span class="sk-data sk-specs-dim">${ctx.esc(r.part_number)}</span>` : ''}</span>
        <span class="sk-specs-kind">${ctx.esc(r.kind)}${who ? ` · ${who}` : ''}</span>
      </li>`;
    }).join('');
    const total = sm.total_price != null ? ` · ${num(sm.total_price, 6)}${sm.currency ? ` ${ctx.esc(sm.currency)}` : ''} priced` : '';
    el.innerHTML = `<p class="sk-specs-note sk-data">make ${sm.make ?? 0} · buy ${sm.buy ?? 0}${total}${b.bom_yaml ? ` · ${ctx.esc(b.bom_yaml)}` : ''}</p>
      <ul class="sk-specs-parts">${rows}</ul>
      ${(b.warnings || []).length ? `<p class="sk-specs-note">${b.warnings.map((w) => ctx.esc(w)).join('<br>')}</p>` : ''}
      ${csv ? `<p class="sk-specs-note"><a href="${ctx.esc(csv.url)}" download="${ctx.esc(csv.file)}">${ctx.esc(csv.file)}</a></p>` : ''}`;
  },
});

// ---------------------------------------------------------------- settings

// SolidCraft 0.44's built-in materials (material.list); .sklent.yaml can name any, custom ones too
const MATERIALS = ['', 'PLA', 'ABS Plastic', 'Nylon', 'Polycarbonate', 'Aluminum', 'Steel', 'Stainless Steel', 'Cast Iron',
  'Brass', 'Copper', 'Titanium', 'Oak', 'Glass'];

registerSettingsGroup({
  id: 'specs',
  title: 'Specs and sheets',
  order: 60,
  fields: [
    { name: 'specs_card', label: 'Spec card', type: 'checkbox', hint: 'spec.json is always written' },
    { name: 'specs_material', label: 'Material for mass', type: 'select', hint: 'unless .sklent.yaml names one',
      options: MATERIALS.map((m) => ({ value: m, label: m || 'none (mass only if the design sets one)' })) },
    { name: 'specs_bom', label: 'Parts list', type: 'checkbox', hint: 'assembly BOM + bom.yaml' },
    { name: 'specs_bom_file', label: 'BOM file', type: 'text', hint: 'next to the design, in the repo' },
    { name: 'specs_views', label: 'Views sheet', type: 'checkbox', hint: 'front, top, right, iso · PNG + PDF' },
    { name: 'specs_dimensions', label: 'Dimensions still', type: 'checkbox', hint: 'front view, overall sizes' },
    { name: 'specs_assembly', label: 'Assembly steps', type: 'checkbox', hint: 'assemblies only' },
    { name: 'specs_assembly_max_steps', label: 'Most steps', type: 'number', min: 1, max: 60 },
  ],
});

// ---------------------------------------------------------------- contact sheet

registerSourceAction({
  id: 'contact-sheet',
  icon: 'layout-grid',
  label: 'Contact sheet',
  order: 10,
  async run(source, ctx) {
    ctx.toast('Making the contact sheet…');
    const r = await api(`/sources/${source.id}/contact-sheet`, { method: 'POST' });
    const filed = r.kist_items.length ? ` · filed in Kist` : '';
    ctx.toast(`Contact sheet: ${r.designs} design${r.designs === 1 ? '' : 's'}, ${r.pages} page${r.pages === 1 ? '' : 's'}${filed}`, {
      action: { label: r.pages > 1 ? 'Open PDF' : 'Open', run: () => window.open(r.pages > 1 ? r.pdf : r.png[0], '_blank', 'noopener') },
    });
  },
});
