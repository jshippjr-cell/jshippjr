#!/usr/bin/env node
'use strict';
/*
 * Jump cuts for a talking-head take filmed on a phone: finds the pauses (from the clip's own
 * loudness, the same way captions.js finds phrases) and cuts them out, keeping a little air
 * around each phrase, so the take moves at the pace short-form viewers expect. Optionally
 * times captions to the cut and writes a page that renders it as a finished video: the clip
 * full-frame with its own sound, word-by-word captions, the hook on screen from the first
 * frame, the project's music under it, and the brand's end card.
 *
 * Usage:
 *   node cut.js <take.mp4> [--out <cut.mp4>] [--min-pause 0.35] [--pad 0.12]
 *   node cut.js <take.mp4> --text "what's said, word for word" --page <page.html>
 *               [--hook "the line on screen from frame 0"] [--cta "follow for part 2"]
 *
 * --min-pause: pauses at least this long are cut (shorter ones are breathing room and stay).
 * --pad: how much of each pause stays on either side of the cut, so words aren't clipped.
 * Without --out, the cut goes next to the take as <name>-cut.mp4, or into the page's assets/
 * folder with --page. The script is the person's real words: never edit them into something
 * they didn't say, and only film or post people with their permission.
 */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const captions = require('./captions');
const { probeDuration } = require('./render');
const { sonicIdentity } = require('./compose');
const { visualIdentity, applyIdentity } = require('./brand');

const TEMPLATE = path.join(__dirname, 'templates', 'narrated.html');
const TAIL = 1.2; // after the take ends, room for the sonic logo

function fail(message) {
  console.error(message);
  process.exit(2);
}

function parseArgs(argv) {
  const args = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (['--out', '--min-pause', '--pad', '--text', '--page', '--hook', '--cta'].includes(a)) args[a.slice(2).replace(/-(\w)/g, (m, c) => c.toUpperCase())] = argv[++i];
    else if (a === '-h' || a === '--help') args.help = true;
    else args.positional.push(a);
  }
  return args;
}

function ffmpeg(args) {
  const run = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { encoding: 'utf8' });
  if (run.status !== 0) fail(`ffmpeg failed: ${run.stderr}`);
}

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const r2 = (t) => Math.round(t * 100) / 100;

// The stretches to keep: spoken runs, joined across pauses shorter than minPause, each padded.
function keepSegments(file, minPause, pad) {
  const db = captions.envelope(captions.decode(file));
  const length = probeDuration(file);
  const runs = captions.spokenRuns(db);
  if (!runs.length) return { length, segments: [] };
  const joined = [];
  for (const r of runs) {
    const last = joined[joined.length - 1];
    if (last && r.start - last.end < minPause) last.end = r.end;
    else joined.push({ ...r });
  }
  const segments = joined.map((r) => ({ start: Math.max(0, r.start - pad), end: Math.min(length, r.end + pad) }));
  // padding can make neighbours touch
  const merged = [];
  for (const s of segments) {
    const last = merged[merged.length - 1];
    if (last && s.start <= last.end) last.end = s.end;
    else merged.push(s);
  }
  return { length, segments: merged };
}

function writeCut(file, segments, out) {
  const parts = segments.map((s, i) =>
    `[0:v]trim=start=${s.start.toFixed(3)}:end=${s.end.toFixed(3)},setpts=PTS-STARTPTS[v${i}];` +
    `[0:a]atrim=start=${s.start.toFixed(3)}:end=${s.end.toFixed(3)},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,afade=t=out:st=${(s.end - s.start - 0.01).toFixed(3)}:d=0.01[a${i}]`).join(';');
  const inputs = segments.map((_, i) => `[v${i}][a${i}]`).join('');
  ffmpeg(['-i', file, '-filter_complex', `${parts};${inputs}concat=n=${segments.length}:v=1:a=1[v][a]`,
    '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', out]);
}

