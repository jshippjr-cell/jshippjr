#!/usr/bin/env node
'use strict';
/*
 * Applies the project's Visual Identity (references/brand-voice.md) to a video page: its
 * colors, its display font, and an end card with the logo and handle that lands on the sonic
 * logo, so the brand is seen and heard together at the end of every video. The visual
 * counterpart of the Sonic Identity.
 *
 * Usage:
 *   node brand.js <page.html> [--endcard | --no-endcard]
 *   node brand.js --show                     # the Visual Identity it finds, and its contrast
 *
 * Running it again replaces what it added before. The end card adds 1.6 seconds after the
 * video's last scene. It goes on marketing and narrated pages by default, not on everyday
 * posts (they loop better without one); --endcard and --no-endcard override that.
 * compose.js applies it on its own.
 *
 * In brand-voice.md:
 *   ## Visual Identity
 *   - Accent: #e07a55
 *   - Background: #0f0f13
 *   - Text: #f3f2ee
 *   - Font: Space Grotesk          (any Google Fonts family; everyday posts keep TikTok Sans)
 *   - Logo: state/videos/assets/logo.png
 *   - Handle: @yourbrand
 */
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
// The end card is added after the video's own end, so nothing is cut short. The sonic logo
// lands a second before the (new) end, while the card is up.
const ENDCARD_SECONDS = 1.6;

function fail(message) {
  console.error(message);
  process.exit(2);
}

