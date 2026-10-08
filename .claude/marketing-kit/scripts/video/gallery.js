#!/usr/bin/env node
'use strict';
/*
 * Builds the template gallery shown in the README: one strip per group of templates, each tile
 * a template's middle scene (or the moment PICK names), settled, with its name under it. Run it
 * after changing templates.
 *
 * Usage: node gallery.js [--out ../../docs/gallery]
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const r = require('./render');

const GROUPS = {
  marketing: ['promo', 'how-to', 'narrated', 'testimonial', 'faq', 'announcement', 'team'],
  'meme-captions': ['pov', 'nobody-me', 'expectation-reality', 'tell-me-without', 'makes-sense', 'starter-pack'],
  'comment-bait': ['tier-list', 'this-or-that', 'hot-take', 'flags', 'quiz', 'rating'],
  'skits-and-stories': ['text-chat', 'notifications', 'post-card', 'storytime', 'countdown', 'reveal', 'before-after'],
};
const TILE = { w: 270, h: 480 };
// where a template's middle scene isn't its best face: a time in seconds, or a scene number (0-based)
const PICK = { narrated: { t: 1.2 }, testimonial: { slide: 3 }, team: { slide: 4 } };

async function main() {
  const argv = process.argv.slice(2);
  const at = argv.indexOf('--out');
  const out = path.resolve(at >= 0 ? argv[at + 1] : path.join(__dirname, '..', '..', 'docs', 'gallery'));
  fs.mkdirSync(out, { recursive: true });
  const { chromium } = r.loadPlaywright();
  const browser = await r.launchBrowser(chromium);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'gallery-'));
  for (const [group, names] of Object.entries(GROUPS)) {
    const tiles = [];
    for (const name of names) {
      const { page, settings } = await r.preparePage(browser, path.join(__dirname, 'templates', `${name}.html`), {});
      const times = await r.slideTimes(page, settings.duration);
      const pick = PICK[name] || {};
      await r.seek(page, pick.t ?? times[pick.slide ?? Math.floor((times.length - 1) / 2)]);
      const file = path.join(tmp, `${name}.png`);
      await page.screenshot({ path: file });
      await page.close();
      tiles.push({ name, file });
    }
    // each tile scaled down with its name in a band underneath, then side by side
    const inputs = tiles.flatMap((t) => ['-i', t.file]);
    const labeled = tiles.map((t, i) => `[${i}:v]scale=${TILE.w}:${TILE.h},pad=${TILE.w}:${TILE.h + 44}:0:0:color=0x16161c,`
      + `drawtext=text='${t.name}':x=(w-text_w)/2:y=${TILE.h + 11}:fontsize=22:fontcolor=0xd8d7de[t${i}]`).join(';');
    const filter = `${labeled};${tiles.map((_, i) => `[t${i}]`).join('')}hstack=inputs=${tiles.length}`;
    const file = path.join(out, `${group}.jpg`);
    const run = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...inputs, '-filter_complex', filter, '-frames:v', '1', '-q:v', '4', file], { encoding: 'utf8' });
    if (run.status !== 0) throw new Error(run.stderr);
    console.log(`${file} (${tiles.length} templates)`);
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