// A page that plays the cut full-frame with its own sound, captions, the hook, music, and the brand.
function writePage(page, clipSrc, length, args) {
  const html = fs.readFileSync(TEMPLATE, 'utf8');
  const head = html.slice(html.indexOf('<html>'), html.indexOf('</head>') + '</head>'.length);
  const defaults = {};
  for (const m of /<body([^>]*)>/.exec(html.slice(html.indexOf('</head>')))[1].matchAll(/data-([\w-]+)="([^"]*)"/g)) defaults[m[1]] = m[2];
  const id = sonicIdentity();
  const sound = { ...defaults };
  if (id) {
    Object.assign(sound, Object.fromEntries(Object.entries({
      music: id.music, bpm: id.bpm, key: id.key, mode: id.mode,
      energy: Number.isFinite(id.energy) ? Math.max(1, id.energy - 1) : undefined, motif: id.motif,
    }).filter(([, v]) => v !== undefined && v !== '' && !Number.isNaN(v))));
  }
  const duration = r2(length + TAIL);
  const attrs = ['class="fyp"', `data-duration="${duration}"`, `data-drop="${Math.min(2, r2(length / 3))}"`,
    ...['music', 'bpm', 'key', 'mode', 'energy', 'motif'].filter((k) => sound[k] !== undefined).map((k) => `data-${k}="${esc(String(sound[k]))}"`)].join(' ');
  const parts = [];
  if (args.hook) parts.push(`    <div class="cap hook"><span>${esc(args.hook)}</span></div>`);
  if (args.cta) parts.push(`    <div class="end"><div class="cap hl pop" style="--in:${r2(Math.max(0, length - 2.5))}s" data-sfx="chime"><span>${esc(args.cta)}</span></div></div>`);
  if (args.text) parts.push(`    <div class="say auto" data-clip="take">${esc(args.text.trim())}</div>`);
  const doc = `<!doctype html>
<!--
  A filmed take, written by scripts/video/cut.js: the jump-cut clip full-frame with its own
  sound (data-audio), captions timed to it (data-clip), and the hook from the first frame.
  Page conventions: see the comment at the top of templates/promo.html.
-->
${head}
<body ${attrs}>
  <div class="glow g1"></div>
  <div class="glow g2"></div>
  <!-- the take, the whole video long; a light scrim so the captions read without hiding faces -->
  <div class="bg now" style="--in:0s; --dur:${duration}s; --kb:none; --shade:.12"><video class="bg-media" id="take" src="${esc(clipSrc)}" data-audio data-loop="false"></video></div>

  <div class="scene narr center">
${parts.join('\n')}
  </div>
</body>
</html>
`;
  const look = visualIdentity();
  const branded = look ? applyIdentity(doc, look, { pageDir: path.dirname(page) }) : { html: doc, changes: [], problems: [] };
  fs.writeFileSync(page, branded.html);
  return { duration, sound, identity: !!id, look: branded };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const take = args.positional[0];
  if (args.help || !take) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }
  if (!fs.existsSync(take)) fail(`No clip at ${take}`);
  if (!/audio/.test(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', take], { encoding: 'utf8' }).stdout)) {
    fail(`${take} has no sound track, so there are no pauses to find.`);
  }
  const minPause = Number(args.minPause || 0.35);
  const pad = Number(args.pad || 0.12);
  const page = args.page ? path.resolve(args.page) : null;
  const out = path.resolve(args.out || (page
    ? path.join(path.dirname(page), 'assets', `${path.basename(take).replace(/\.[^.]+$/, '')}-cut.mp4`)
    : take.replace(/(\.[^./]+)?$/, '-cut.mp4')));
  fs.mkdirSync(path.dirname(out), { recursive: true });

  const { length, segments } = keepSegments(take, minPause, pad);
  if (!segments.length) fail(`No speech found in ${take}.`);
  writeCut(take, segments, out);
  const cutLength = probeDuration(out);
  console.log(`Wrote ${out}: ${length.toFixed(2)}s -> ${cutLength.toFixed(2)}s, ${segments.length} stretch${segments.length === 1 ? '' : 'es'} kept (${segments.length - 1} cut${segments.length === 2 ? '' : 's'})`);
  for (const s of segments) console.log(`  kept ${s.start.toFixed(2)}–${s.end.toFixed(2)}s`);

  if (args.text) {
    const timing = await captions.alignWords(out, args.text, { shift: 0 });
    for (const n of timing.notes) console.warn(`Note: ${n}`);
    const chunks = captions.chunkWords(timing.words);
    console.log(`Captions (timed by ${timing.method}):`);
    for (const c of chunks) console.log(`  ${c.start.toFixed(2)}s  ${c.words.map((w) => w.text).join(' ')}`);
  }
  if (page) {
    const src = path.relative(path.dirname(page), out).split(path.sep).join('/');
    const { duration, sound, identity, look } = writePage(page, src, cutLength, args);
    console.log(`Wrote ${page}: ${duration}s`);
    console.log(`  sound: the take's own voice over ${sound.music}${identity ? ' (the Sonic Identity, one energy step lower)' : ' (the template default)'}`);
    console.log(`  look: ${look.changes.length ? look.changes.join('; ') : 'the template default; no Visual Identity saved yet'}`);
    for (const p of look.problems) console.warn(`Note: ${p}`);
    if (!args.text) console.warn('Note: no --text, so no captions. Most people watch muted: pass what\'s said, word for word.');
    if (!args.hook) console.warn('Note: no --hook, so the first frame has no text. Add one to stop the scroll.');
    const check = spawnSync(process.execPath, [path.join(__dirname, 'render.js'), page, '--check'], { stdio: 'inherit' });
    if (check.status !== 0) console.warn('Fix what --check lists, then run cut.js again.');
  }
}

if (require.main === module) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}

module.exports = { keepSegments };