// The Visual Identity section of brand-voice.md, or null while it's the placeholder.
function visualIdentity(file = path.join(ROOT, 'references', 'brand-voice.md')) {
  if (!fs.existsSync(file)) return null;
  const text = fs.readFileSync(file, 'utf8');
  const section = (/^## Visual Identity\n([\s\S]*?)(?=^## |$(?![\s\S]))/m.exec(text) || [])[1] || '';
  if (!section.trim() || /not yet configured/i.test(section)) return null;
  const field = (name) => {
    const v = ((new RegExp(`^-\\s*${name}:\\s*(.+)$`, 'mi')).exec(section) || [])[1];
    return v ? v.replace(/\s*\(.*\)\s*$/, '').trim() : undefined;
  };
  const color = (v) => (v && /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.test(v) ? v : undefined);
  const id = {
    accent: color(field('Accent')), bg: color(field('Background')), text: color(field('Text')),
    font: field('Font'), logo: field('Logo'), handle: field('Handle'),
  };
  if (id.font && !/^[A-Za-z0-9 ]+$/.test(id.font)) id.font = undefined;
  return Object.values(id).some(Boolean) ? id : null;
}

// ---- color math (sRGB), for derived shades and WCAG contrast
const rgb = (hex) => {
  let h = hex.replace('#', '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
};
const toHex = (c) => `#${c.map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('')}`;
const mix = (a, b, t) => toHex(rgb(a).map((v, i) => v + (rgb(b)[i] - v) * t));
const luminance = (hex) => {
  const [r, g, b] = rgb(hex).map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

// Contrast warnings for the identity's colors: white text sits on the accent (highlighted
// captions, buttons), and body text on the background.
function contrastProblems(id, defaults = { accent: '#e07a55', bg: '#0f0f13', text: '#f3f2ee' }) {
  const c = { ...defaults, ...Object.fromEntries(Object.entries(id || {}).filter(([, v]) => v)) };
  const problems = [];
  const onAccent = contrast('#ffffff', c.accent);
  if (onAccent < 3) problems.push(`white text on the accent ${c.accent} has a contrast of ${onAccent.toFixed(1)}:1, under 3:1; highlighted captions and buttons will be hard to read, so use a darker accent`);
  const body = contrast(c.text, c.bg);
  if (body < 4.5) problems.push(`text ${c.text} on background ${c.bg} has a contrast of ${body.toFixed(1)}:1, under 4.5:1`);
  return problems;
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// Finds the logo file and copies it into the page's assets/ folder if it isn't there.
// Returns its src relative to the page, or null.
function placeLogo(logo, pageDir) {
  const candidates = path.isAbsolute(logo) ? [logo] : [path.join(pageDir, logo), path.join(ROOT, logo), path.resolve(logo)];
  const found = candidates.find((f) => fs.existsSync(f));
  if (!found) return null;
  const assets = path.join(pageDir, 'assets');
  if (path.dirname(path.resolve(found)) === path.resolve(assets)) return `assets/${path.basename(found)}`;
  fs.mkdirSync(assets, { recursive: true });
  const name = `logo${path.extname(found)}`;
  fs.copyFileSync(found, path.join(assets, name));
  return `assets/${name}`;
}

// Rewrites the attributes of the page's real <body> tag, the one after </head> (the templates'
// doc comment mentions <body data-*> too).
function onBody(html, edit) {
  const at = html.indexOf('</head>');
  return html.slice(0, at) + html.slice(at).replace(/<body([^>]*)>/, (m, attrs) => `<body${edit(attrs)}>`);
}

// Applies the identity to the page's HTML. Returns { html, changes, problems }.
function applyIdentity(html, id, { pageDir = '.', endcard } = {}) {
  const changes = [];
  const problems = contrastProblems(id);
  // what an earlier run added
  html = html.replace(/<style id="brand">[\s\S]*?<\/style>\n?/, '').replace(/<link id="brand-font"[^>]*>\n?/, '')
    .replace(/\n? *<!-- brand:endcard -->[\s\S]*?<!-- \/brand:endcard -->/, '');
  html = html.replace(/(<div class="scene[^"]*") style="--out:[\d.]+s" data-brand-out>/, '$1>');
  html = onBody(html, (attrs) => {
    const base = /\s*data-brand-base="([\d.]+)"/.exec(attrs);
    return base ? attrs.replace(base[0], '').replace(/data-duration="[\d.]+"/, `data-duration="${base[1]}"`) : attrs;
  });

  const vars = [];
  if (id.accent) vars.push(`--accent: ${id.accent};`);
  // the soft background glows, tinted from the accent so they don't clash with it
  const glows = id.accent ? `  .glow.g1 { background: ${mix(id.accent, id.bg || '#0f0f13', 0.45)}; } .glow.g2 { background: ${mix(id.accent, id.bg || '#0f0f13', 0.7)}; }` : '';
  if (id.bg) {
    vars.push(`--bg: ${id.bg};`, `--card: ${mix(id.bg, '#ffffff', 0.07)};`, `--line: ${mix(id.bg, '#ffffff', 0.14)};`);
  }
  if (id.text) vars.push(`--text: ${id.text};`);
  if (id.text || id.bg) vars.push(`--muted: ${mix(id.text || '#f3f2ee', id.bg || '#0f0f13', 0.42)};`);
  const css = [];
  if (vars.length) {
    css.push(`  :root { ${vars.join(' ')} }`);
    if (glows) css.push(glows);
    changes.push(`colors (${['accent', 'bg', 'text'].filter((k) => id[k]).map((k) => `${k} ${id[k]}`).join(', ')})`);
  }
  let fontLink = '';
  if (id.font && id.font !== 'Inter') {
    fontLink = `<link id="brand-font" rel="stylesheet" href="https://fonts.googleapis.com/css2?family=${id.font.trim().replace(/ /g, '+')}:wght@500;600;700;800;900&display=block">\n`;
    // everyday posts keep TikTok Sans, the platforms' own caption font
    css.push(`  body:not(.fyp) { font-family: "${id.font}", "Inter", "Liberation Sans", "Noto Color Emoji", sans-serif; }`);
    changes.push(`font ${id.font}`);
  }
  if (css.length || fontLink) html = html.replace('</head>', `${fontLink}<style id="brand">\n${css.join('\n')}\n</style>\n</head>`);

  // the real <body> tag, after </head> (the template's doc comment mentions <body data-*> too)
  const body = /<body([^>]*)>/.exec(html.slice(html.indexOf('</head>')));
  const duration = body && parseFloat((/data-duration="([\d.]+)"/.exec(body[1]) || [])[1]);
  const everyday = body && /class="[^"]*\bfyp\b/.test(body[1]) && !/class="say auto"/.test(html);
  const wantCard = endcard ?? !everyday;
  if (wantCard && (id.logo || id.handle) && duration > 2) {
    const at = duration;
    const logo = id.logo ? placeLogo(id.logo, pageDir) : null;
    if (id.logo && !logo) problems.push(`logo ${id.logo} not found; the end card shows the handle only`);
    const parts = [];
    if (logo) parts.push(`<img class="logo" src="${esc(logo)}" alt="">`);
    if (id.handle) parts.push(`<div class="handle">${esc(id.handle)}</div>`);
    if (parts.length) {
      // the last scene (the one with no --out) leaves where the video used to end
      let cleared = false;
      html = html.replace(/<div class="scene([^"]*)">(?![\s\S]*<div class="scene[^"]*">)/, (m, cls) => {
        cleared = true;
        return `<div class="scene${cls}" style="--out:${(at - 0.1).toFixed(2)}s" data-brand-out>`;
      });
      const total = +(duration + ENDCARD_SECONDS).toFixed(2);
      html = onBody(html, (attrs) => `${attrs.replace(/data-duration="[\d.]+"/, `data-duration="${total}"`)} data-brand-base="${duration}"`);
      const card = `  <!-- brand:endcard -->\n  <div class="endcard" style="--in:${at}s">${parts.join('')}</div>\n  <!-- /brand:endcard -->`;
      html = html.replace(/\n<\/body>/, `\n${card}\n</body>`);
      changes.push(`end card from ${at}s, making the video ${total}s (${[logo && 'logo', id.handle && 'handle'].filter(Boolean).join(' and ')})${cleared ? '' : '; no open last scene found, so it overlays the last frame'}`);
    }
  }
  return { html, changes, problems };
}

function main() {
  const argv = process.argv.slice(2);
  const args = { positional: [] };
  for (const a of argv) {
    if (a === '--show') args.show = true;
    else if (a === '--endcard') args.endcard = true;
    else if (a === '--no-endcard') args.endcard = false;
    else if (a === '-h' || a === '--help') args.help = true;
    else args.positional.push(a);
  }
  if (args.help || (!args.show && !args.positional.length)) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }
  const id = visualIdentity();
  if (args.show) {
    if (!id) return console.log('No Visual Identity saved yet in references/brand-voice.md.');
    console.log(JSON.stringify(id, null, 2));
    for (const p of contrastProblems(id)) console.warn(`Warning: ${p}`);
    return;
  }
  if (!id) fail('No Visual Identity saved yet in references/brand-voice.md; the page keeps its template colors.');
  const page = args.positional[0];
  if (!fs.existsSync(page)) fail(`No page at ${page}`);
  const { html, changes, problems } = applyIdentity(fs.readFileSync(page, 'utf8'), id, { pageDir: path.dirname(path.resolve(page)), endcard: args.endcard });
  fs.writeFileSync(page, html);
  for (const p of problems) console.warn(`Warning: ${p}`);
  console.log(changes.length ? `Applied to ${page}: ${changes.join('; ')}` : `Nothing to apply to ${page}.`);
}

if (require.main === module) main();

module.exports = { visualIdentity, applyIdentity, contrastProblems, contrast };
