#!/usr/bin/env node
'use strict';
/*
 * The QA pass for rendered videos: checks every template (or the pages you
 * name) the way a careful reviewer would, and writes a report.
 *
 * For each page:
 * - layout lint over the whole timeline (safe zone, overflow, clipping,
 *   text running into other text or elements), and the retention checks: text on
 *   the first frame, nothing too brief to read, and pacing notes
 * - every hook variant (data-variant) separately
 * - every data-sfx cue and music setting resolves, and media and fonts load
 * - a contact sheet of each scene's settled frame, to look over by eye
 * - the soundtrack, measured: about -14 LUFS, true peak at or under -1 dBTP
 *
 * Usage: node check.js [page.html ...] [--out dir] [--no-audio]
 * With no pages, checks every template in templates/. Exits 1 if anything
 * needs attention; the report is <out>/report.md (default: check-report/).
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const r = require('./render');

function parseArgs(argv) {
  const args = { pages: [], audio: true, out: path.join(__dirname, 'check-report') };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--out') args.out = argv[++i];
    else if (argv[i] === '--no-audio') args.audio = false;
    else if (argv[i] === '-h' || argv[i] === '--help') args.help = true;
    else args.pages.push(argv[i]);
  }
  return args;
}

function contactSheet(files, out) {
  const cols = Math.min(6, files.length);
  const rows = Math.ceil(files.length / cols);
  const inputs = files.flatMap((f) => ['-i', f]);
  const scaled = files.map((_, i) => `[${i}:v]scale=270:480[s${i}]`).join(';');
  // pad the grid with black cells so xstack always has a full layout
  const layout = files.map((_, i) => `${(i % cols) * 278}_${Math.floor(i / cols) * 488}`).join('|');
  const filter = files.length === 1
    ? '[0:v]scale=270:480[out]'
    : `${scaled};${files.map((_, i) => `[s${i}]`).join('')}xstack=inputs=${files.length}:layout=${layout}:fill=white[out]`;
  const run = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...inputs, '-filter_complex', filter, '-map', '[out]', '-frames:v', '1', out], { encoding: 'utf8' });
  return run.status === 0 ? out : null;
}

async function checkPage(browser, pagePath, outDir, withAudio, variant) {
  const name = path.basename(pagePath, '.html') + (variant ? `-${variant}` : '');
  const result = { name, page: pagePath, problems: [], lint: [], pacing: [], slides: 0, audio: null, sheet: null };
  const { page, problems: fontProblems } = await r.openPage(browser, pagePath);
  try {
    if (variant) await r.applyVariant(page, variant);
    const mediaProblems = await r.prepareMedia(page);
    const settings = await r.readPage(page);
    result.problems.push(...fontProblems, ...settings.problems, ...mediaProblems, ...r.checkMusic(settings));
    // voice lines measured and captions placed before linting, so the lint covers them
    result.problems.push(...(await r.prepareVoices(page, settings)).problems);
    const duration = settings.duration;
    if (!(duration > 0)) {
      result.problems.push('no <body data-duration>');
      return result;
    }
    result.duration = duration;
    result.music = settings.musicFile ? 'licensed track' : settings.music;
    result.cues = settings.cues.length;

    const lint = await r.lintTimeline(page, duration);
    result.lint = lint.filter((p) => !p.advice);
    result.pacing = lint.filter((p) => p.advice);

    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), `check-${name}-`));
    const times = await r.slideTimes(page, duration);
    const shots = [];
    for (let i = 0; i < times.length; i++) {
      await r.seek(page, times[i]);
      const file = path.join(tmp, `slide_${String(i + 1).padStart(2, '0')}.png`);
      await page.screenshot({ path: file });
      shots.push(file);
    }
    result.slides = shots.length;
    result.sheet = contactSheet(shots, path.join(outDir, `${name}.png`));

    if (withAudio) {
      const m4a = path.join(outDir, `${name}.m4a`);
      r.writeSoundtrack(settings, duration, tmp, null, m4a);
      const level = r.measureAudio(m4a);
      result.audio = level;
      if (Number.isFinite(level.lufs) && Math.abs(level.lufs + 14) > 0.6) result.problems.push(`loudness ${level.lufs} LUFS, not about -14`);
      if (level.truePeak > -1) result.problems.push(`true peak ${level.truePeak} dBTP, above -1`);
    }
    fs.rmSync(tmp, { recursive: true, force: true });
  } catch (e) {
    result.problems.push(`check crashed: ${e.message.split('\n')[0]}`);
  } finally {
    await page.close();
  }
  return result;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    return;
  }
  const pages = args.pages.length ? args.pages
    : fs.readdirSync(path.join(__dirname, 'templates')).filter((f) => f.endsWith('.html')).sort().map((f) => path.join(__dirname, 'templates', f));
  const withAudio = args.audio && spawnSync('ffmpeg', ['-version']).status === 0;
  fs.mkdirSync(args.out, { recursive: true });

  const { chromium } = r.loadPlaywright();
  const browser = await r.launchBrowser(chromium);
  const results = [];
  for (const p of pages) {
    // a page with hook variants is checked once per variant
    const probe = await r.openPage(browser, p);
    const variants = await r.variantsOf(probe.page);
    await probe.page.close();
    for (const v of variants.length ? variants : [null]) {
      process.stderr.write(`checking ${path.basename(p)}${v ? ` [variant ${v}]` : ''}... `);
      const res = await checkPage(browser, p, args.out, withAudio, v);
      process.stderr.write(res.problems.length || res.lint.length ? `${res.problems.length + res.lint.length} to fix\n` : 'ok\n');
      results.push(res);
    }
  }
  await browser.close();

  const bad = results.filter((x) => x.problems.length || x.lint.length);
  const lines = [
    '# Video check',
    '',
    `${results.length} page(s) checked, ${bad.length} need attention.${withAudio ? '' : ' Audio not checked (no ffmpeg, or --no-audio).'}`,
    '',
    '| Page | Length | Music | Cues | Slides | Loudness | Peak | Status |',
    '|---|---|---|---|---|---|---|---|',
    ...results.map((x) => `| ${x.name} | ${x.duration ?? '?'}s | ${x.music ?? ''} | ${x.cues ?? ''} | ${x.slides} | ${x.audio ? `${x.audio.lufs} LUFS` : ''} | ${x.audio ? `${x.audio.truePeak} dBTP` : ''} | ${x.problems.length || x.lint.length ? 'fix' : 'ok'} |`),
    '',
  ];
  for (const x of results) {
    if (!x.problems.length && !x.lint.length && !x.pacing.length) continue;
    lines.push(`## ${x.name}`, '', ...x.problems.map((p) => `- ${p}`), ...x.lint.map((p) => `- Layout: ${r.describeLint(p)}`),
      ...x.pacing.map((p) => `- Pacing (advice, not a failure): ${r.describeLint(p)}`), '');
  }
  lines.push('Contact sheets (each scene\'s settled frame) are next to this report as <page>.png; look them over for anything a lint can\'t judge: legibility, emoji, and whether it looks good.', '');
  fs.writeFileSync(path.join(args.out, 'report.md'), lines.join('\n'));
  console.log(lines.slice(0, results.length + 6).join('\n'));
  console.log(`Report: ${path.join(args.out, 'report.md')}`);
  process.exit(bad.length ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
