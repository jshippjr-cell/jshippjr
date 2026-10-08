#!/usr/bin/env node
'use strict';
/*
 * Renders an animated HTML page into a vertical MP4 (1080x1920, 9:16, 30fps,
 * H.264 + AAC) ready for YouTube Shorts, Instagram Reels, or TikTok, with an
 * original soundtrack synced to the page's own animation cues.
 *
 * The page animates with CSS animations (or the Web Animations API). This
 * script pauses every animation and seeks it frame by frame in headless
 * Chromium, so the output is frame-exact no matter how slow the machine is.
 * See templates/promo.html for the page conventions, and docs/video.md,
 * "Rendering a short-form video locally".
 *
 * Usage:
 *   node render.js <page.html> <out.mp4> [--duration 24] [--fps 30] [--silent] [--workers 3]
 *   node render.js <page.html> <out.mp4> --draft                   # half size at 15fps, fast, to check timing
 *   node render.js --batch <page.html> ... [--outdir dir]          # each page to <page>.mp4, every variant, in one run
 *   node render.js <page.html> --stills 1.5,6,12 [--outdir dir]   # preview PNGs (default: stills/ next to the page)
 *   node render.js <page.html> --slides [--outdir dir]             # each scene's settled frame as a PNG, for
 *                                                                   # TikTok photo mode / Instagram carousels
 *   node render.js <page.html> --check                             # layout lint over the whole timeline only
 *   node render.js <page.html> <out.m4a> --audio-only              # just the soundtrack, in seconds
 *   node render.js --sample <genre> <out.m4a> [--motif "1 3 5 6 | 5 3 2 -"] [--key C] [--mode major]
 *                  [--bpm 118] [--energy 3] [--duration 12]          # audition a sound with no page at all
 *   node render.js <page.html> --voice-lengths                     # each voice line's start, length, and room in its scene
 *   node render.js <page.html> --cover 0 [--outdir dir]            # the cover frame as a PNG, checked against the 3:4 grid crop
 *                                                                   # (with <out.mp4>, it's written next to the video too)
 *   node render.js <page.html> <out.mp4> --variants a,b,c          # one video per hook variant: out-a.mp4, out-b.mp4, ...
 *                                                                   # (--variant a for just one; --check checks them all)
 *
 * A voiceover goes in with <body data-voice-src="assets/voice.m4a"> (one take, starting at
 * data-voice-start) or data-voice="assets/line-2.m4a" on any element (plays at its --voice
 * or --in time). The music and effects duck under it. An element with class "say auto" and a
 * data-voice clip gets word-by-word captions of its own text, timed to the clip (captions.js;
 * add --whisper to time them with Whisper instead), and a render with captions also writes
 * an .srt next to the video. Every voice line is checked against its scene's end.
 *
 * Every run lints the layout: text outside the platforms' safe zone,
 * overflowing or clipped, or colliding with other text is reported with its
 * time, which is how copy that runs long gets caught.
 *
 * Needs: Node 18+, ffmpeg (with libx264 and aac) on PATH, and Playwright
 * (`npm install` in this folder, then `npx playwright install chromium`, or
 * an installed Google Chrome, which is used as a fallback).
 */
const { spawn, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { fileURLToPath, pathToFileURL } = require('url');
const { buildSoundtrack, wavBuffer, parseMotif, SOUNDS, GENRES } = require('./soundtrack');
const captions = require('./captions');

const WIDTH = 1080;
const HEIGHT = 1920;
// Audio is mixed to -14 LUFS, what YouTube, Instagram, and TikTok normalize
// to, with the true peak at or under -1 dBTP so a platform's re-encode
// doesn't clip it. PRE goes first: a low-pass, because the noise-based
// sounds carry energy right up to 24 kHz (inter-sample peaks a limiter can't
// see, and phone speakers can't play), then a limiter that shaves the click
// and pluck transients so the gain needed for -14 LUFS doesn't push them up
// with it.
const PRE = 'lowpass=f=16000:poles=2,alimiter=limit=0.25:attack=5:release=60:level=false';
const TARGET_LUFS = -14;
const MAX_TRUE_PEAK = -1;
// The final limiter runs at 192 kHz (4x) so it catches peaks between
// samples. AAC encoding can still overshoot unpredictably, so the result is
// measured and re-encoded with the next lower ceiling until it fits.
const CEILINGS = [0.79, 0.75, 0.7, 0.63];

function fail(message) {
  console.error(message);
  process.exit(2);
}

function parseArgs(argv) {
  const args = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--silent') args.silent = true;
    else if (a === '--audio-only') args.audioOnly = true;
    else if (a === '--check') args.check = true;
    else if (a === '--slides') args.slides = true;
    else if (a === '--voice-lengths') args.voiceLengths = true;
    else if (a === '--whisper') args.whisper = true;
    else if (a === '--draft') args.draft = true;
    else if (a === '--batch') args.batch = true;
    else if (['--duration', '--fps', '--stills', '--outdir', '--sample', '--motif', '--key', '--mode', '--bpm', '--energy', '--variant', '--variants', '--cover', '--workers'].includes(a)) args[a.slice(2)] = argv[++i];
    else if (a === '-h' || a === '--help') args.help = true;
    else args.positional.push(a);
  }
  return args;
}

function loadPlaywright() {
  for (const name of ['playwright', 'playwright-core']) {
    try {
      return require(name);
    } catch (e) {
      if (e.code !== 'MODULE_NOT_FOUND') throw e;
    }
  }
  fail(
    'Playwright is not installed. From this folder (scripts/video) run:\n' +
      '  npm install\n  npx playwright install chromium\n' +
      '(The second step can be skipped if Google Chrome is installed; it is used as a fallback.)'
  );
}

async function launchBrowser(chromium) {
  try {
    return await chromium.launch();
  } catch (e) {
    // no Playwright-managed Chromium downloaded: try the user's own Chrome before giving up
    try {
      return await chromium.launch({ channel: 'chrome' });
    } catch {
      fail(`Couldn't start a browser: ${e.message.split('\n')[0]}\nRun \`npx playwright install chromium\` in scripts/video, or install Google Chrome.`);
    }
  }
}

// Web fonts (Google Fonts) are fetched by Node and cached, not by the browser: renders then
// work offline after the first run, and behind proxies the bundled Chromium doesn't trust.
const FONT_HOSTS = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;
const FONT_CACHE = path.join(os.homedir(), '.cache', 'marketing-skill', 'fonts');

async function routeFonts(page) {
  await page.route(FONT_HOSTS, async (route) => {
    const url = route.request().url();
    const file = path.join(FONT_CACHE, crypto.createHash('sha1').update(url).digest('hex'));
    try {
      if (!fs.existsSync(file)) {
        const res = await fetch(url, { headers: { 'user-agent': route.request().headers()['user-agent'] } });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = Buffer.from(await res.arrayBuffer());
        fs.mkdirSync(FONT_CACHE, { recursive: true });
        fs.writeFileSync(`${file}.type`, res.headers.get('content-type') || 'application/octet-stream');
        fs.writeFileSync(file, body);
      }
      await route.fulfill({
        body: fs.readFileSync(file),
        contentType: fs.readFileSync(`${file}.type`, 'utf8'),
        headers: { 'access-control-allow-origin': '*' },
      });
    } catch {
      await route.continue();
    }
  });
}

// Opens a page at the frame size with its fonts loaded. Returns the page and any fonts that
// failed, since a fallback font changes every line break the layout lint checks.
async function openPage(browser, pagePath) {
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
  await routeFonts(page);
  await page.goto('file://' + path.resolve(pagePath), { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  const failed = await page.evaluate(() => {
    const out = new Set();
    for (const f of document.fonts) if (f.status === 'error') out.add(f.family.replace(/"/g, ''));
    for (const l of document.querySelectorAll('link[rel="stylesheet"]')) {
      if (/fonts\.googleapis\.com/.test(l.href) && ![...document.fonts].length) out.add('Google Fonts stylesheet');
    }
    return [...out];
  });
  const problems = failed.length
    ? [`web fonts didn't load (${failed.join(', ')}), so text uses a fallback font; connect to the internet once so they cache`]
    : [];
  return { page, problems };
}

function requireFfmpeg() {
  const probe = spawnSync('ffmpeg', ['-hide_banner', '-encoders'], { encoding: 'utf8' });
  if (probe.error || probe.status !== 0) fail('ffmpeg was not found on PATH. Install it (e.g. `brew install ffmpeg` or `apt install ffmpeg`) and retry.');
  for (const enc of ['libx264', 'aac']) {
    if (!probe.stdout.includes(` ${enc} `)) fail(`This ffmpeg build has no ${enc} encoder, which the platforms' upload specs need. Install a full ffmpeg build.`);
  }
}

function ffmpeg(args) {
  const run = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...args], { encoding: 'utf8' });
  if (run.status !== 0) fail(`ffmpeg failed: ${run.stderr}`);
}

// Pause every animation on the page and jump it to `seconds`. Background
// videos (swapped for frame sequences by prepareMedia) jump too: a clip
// starts at its --in time, inherited from its .bg layer, from data-offset
// seconds into the clip, and loops unless data-loop="false".
async function seek(page, seconds) {
  await page.evaluate(async (t) => {
    for (const a of document.getAnimations()) {
      a.pause();
      a.currentTime = t * 1000;
    }
    const toSeconds = (v) => {
      v = (v || '').trim();
      return v.endsWith('ms') ? parseFloat(v) / 1000 : parseFloat(v) || 0;
    };
    const decodes = [];
    for (const img of document.querySelectorAll('img[data-frames]')) {
      const count = Number(img.dataset.count);
      let local = Math.max(0, t - toSeconds(getComputedStyle(img).getPropertyValue('--in'))) + toSeconds(img.dataset.offset);
      let frame = Math.floor(local * 30 + 1e-6);
      frame = img.dataset.loop === 'false' ? Math.min(frame, count - 1) : frame % count;
      const src = `${img.dataset.frames}/${String(frame + 1).padStart(5, '0')}.jpg`;
      if (img.getAttribute('src') !== src) {
        img.src = src;
        decodes.push(img.decode().catch(() => null));
      }
    }
    await Promise.all(decodes);
    return new Promise(requestAnimationFrame);
  }, seconds);
}

const hasFfmpeg = () => spawnSync('ffmpeg', ['-version']).status === 0;

// Average brightness of an image, 0 (black) to 1 (white), or null without ffmpeg.
function meanLuma(file) {
  if (!hasFfmpeg()) return null;
  const run = spawnSync('ffmpeg', ['-loglevel', 'error', '-i', file, '-frames:v', '1', '-vf', 'scale=36:64,format=gray', '-f', 'rawvideo', '-']);
  if (run.status !== 0 || !run.stdout.length) return null;
  let sum = 0;
  for (const b of run.stdout) sum += b;
  return sum / run.stdout.length / 255;
}

// Background videos become a 1080x1920 30fps JPEG frame sequence (made once,
// cached across runs), and each <video> is swapped for an <img> that seek()
// points at the right frame. That's exact on any frame, and it doesn't depend
// on the browser's video codecs (Playwright's Chromium can't play H.264).
// Images are decoded up front. Returns problems to warn about.
async function prepareMedia(page) {
  const problems = [];
  // A clip that fills the frame (a background) is cut to 1080x1920. One in a smaller box, like a
  // screen recording in the phone frame, is cut to that box's own shape instead, so a tall
  // recording isn't cropped to 9:16 first and then cropped again to fit the box.
  const videos = await page.evaluate(() => [...document.querySelectorAll('video')].map((v, i) => {
    v.dataset.renderIndex = String(i);
    const full = !!v.closest('.bg') || !v.offsetWidth || !v.offsetHeight;
    return { src: v.currentSrc || v.src || v.querySelector('source')?.src || '', w: full ? 0 : v.offsetWidth, h: full ? 0 : v.offsetHeight };
  }));
  const cacheDir = path.join(os.tmpdir(), 'render-video-cache');
  if (videos.length && !hasFfmpeg()) {
    problems.push('ffmpeg is needed to render background videos; they will be blank');
    return problems;
  }
  for (let i = 0; i < videos.length; i++) {
    const { src, w, h } = videos[i];
    // twice the box's size for sharpness, within the frame, in even numbers for the encoder
    const scale = w ? Math.min(2, WIDTH / w, HEIGHT / h) : 1;
    const W = w ? 2 * Math.round((w * scale) / 2) : WIDTH;
    const H = h ? 2 * Math.round((h * scale) / 2) : HEIGHT;
    if (!src.startsWith('file:')) {
      problems.push(`video ${src || '(no src)'} isn't a local file; download it into assets/ first (media.js does this)`);
      continue;
    }
    const file = fileURLToPath(src);
    if (!fs.existsSync(file)) {
      problems.push(`video not found: ${file}`);
      continue;
    }
    const st = fs.statSync(file);
    const key = crypto.createHash('sha1').update(`${file}|${st.size}|${st.mtimeMs}|${W}x${H}`).digest('hex').slice(0, 16);
    const dir = path.join(cacheDir, key);
    if (!fs.existsSync(path.join(dir, 'done'))) {
      fs.rmSync(dir, { recursive: true, force: true });
      fs.mkdirSync(dir, { recursive: true });
      ffmpeg(['-i', file, '-vf', `scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},fps=30`,
        '-q:v', '3', path.join(dir, '%05d.jpg')]);
      fs.writeFileSync(path.join(dir, 'done'), '');
    }
    const count = fs.readdirSync(dir).filter((f) => f.endsWith('.jpg')).length;
    await page.evaluate(([index, framesUrl, n]) => {
      const v = document.querySelector(`video[data-render-index="${index}"]`);
      const img = document.createElement('img');
      for (const { name, value } of v.attributes) if (!['src', 'autoplay', 'loop', 'muted', 'controls', 'playsinline', 'preload', 'data-render-index'].includes(name)) img.setAttribute(name, value);
      img.dataset.frames = framesUrl;
      img.dataset.count = String(n);
      img.dataset.srcFile = v.currentSrc || v.src || v.querySelector('source')?.src || '';
      img.src = `${framesUrl}/00001.jpg`;
      img.alt = '';
      v.replaceWith(img);
    }, [i, pathToFileURL(dir).href, count]);
  }
  // Darken each background just enough for white text: brighter media gets a heavier --shade,
  // unless the page set one on the slot itself.
  const slots = await page.evaluate(() => [...document.querySelectorAll('.bg')].map((bg, i) => {
    const media = bg.querySelector('.bg-media');
    if (!media || bg.style.getPropertyValue('--shade')) return null;
    const src = media.dataset.frames ? `${media.dataset.frames}/00001.jpg` : media.currentSrc || media.src;
    return src && src.startsWith('file:') ? { i, src } : null;
  }).filter(Boolean));
  for (const { i, src } of slots) {
    const luma = meanLuma(fileURLToPath(src));
    if (luma === null) continue;
    // grade (x0.9) and the scrim's middle band (x0.8) then bring the area behind text to about 0.22
    const shade = Math.min(0.75, Math.max(0.25, 1 - 0.22 / (0.72 * luma))).toFixed(2);
    await page.evaluate(([index, value]) => document.querySelectorAll('.bg')[index].style.setProperty('--shade', value), [i, shade]);
  }

  const images = await page.evaluate(async () => Promise.all([...document.images].map(async (img) => {
    try { await img.decode(); } catch { /* reported below */ }
    return { src: img.getAttribute('src'), w: img.naturalWidth, h: img.naturalHeight, bg: !!img.closest('.bg') };
  })));
  for (const img of images) {
    if (!img.w) problems.push(`image didn't load: ${img.src}`);
    else if (img.bg && (img.w < 1080 || img.h < 1920)) problems.push(`background ${img.src} is ${img.w}x${img.h}, under 1080x1920; it will look soft`);
  }
  return problems;
}

// Platform UI covers the top ~150px (tabs), the bottom ~470px (caption, sound), and the
// right ~120px (like/comment/share); text has to stay clear of all three.
const SAFE_ZONE = { left: 60, right: 960, top: 150, bottom: 1450 };

// Checks every visible, settled text element at the current moment: inside the safe zone,
// not overflowing its own box, not clipped by an overflow:hidden ancestor, and not
// colliding with other text. Text mid-animation is skipped, since it's moving on purpose.
// Add data-lint="off" to an element to exempt it and everything inside it.
async function lintLayout(page, seconds) {
  return page.evaluate(([t, safe]) => {
    const problems = [];
    const moving = (el) => {
      for (let e = el; e; e = e.parentElement) {
        for (const a of e.getAnimations()) {
          const c = a.effect.getComputedTiming();
          if (c.activeDuration === Infinity || c.localTime === null) continue;
          if (c.localTime > c.delay && c.localTime < c.delay + c.activeDuration) return true;
        }
      }
      return false;
    };
    const opacity = (el) => {
      let o = 1;
      for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
        o *= parseFloat(cs.opacity);
      }
      return o;
    };
    const snippet = (el) => el.textContent.trim().replace(/\s+/g, ' ').slice(0, 48);
    const texts = [];
    for (const el of document.body.querySelectorAll('*')) {
      if (el.closest('.bg, .bg-media, [data-lint="off"], script, style')) continue;
      if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      if (opacity(el) < 0.5 || moving(el)) continue;
      const range = document.createRange();
      range.selectNodeContents(el);
      const rects = [...range.getClientRects()].filter((r) => r.width > 1 && r.height > 1);
      if (!rects.length) continue;
      const box = {
        left: Math.min(...rects.map((r) => r.left)), right: Math.max(...rects.map((r) => r.right)),
        top: Math.min(...rects.map((r) => r.top)), bottom: Math.max(...rects.map((r) => r.bottom)),
      };
      // glyph boxes of display type with a tight line-height reach past the line box by design,
      // so vertical checks allow a third of the font size
      const slack = Math.max(4, 0.35 * parseFloat(getComputedStyle(el).fontSize));
      texts.push({ el, box, slack, rects });
      if (box.left < safe.left - 2 || box.right > safe.right + 2 || box.top < safe.top - slack || box.bottom > safe.bottom + slack) {
        problems.push({ t, kind: 'outside the safe zone', text: snippet(el),
          detail: `x ${Math.round(box.left)}-${Math.round(box.right)}, y ${Math.round(box.top)}-${Math.round(box.bottom)}` });
      }
      const own = el.getBoundingClientRect();
      if (box.right > own.right + 4 || box.left < own.left - 4 || box.bottom > own.bottom + slack) {
        problems.push({ t, kind: 'overflows its box', text: snippet(el) });
      }
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (cs.overflow === 'visible' && cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
        const r = a.getBoundingClientRect();
        if (box.left < r.left - 2 || box.right > r.right + 2 || box.top < r.top - slack || box.bottom > r.bottom + slack) {
          problems.push({ t, kind: 'clipped by its container', text: snippet(el) });
          break;
        }
      }
    }
    // text running into a box it isn't part of (a card, phone frame, image, bubble)
    const boxes = [];
    for (const el of document.body.querySelectorAll('*')) {
      if (el.closest('.bg, .bg-media, .glow, [data-lint="off"], script, style')) continue;
      const cs = getComputedStyle(el);
      const filled = (cs.backgroundColor && !/rgba\(.*,\s*0(\.0*)?\)$|transparent/.test(cs.backgroundColor)) || cs.backgroundImage !== 'none';
      const bordered = ['Top', 'Right', 'Bottom', 'Left'].some((side) => parseFloat(cs[`border${side}Width`]) > 0 && !/rgba\(.*,\s*0(\.0*)?\)$|transparent/.test(cs[`border${side}Color`]));
      if (!(filled || bordered || el.tagName === 'IMG')) continue;
      if (opacity(el) < 0.5 || moving(el)) continue;
      boxes.push({ el, r: el.getBoundingClientRect() });
    }
    // checked line by line: one covered line is a problem however wide the paragraph is
    for (const t0 of texts) {
      const hit = boxes.find((b) => !b.el.contains(t0.el) && !t0.el.contains(b.el) && t0.rects.some((line) => {
        const w = Math.min(line.right, b.r.right) - Math.max(line.left, b.r.left);
        const h = Math.min(line.bottom - t0.slack / 2, b.r.bottom) - Math.max(line.top + t0.slack / 2, b.r.top);
        return w > 30 && h > 6;
      }));
      if (hit) problems.push({ t, kind: 'runs into another element', text: snippet(t0.el), detail: `<${hit.el.tagName.toLowerCase()} class="${hit.el.className}">` });
    }

    for (let i = 0; i < texts.length; i++) {
      for (let j = i + 1; j < texts.length; j++) {
        const a = texts[i];
        const b = texts[j];
        if (a.el.contains(b.el) || b.el.contains(a.el)) continue;
        const w = Math.min(a.box.right, b.box.right) - Math.max(a.box.left, b.box.left);
        const h = Math.min(a.box.bottom - a.slack / 2, b.box.bottom - b.slack / 2) - Math.max(a.box.top + a.slack / 2, b.box.top + b.slack / 2);
        if (w <= 0 || h <= 0) continue;
        const smaller = Math.min((a.box.right - a.box.left) * (a.box.bottom - a.box.top), (b.box.right - b.box.left) * (b.box.bottom - b.box.top));
        if (w * h > 0.2 * smaller) problems.push({ t, kind: 'overlaps other text', text: `${snippet(a.el)} / ${snippet(b.el)}` });
      }
    }
    return problems;
  }, [seconds, SAFE_ZONE]);
}

// What text is readable right now, and whether anything is moving: each visible text element
// (an id that stays with it across seeks, its word count, and whether it's a caption synced to
// a voice), and `active` if any finite animation outside the background is mid-flight.
async function textSnapshot(page) {
  return page.evaluate(() => {
    const out = { texts: [], active: false };
    const opacity = (el) => {
      let o = 1;
      for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
        o *= parseFloat(cs.opacity);
      }
      return o;
    };
    for (const el of document.body.querySelectorAll('*')) {
      if (el.closest('.bg, .bg-media, [data-lint="off"], script, style')) continue;
      if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      if (opacity(el) < 0.5) continue;
      if (!el.dataset.lintId) el.dataset.lintId = String((window.lintIds = (window.lintIds || 0) + 1));
      const text = el.textContent.trim().replace(/\s+/g, ' ');
      out.texts.push({ id: el.dataset.lintId, words: text.split(' ').length, text: text.slice(0, 48), synced: !!el.closest('.say') });
    }
    for (const a of document.getAnimations()) {
      const target = a.effect && a.effect.target;
      if (!target || target.closest('.bg, .glow')) continue;
      const c = a.effect.getComputedTiming();
      if (c.activeDuration === Infinity || c.localTime === null) continue;
      if (c.localTime > c.delay && c.localTime < c.delay + c.activeDuration) {
        out.active = true;
        break;
      }
    }
    return out;
  });
}

// Retention checks over the sampled timeline: the first frame (the default cover, and the moment
// a viewer decides to stay) and the first second need text; every caption needs to stay up
// long enough to read (allowing one sample of slack); and, as advice rather than a failure,
// the screen shouldn't sit unchanged for more than STATIC_LIMIT seconds outside a data-break.
// Captions synced to a voice are exempt from the reading check, since they're heard as read.
const READ_WORDS_PER_SECOND = 4;
const STATIC_LIMIT = 3;
function retentionProblems(samples, duration, step, breaks) {
  const problems = [];
  if (!samples.filter((x) => x.t <= 1 + 1e-6).some((x) => x.texts.length)) {
    problems.push({ t: 0, kind: 'no text on screen in the first second', text: '', detail: 'viewers decide in that second, sound off; put the hook on screen from frame 0 (class "now")' });
  } else if (!samples[0].texts.length) {
    problems.push({ t: 0, kind: 'the first frame has no text', text: '', detail: 'it\'s the default cover and the swipe decision; give the hook class "now" instead of an entrance' });
  }
  const shown = new Map();
  for (const x of samples) {
    for (const tx of x.texts) {
      const e = shown.get(tx.id) || { ...tx, first: x.t, count: 0 };
      e.count++;
      shown.set(tx.id, e);
    }
  }
  for (const e of shown.values()) {
    if (e.synced || e.words < 3) continue;
    const need = e.words / READ_WORDS_PER_SECOND + 0.2;
    const up = e.count * step;
    if (up + step < need) {
      problems.push({ t: e.first, kind: 'is on screen too briefly to read', text: e.text, detail: `about ${up.toFixed(1)}s for ${e.words} words; give it ${need.toFixed(1)}s, or cut words` });
    }
  }
  const inBreak = (a, b) => breaks.some(([s, e]) => a >= s - 0.3 && b <= e + 0.3);
  let since = 0;
  let prev = null;
  for (const x of samples) {
    const sig = x.texts.map((tx) => tx.id).sort().join(',');
    if (x.active || sig !== prev) {
      if (x.t - since > STATIC_LIMIT && since < duration - 1.5 && !inBreak(since, x.t)) {
        problems.push({ t: since, kind: 'nothing changes on screen', text: '', advice: true, detail: `${since.toFixed(2)}–${x.t.toFixed(2)}s; fine for a punchline or a list to scan, otherwise add a beat (a new line, a cue, a background change)` });
      }
      since = x.t;
    }
    prev = sig;
  }
  return problems;
}

const parseBreaks = (v) => String(v || '').split(',').map((w) => /^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*$/.exec(w)).filter(Boolean).map((m) => [parseFloat(m[1]), parseFloat(m[2])]);

// Lints the page every `step` seconds, and returns each problem once (at its first time):
// the layout at every sample, then the retention checks over the whole timeline.
async function lintTimeline(page, duration, step = 0.25) {
  const seen = new Map();
  const samples = [];
  for (let t = 0; t <= duration + 1e-6; t += step) {
    const at = Math.min(t, duration - 0.01);
    await seek(page, at);
    for (const p of await lintLayout(page, at)) {
      const key = `${p.kind}|${p.text}`;
      if (!seen.has(key)) seen.set(key, p);
    }
    samples.push({ t: at, ...(await textSnapshot(page)) });
  }
  const breaks = parseBreaks(await page.evaluate(() => document.body.dataset.break));
  return [...seen.values(), ...retentionProblems(samples, duration, step, breaks)];
}

const describeLint = (p) => `${p.t.toFixed(2)}s: ${p.text ? `"${p.text}" ` : ''}${p.kind}${p.detail ? ` (${p.detail})` : ''}`;
// Advice (pacing notes) is shown but doesn't fail a check.
const lintLabel = (p) => (p.advice ? 'Pacing' : 'Layout');

// The settled moment of each scene, just before it leaves: one per .scene, .gone, or .swap exit,
// plus the end. <body data-slides="2.6,6.8,..."> overrides. Used for --slides and check.js.
async function slideTimes(page, duration) {
  return page.evaluate((d) => {
    if (document.body.dataset.slides) return document.body.dataset.slides.split(',').map(Number).filter((n) => n >= 0 && n <= d);
    const toSeconds = (v) => {
      v = (v || '').trim();
      return v.endsWith('ms') ? parseFloat(v) / 1000 : parseFloat(v);
    };
    const outs = new Set();
    for (const el of document.querySelectorAll('.scene, .gone, .swap')) {
      const out = toSeconds(el.style.getPropertyValue('--out'));
      if (out > 0 && out < d) outs.add(Math.round((out - 0.15) * 100) / 100);
    }
    outs.add(Math.round((d - 0.2) * 100) / 100);
    // exits within 0.3s of each other are the same moment (an item leaving with its scene)
    return [...outs].sort((a, b) => a - b).filter((t, i, all) => i === all.length - 1 || all[i + 1] - t > 0.3);
  }, duration);
}

// Settings from <body data-*>, and sound cues from every [data-sfx] element.
// data-sfx="swish:in tick:tick" plays a swish at the element's --in and a
// tick at its --tick (CSS custom properties, e.g. style="--in:3.4s").
async function readPage(page) {
  return page.evaluate((known) => {
    const toSeconds = (v) => {
      v = (v || '').trim();
      if (!v) return NaN;
      return v.endsWith('ms') ? parseFloat(v) / 1000 : parseFloat(v);
    };
    const cues = [];
    const problems = [];
    for (const el of document.querySelectorAll('[data-sfx]')) {
      for (const token of el.dataset.sfx.trim().split(/\s+/)) {
        const [sound, cssVar = 'in'] = token.split(':');
        const time = toSeconds(getComputedStyle(el).getPropertyValue(`--${cssVar}`));
        if (!known.includes(sound)) problems.push(`unknown sound "${sound}" (known: ${known.join(', ')})`);
        else if (Number.isNaN(time)) problems.push(`data-sfx="${token}" but the element has no --${cssVar} time`);
        else cues.push({ sound, time });
      }
    }
    const d = document.body.dataset;
    const num = (v) => (v !== undefined && v !== '' ? parseFloat(v) : undefined);
    // spoken lines: one take on <body>, and/or one clip per element at its --voice (or --in) time
    const voices = [];
    if (d.voiceSrc) voices.push({ src: new URL(d.voiceSrc, location.href).href, time: num(d.voiceStart) || 0 });
    document.querySelectorAll('[data-voice]').forEach((el, index) => {
      const cs = getComputedStyle(el);
      let time = toSeconds(cs.getPropertyValue('--voice'));
      if (Number.isNaN(time)) time = toSeconds(cs.getPropertyValue('--in'));
      if (Number.isNaN(time)) {
        problems.push(`data-voice="${el.dataset.voice}" but the element has no --voice or --in time`);
        return;
      }
      el.dataset.voiceIndex = String(index);
      const scene = el.closest('.scene');
      const sceneOut = scene ? toSeconds(scene.style.getPropertyValue('--out')) : NaN;
      // <div class="say auto" data-voice="..."> gets word-by-word captions of its own text
      const caption = el.matches('.say.auto') ? el.textContent.replace(/\s+/g, ' ').trim() : '';
      voices.push({ src: new URL(el.dataset.voice, location.href).href, time, index, sceneOut, caption });
    });
    // A filmed clip that keeps its own sound: <video data-audio> plays it in sync with the
    // picture, from data-offset seconds into the file, while the clip is on screen. Captions for
    // it go in <div class="say auto" data-clip="<the video's id>">the words said</div>.
    const captionFor = new Map();
    for (const el of document.querySelectorAll('.say.auto[data-clip]')) captionFor.set(el.dataset.clip, el);
    document.querySelectorAll('[data-audio]').forEach((el, k) => {
      const src = el.dataset.srcFile || el.currentSrc || el.src;
      const cs = getComputedStyle(el);
      const time = toSeconds(cs.getPropertyValue('--in')) || 0;
      const holder = el.closest('.bg') || el.closest('.scene');
      const sceneOut = holder ? toSeconds(holder.style.getPropertyValue('--out')) : NaN;
      const capEl = el.id ? captionFor.get(el.id) : null;
      let index;
      if (capEl) {
        index = `clip-${k}`;
        capEl.dataset.voiceIndex = index;
        captionFor.delete(el.id);
      }
      voices.push({
        src, time, index, sceneOut, sync: true, offset: parseFloat(el.dataset.offset) || 0,
        // the sound stops when the clip leaves the screen
        maxLength: Number.isFinite(sceneOut) ? Math.max(0, sceneOut - time) : undefined,
        caption: capEl ? capEl.textContent.replace(/\s+/g, ' ').trim() : '',
      });
    });
    for (const id of captionFor.keys()) problems.push(`a caption has data-clip="${id}" but no <video data-audio id="${id}"> was found`);
    return {
      cues,
      problems,
      voices,
      duration: num(d.duration),
      drop: num(d.drop),
      bpm: num(d.bpm),
      key: d.key,
      mode: d.mode,
      energy: num(d.energy),
      motif: d.motif,
      breaks: d.break || '',
      music: d.music || 'lofi',
      musicSrc: d.musicSrc ? new URL(d.musicSrc, location.href).href : '',
      musicStart: num(d.musicStart) || 0,
      musicAt: num(d.musicAt) || 0,
    };
  }, SOUNDS);
}

// Checks the music settings, warning about anything it has to ignore.
function checkMusic(settings) {
  const problems = [];
  if (settings.music !== 'none' && !GENRES[settings.music]) {
    problems.push(`unknown data-music="${settings.music}" (use ${Object.keys(GENRES).join(', ')}, or none); using lofi`);
    settings.music = 'lofi';
  }
  if (settings.motif) {
    try {
      parseMotif(settings.motif);
    } catch (e) {
      problems.push(`data-motif "${settings.motif}" can't be used (${e.message}); using the genre's default hook`);
      settings.motif = undefined;
    }
  }
  if (settings.key && !/^[A-G](#|b)?$/.test(settings.key)) {
    problems.push(`data-key "${settings.key}" isn't a key like C, F#, or Bb; using C`);
    settings.key = 'C';
  }
  if (settings.mode && !['major', 'minor'].includes(settings.mode)) {
    problems.push(`data-mode "${settings.mode}" should be major or minor; using the genre's default`);
    settings.mode = undefined;
  }
  settings.breaks = String(settings.breaks || '').split(',').map((w) => w.trim()).filter(Boolean).map((w) => {
    const m = /^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/.exec(w);
    if (!m) problems.push(`data-break "${w}" should look like 8.5-13.5`);
    return m && [parseFloat(m[1]), parseFloat(m[2])];
  }).filter(Boolean);
  if (settings.musicSrc) {
    const file = settings.musicSrc.startsWith('file:') ? fileURLToPath(settings.musicSrc) : '';
    if (!file || !fs.existsSync(file)) {
      problems.push(`data-music-src not found (${file || settings.musicSrc}); using the generated music instead`);
      settings.musicSrc = '';
    } else {
      settings.musicFile = file;
    }
  }
  settings.voiceClips = [];
  for (const v of settings.voices || []) {
    const file = v.src.startsWith('file:') ? fileURLToPath(v.src) : '';
    if (!file || !fs.existsSync(file)) problems.push(`voice clip not found (${file || v.src}); leaving it out`);
    else settings.voiceClips.push({ ...v, file });
  }
  return problems;
}

// Warnings about the mix as a whole, once the video's length is known.
const LONG_FOR_GENERATED_MUSIC = 45;
function checkMix(settings, duration) {
  const problems = [];
  if (!settings.musicFile && settings.music !== 'none' && duration > LONG_FOR_GENERATED_MUSIC) {
    problems.push(`the generated music is written for short videos and repeats the same few bars, so over ${Math.round(duration)}s it gets monotonous; use a licensed track (data-music-src) for a video this long`);
  }
  const cues = settings.cues.filter((c) => c.time < duration).length;
  if ((settings.voiceClips || []).length && cues > duration / 3) {
    problems.push(`${cues} sound effects under a voiceover is one every ${(duration / cues).toFixed(1)}s, and effects compete with speech; keep them to scene changes and key moments (one every 3s or fewer)`);
  }
  return problems;
}

const hasAudioStream = (file) => /audio/.test(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', file], { encoding: 'utf8' }).stdout);
const probeDuration = (file) => parseFloat(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file], { encoding: 'utf8' }).stdout);

// Mixes a licensed track (trimmed, faded) under the generated sound effects, dipping it a
// few dB on each effect so they still land, and writes the result to `out` as a WAV.
// `at` is when the music comes in (data-music-at), for a track shorter than the video or an
// opening that plays without it.
function mixLicensedTrack(trackFile, start, duration, sfxWav, out, at = 0) {
  const trackLen = probeDuration(trackFile);
  const problems = [];
  const room = Math.max(0, duration - at);
  if (Number.isFinite(trackLen) && trackLen - start < room - 0.05) {
    problems.push(`the track has only ${(trackLen - start).toFixed(1)}s from data-music-start=${start}s for the ${room.toFixed(1)}s it plays${at ? ` (from data-music-at=${at}s)` : ''}, so the music will stop early; pick an earlier data-music-start, a later data-music-at, or a longer track`);
  }
  const fadeOut = Math.max(0, duration - 1.5).toFixed(2);
  const delay = at > 0 ? `,adelay=${Math.round(at * 1000)}:all=1` : '';
  ffmpeg(['-ss', String(start), '-t', String(room), '-i', trackFile, '-i', sfxWav, '-filter_complex',
    `[0:a]aresample=48000,aformat=channel_layouts=stereo,afade=t=in:d=0.3${delay},apad,atrim=0:${duration},afade=t=out:st=${fadeOut}:d=1.5,volume=0.8[m];` +
    '[1:a]asplit=2[fx][key];[m][key]sidechaincompress=threshold=0.04:ratio=2.5:attack=5:release=180[ducked];' +
    '[ducked][fx]amix=inputs=2:normalize=0', '-ar', '48000', '-c:a', 'pcm_s16le', out]);
  return problems;
}

// Integrated loudness (LUFS) and true peak (dBTP) of a file's audio, via ffmpeg's EBU R128 meter.
function measureAudio(file, filter = '') {
  const run = spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', file, '-map', '0:a',
    '-af', `${filter}${filter ? ',' : ''}ebur128=peak=true`, '-f', 'null', '-'], { encoding: 'utf8' });
  const summary = run.stderr.slice(run.stderr.lastIndexOf('Summary:'));
  const value = (re) => {
    const m = re.exec(summary);
    return m ? (m[1] === '-inf' ? -Infinity : parseFloat(m[1])) : NaN;
  };
  return { lufs: value(/I:\s+(-?[\d.]+|-inf) LUFS/), truePeak: value(/Peak:\s+(-?[\d.]+|-inf) dBFS/) };
}

// The voice is leveled low here so the peak limiter in muxSoundtrack (PRE) leaves speech alone;
// muxSoundtrack then brings the whole mix up to -14 LUFS. The music and effects sit
// BED_UNDER_VOICE dB under it, and duck about 10 dB more while someone is speaking.
const VOICE_LUFS = -26;
const BED_UNDER_VOICE = 7;

// Cleans up and levels one spoken line, so lines recorded at different distances match: low
// rumble filtered, silence trimmed from both ends (the line starts at its cue, and its length
// is the speech itself), light compression, then leveled to VOICE_LUFS. Cached across runs.
// Returns { prepared, length, trimmed }, where trimmed is how much silence came off the start.
const VOICE_CACHE = path.join(os.tmpdir(), 'render-video-cache', 'voice');
//
// A filmed clip's sound ({ sync: true }) keeps its silences, so it stays in step with the
// picture; `offset` and `maxLength` pick the stretch that plays.
function prepareVoice(file, { sync = false, offset = 0, maxLength } = {}) {
  const st = fs.statSync(file);
  const key = crypto.createHash('sha1').update(`${file}|${st.size}|${st.mtimeMs}|${VOICE_LUFS}|2|${sync}|${offset}|${maxLength}`).digest('hex').slice(0, 16);
  const prepared = path.join(VOICE_CACHE, `${key}.wav`);
  const meta = `${prepared}.json`;
  if (!fs.existsSync(meta)) {
    fs.mkdirSync(VOICE_CACHE, { recursive: true });
    const raw = path.join(VOICE_CACHE, `${key}-raw.wav`);
    const lead = path.join(VOICE_CACHE, `${key}-lead.wav`);
    const window = [...(offset ? ['-ss', String(offset)] : []), ...(maxLength ? ['-t', String(maxLength)] : [])];
    // the leading trim on its own first, to know how much it took off
    ffmpeg([...window, '-i', file, '-vn', '-af', 'aresample=48000,aformat=channel_layouts=stereo,highpass=f=80' +
      (sync ? '' : ',silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08'), '-c:a', 'pcm_s16le', lead]);
    const trimmed = sync ? 0 : Math.max(0, probeDuration(file) - offset - probeDuration(lead));
    // trailing silence: reversed, trimmed like the start, reversed back
    ffmpeg(['-i', lead, '-af', (sync ? '' : 'areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.15,areverse,') +
      'acompressor=threshold=0.1:ratio=2.5:attack=15:release=200', '-c:a', 'pcm_s16le', raw]);
    const { lufs } = measureAudio(raw);
    ffmpeg(['-i', raw, '-af', `volume=${Number.isFinite(lufs) ? (VOICE_LUFS - lufs).toFixed(2) : 0}dB`, '-c:a', 'pcm_s16le', prepared]);
    fs.rmSync(raw, { force: true });
    fs.rmSync(lead, { force: true });
    fs.writeFileSync(meta, JSON.stringify({ length: probeDuration(prepared), trimmed }));
  }
  return { prepared, ...JSON.parse(fs.readFileSync(meta, 'utf8')) };
}

// Prepares every voice clip before any frame is captured, so the page can use real line
// lengths: checks each line fits its scene, and puts word-by-word captions in every
// <div class="say auto" data-voice>. Returns { problems, cues } (cues for an .srt file).
async function prepareVoices(page, settings) {
  const problems = [];
  const cues = [];
  // the caption styles go in whenever a page has auto captions, voiced or not (narrated.html
  // previews them at a reading pace before any voice exists)
  await page.evaluate((css) => {
    if (!document.querySelector('.say.auto')) return;
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);
  }, captions.CAPTION_CSS);
  const clips = settings.voiceClips || [];
  if (!clips.length) return { problems, cues };
  if (!hasFfmpeg()) {
    problems.push('ffmpeg is needed to measure voice clips and time captions; skipped');
    return { problems, cues };
  }
  const sorted = [...clips].sort((a, b) => a.time - b.time);
  for (const clip of [...clips]) {
    const name = path.basename(clip.file);
    if (clip.sync && !hasAudioStream(clip.file)) {
      problems.push(`${name} has data-audio but no sound track; it plays silent`);
      clips.splice(clips.indexOf(clip), 1);
      continue;
    }
    Object.assign(clip, prepareVoice(clip.file, clip));
    const end = clip.time + clip.length;
    if (Number.isFinite(clip.sceneOut) && end > clip.sceneOut + 0.1) {
      problems.push(`voice ${name} runs to ${end.toFixed(2)}s, past its scene's end at ${clip.sceneOut.toFixed(2)}s; give the scene ${(end - clip.sceneOut + 0.3).toFixed(1)}s more, or shorten the line`);
    }
    if (!clip.caption) continue;
    const timing = await captions.alignWords(clip.prepared, clip.caption, { shift: clip.trimmed, sidecarFor: clip.file, whisper: !!settings.whisper });
    for (const n of timing.notes) problems.push(`captions for ${name}: ${n}`);
    clip.captionMethod = timing.method;
    const chunks = captions.chunkWords(timing.words);
    const next = sorted.find((c) => c.time > clip.time);
    let hold = Number.isFinite(clip.sceneOut) ? clip.sceneOut : end + 0.5;
    if (next) hold = Math.min(hold, next.time);
    const html = captions.captionMarkup(chunks, clip.time, hold);
    await page.evaluate(([index, markup]) => {
      document.querySelector(`[data-voice-index="${index}"]`).innerHTML = markup;
    }, [clip.index, html]);
    chunks.forEach((c, i) => cues.push({
      start: clip.time + c.start,
      end: chunks[i + 1] ? clip.time + chunks[i + 1].start : Math.max(clip.time + c.end + 0.4, hold),
      text: c.words.map((w) => w.text).join(' '),
    }));
  }
  return { problems, cues: cues.sort((a, b) => a.start - b.start) };
}

// The voice clips' timing, for fitting scenes to them: when each line starts, how long it
// runs once its leading silence is trimmed, and how much room its scene leaves.
function describeVoices(clips) {
  const rows = [...clips].sort((a, b) => a.time - b.time).map((c) => {
    const end = c.time + c.length;
    const room = Number.isFinite(c.sceneOut) ? `scene ends ${c.sceneOut.toFixed(2)}s (${c.sceneOut - end >= 0 ? '+' : ''}${(c.sceneOut - end).toFixed(2)}s)` : 'no scene end';
    return `${path.basename(c.file).padEnd(16)} starts ${c.time.toFixed(2)}s  length ${c.length.toFixed(2)}s  ends ${end.toFixed(2)}s  ${room}${c.captionMethod ? `  captions: ${c.captionMethod}` : ''}`;
  });
  return rows.join('\n');
}

// Mixes spoken lines over the music and effects in `bedWav`, and writes the result to `out`
// as a WAV. Returns problems to warn about.
function mixVoice(clips, duration, bedWav, tmp, out) {
  const problems = [];
  const parts = [];
  let prevEnd = -Infinity;
  [...clips].sort((a, b) => a.time - b.time).forEach((clip) => {
    if (!clip.prepared) Object.assign(clip, prepareVoice(clip.file, clip));
    const name = path.basename(clip.file);
    if (clip.time < prevEnd - 0.05) problems.push(`voice ${name} starts at ${clip.time.toFixed(2)}s, before the previous line ends at ${prevEnd.toFixed(2)}s, so they overlap`);
    if (clip.time + clip.length > duration + 0.05) problems.push(`voice ${name} runs ${(clip.time + clip.length - duration).toFixed(1)}s past the end of the video and will be cut off`);
    prevEnd = clip.time + clip.length;
    parts.push({ file: clip.prepared, time: clip.time });
  });
  const voiceWav = path.join(tmp, 'voice.wav');
  ffmpeg([...parts.flatMap((p) => ['-i', p.file]), '-filter_complex',
    `${parts.map((p, i) => `[${i}:a]adelay=${Math.round(p.time * 1000)}:all=1[v${i}]`).join(';')};` +
    `${parts.map((p, i) => `[v${i}]`).join('')}amix=inputs=${parts.length}:normalize=0,apad,atrim=0:${duration}`,
    '-ar', '48000', '-c:a', 'pcm_s16le', voiceWav]);
  const bed = measureAudio(bedWav).lufs;
  const bedGain = Number.isFinite(bed) ? (VOICE_LUFS - BED_UNDER_VOICE - bed).toFixed(2) : '0';
  ffmpeg(['-i', bedWav, '-i', voiceWav, '-filter_complex',
    `[0:a]volume=${bedGain}dB[bed];[1:a]asplit=2[v][key];` +
    '[bed][key]sidechaincompress=threshold=0.008:ratio=3:attack=40:release=450[ducked];' +
    '[ducked][v]amix=inputs=2:normalize=0', '-t', String(duration), '-ar', '48000', '-c:a', 'pcm_s16le', out]);
  return problems;
}

function muxSoundtrack(videoOnly, wav, out) {
  // with no video, writes an audio-only file (an .m4a preview)
  const inputs = videoOnly ? ['-i', videoOnly, '-i', wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy'] : ['-i', wav, '-vn'];
  const { lufs } = measureAudio(wav, PRE);
  // capped, so a page with only a few sparse sound effects isn't boosted into a wall of clicks
  const gain = Number.isFinite(lufs) ? Math.min(20, TARGET_LUFS - lufs).toFixed(2) : '0';
  let result;
  for (const ceiling of CEILINGS) {
    const filter = `${PRE},volume=${gain}dB,aresample=192000,alimiter=limit=${ceiling}:attack=5:release=50:level=false,aresample=48000`;
    ffmpeg([...inputs, '-af', filter, '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart', out]);
    result = measureAudio(out);
    if (result.truePeak <= MAX_TRUE_PEAK) break;
  }
  if (!(result.truePeak <= MAX_TRUE_PEAK)) {
    console.warn(`Warning: the audio's true peak is ${result.truePeak} dBTP, above ${MAX_TRUE_PEAK}; a platform re-encode may clip it slightly.`);
  }
  return result;
}

function muxSilence(videoOnly, out) {
  // some uploaders reject a file with no audio stream at all, so --silent still gets one
  ffmpeg(['-i', videoOnly, '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-map', '0:v', '-map', '1:a',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-shortest', '-movflags', '+faststart', out]);
}

// Builds the page's soundtrack (generated music or a licensed track, plus the sound
// effects) and muxes it into `out`, or writes it alone when there's no video.
function writeSoundtrack(settings, duration, tmp, videoOnly, out) {
  const licensed = !!settings.musicFile;
  const voices = settings.voiceClips || [];
  const { L, R, silent } = buildSoundtrack(settings.cues, { ...settings, music: licensed ? 'none' : settings.music, duration });
  if (silent && !licensed && !voices.length) {
    if (videoOnly) muxSilence(videoOnly, out);
    else ffmpeg(['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', String(duration), '-c:a', 'aac', out]);
    return { audio: 'silent track' };
  }
  let wav = path.join(tmp, 'soundtrack.wav');
  fs.writeFileSync(wav, wavBuffer(L, R));
  if (licensed) {
    const mixed = path.join(tmp, 'mixed.wav');
    for (const p of mixLicensedTrack(settings.musicFile, settings.musicStart, duration, wav, mixed, settings.musicAt)) console.warn(`Warning: ${p}`);
    wav = mixed;
  }
  if (voices.length) {
    const voiced = path.join(tmp, 'voiced.wav');
    for (const p of mixVoice(voices, duration, wav, tmp, voiced)) console.warn(`Warning: ${p}`);
    wav = voiced;
  }
  const level = muxSoundtrack(videoOnly, wav, out);
  const counts = {};
  for (const c of settings.cues.filter((c) => c.time < duration)) counts[c.sound] = (counts[c.sound] || 0) + 1;
  const summary = Object.entries(counts).map(([k, v]) => `${v} ${k}`).join(', ');
  const music = licensed ? `licensed track ${path.basename(settings.musicFile)} + `
    : settings.music === 'none' ? '' : `${settings.music} music + `;
  const voice = voices.length ? `, voiceover (${voices.length} clip${voices.length === 1 ? '' : 's'})` : '';
  return { audio: `soundtrack (${music}${summary || 'no sound effects'}${voice}; ${level.lufs} LUFS, ${level.truePeak} dBTP)` };
}

// --sample: a short preview of a genre and hook, with no page involved.
function sample(args) {
  const out = args.positional[0];
  if (!out) fail('Usage: node render.js --sample <genre> <out.m4a> [--motif "..."] [--key C] [--mode major] [--bpm 118] [--energy 3]');
  requireFfmpeg();
  const settings = {
    cues: [], music: args.sample, motif: args.motif, key: args.key, mode: args.mode,
    bpm: args.bpm ? Number(args.bpm) : undefined, energy: args.energy ? Number(args.energy) : undefined,
    drop: 2, breaks: '',
  };
  for (const p of checkMusic(settings)) console.warn(`Warning: ${p}`);
  const duration = Number(args.duration || 12);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'render-'));
  const { audio } = writeSoundtrack(settings, duration, tmp, null, out);
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`Wrote ${out}: ${duration}s ${audio}`);
}

// Renders frames [from, to) at `fps` into one H.264 file. The frames are split across `workers`
// browsers, each rendering a contiguous run into its own segment, and the segments are joined
// without re-encoding. `open(browser)` returns a page ready to seek, set up the same way in
// every worker; `onFrame(page, t)` runs before each capture (the layout lint uses it). `scale`
// below 1 captures smaller frames, for drafts.
async function renderFrames({ chromium, open, from = 0, to, fps, workers = 1, file, crf = 18, preset = 'slow', tune,
  scale = 1, width = WIDTH, height = HEIGHT, onFrame }) {
  const total = to - from;
  const count = Math.max(1, Math.min(workers, Math.ceil(total / fps)));
  const per = Math.ceil(total / count);
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'render-frames-'));
  let done = 0;
  const started = Date.now();
  const progress = () => {
    done++;
    if (done % fps === 0 || done === total) {
      const rate = done / Math.max(0.001, (Date.now() - started) / 1000);
      process.stderr.write(`\rframe ${done}/${total} (${rate.toFixed(1)} fps, ~${Math.round((total - done) / rate)}s left)   `);
    }
  };
  const clip = scale === 1 ? undefined : { x: 0, y: 0, width, height, scale };
  const segment = async (first, last, out) => {
    const browser = await launchBrowser(chromium);
    try {
      const page = await open(browser);
      const cdp = await page.context().newCDPSession(page);
      const encoder = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(fps), '-i', '-',
        '-c:v', 'libx264', '-preset', preset, '-crf', String(crf), ...(tune ? ['-tune', tune] : []), '-pix_fmt', 'yuv420p',
        '-profile:v', 'high', '-r', String(fps), out], { stdio: ['pipe', 'inherit', 'inherit'] });
      const encoded = new Promise((resolve) => encoder.on('close', resolve));
      for (let i = first; i < last; i++) {
        await seek(page, i / fps);
        if (onFrame) await onFrame(page, i / fps);
        const { data } = await cdp.send('Page.captureScreenshot', { format: 'png', optimizeForSpeed: true, ...(clip ? { clip } : {}) });
        if (!encoder.stdin.write(Buffer.from(data, 'base64'))) await new Promise((r) => encoder.stdin.once('drain', r));
        progress();
      }
      encoder.stdin.end();
      if ((await encoded) !== 0) throw new Error(`ffmpeg failed while encoding ${out}`);
    } finally {
      await browser.close();
    }
  };
  const segments = [];
  const jobs = [];
  for (let w = 0; w < count; w++) {
    const first = from + w * per;
    const last = Math.min(to, first + per);
    if (first >= last) break;
    const out = path.join(tmp, `seg${w}.mp4`);
    segments.push(out);
    jobs.push(segment(first, last, out));
  }
  await Promise.all(jobs);
  process.stderr.write('\n');
  const list = path.join(tmp, 'segments.txt');
  fs.writeFileSync(list, segments.map((f) => `file '${f}'`).join('\n'));
  ffmpeg(['-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', file]);
  fs.rmSync(tmp, { recursive: true, force: true });
  return { seconds: (Date.now() - started) / 1000, workers: segments.length };
}

// Workers by default: one per core but one, up to four (each is a whole browser).
const defaultWorkers = () => Math.max(1, Math.min(4, os.cpus().length - 1));

// Hook variants: elements with data-variant="a" (or "a b") appear only in those variants.
// Removes every other variant's elements, before media, sound cues, and voices are read.
async function variantsOf(page) {
  return page.evaluate(() => [...new Set([...document.querySelectorAll('[data-variant]')]
    .flatMap((el) => el.dataset.variant.split(/[\s,]+/).filter(Boolean)))].sort());
}
async function applyVariant(page, variant) {
  await page.evaluate((v) => {
    for (const el of document.querySelectorAll('[data-variant]')) {
      if (!el.dataset.variant.split(/[\s,]+/).includes(v)) el.remove();
    }
  }, variant);
}

// The profile grids on Instagram and TikTok show a 3:4 crop from the middle of a 9:16 cover
// (1080x1440, from y=240 to y=1680), so the cover's text has to sit inside it.
const GRID_CROP = { top: 240, bottom: 1680 };
async function coverProblems(page, t) {
  const boxes = await page.evaluate(() => {
    const out = [];
    for (const el of document.body.querySelectorAll('*')) {
      if (el.closest('.bg, .bg-media, [data-lint="off"], script, style')) continue;
      if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      let o = 1;
      for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.display === 'none' || cs.visibility === 'hidden') { o = 0; break; }
        o *= parseFloat(cs.opacity);
      }
      if (o < 0.5) continue;
      const r = el.getBoundingClientRect();
      out.push({ top: r.top, bottom: r.bottom, text: el.textContent.trim().replace(/\s+/g, ' ').slice(0, 48) });
    }
    return out;
  });
  if (!boxes.length) return [{ t, kind: 'the cover has no text', text: '', detail: 'pick a moment that shows the hook, or give the hook class "now" and use --cover 0' }];
  return boxes.filter((b) => b.top < GRID_CROP.top || b.bottom > GRID_CROP.bottom)
    .map((b) => ({ t, kind: 'is cut off in the profile grid', text: b.text, detail: `the grid shows y ${GRID_CROP.top}-${GRID_CROP.bottom} of the cover` }));
}

// Writes the cover at `t` seconds to `file`, and returns its problems.
async function writeCover(page, t, file) {
  await seek(page, t);
  await page.screenshot({ path: file });
  return [...await lintLayout(page, t), ...await coverProblems(page, t)];
}

// out.mp4 -> out-b.mp4, for one of several variants
const withVariant = (file, variant, many) => (many && variant ? file.replace(/(\.[^./]+)?$/, (ext) => `-${variant}${ext || ''}`) : file);

// Opens a page and sets it up for seeking: the variant, background clips, sound settings, and
// voice lines with their captions. Every render worker sets its page up the same way.
async function preparePage(browser, pagePath, args, variant) {
  const { page, problems: fontProblems } = await openPage(browser, pagePath);
  if (variant) await applyVariant(page, variant);
  const mediaProblems = await prepareMedia(page);
  const settings = await readPage(page);
  settings.whisper = args.whisper;
  settings.problems.push(...fontProblems, ...mediaProblems, ...checkMusic(settings));
  const voiced = await prepareVoices(page, settings);
  settings.problems.push(...voiced.problems);
  return { page, settings, voiced };
}

// Opens the page (in one variant, if it has them) and does what was asked. Returns an exit code.
async function runPage(browser, pagePath, outPath, args, variant, many) {
  const label = variant ? ` [variant ${variant}]` : '';
  const { page, settings, voiced } = await preparePage(browser, pagePath, args, variant);
  for (const p of settings.problems) console.warn(`Warning${label}: ${p}`);
  const pageDir = path.dirname(path.resolve(pagePath));
  const pageBase = path.basename(pagePath).replace(/\.html?$/, '');
  try {
    if (args.voiceLengths) {
      console.log(settings.voiceClips.length ? describeVoices(settings.voiceClips) : 'No data-voice clips on this page.');
      return 0;
    }
    if (args.stills) {
      const outdir = withVariant(args.outdir || path.join(pageDir, 'stills'), variant, many);
      fs.mkdirSync(outdir, { recursive: true });
      const lint = [];
      for (const t of args.stills.split(',').map(Number)) {
        await seek(page, t);
        lint.push(...await lintLayout(page, t));
        const file = path.join(outdir, `still_${t.toFixed(2)}s.png`);
        await page.screenshot({ path: file });
        console.log(file);
      }
      for (const p of lint) console.warn(`Layout${label}: ${describeLint(p)}`);
      return 0;
    }
    if (args.cover !== undefined && !outPath) {
      const file = withVariant(path.join(args.outdir || pageDir, `${pageBase}-cover.png`), variant, many);
      if (args.outdir) fs.mkdirSync(args.outdir, { recursive: true });
      const problems = await writeCover(page, Number(args.cover), file);
      for (const p of problems) console.warn(`Cover${label}: ${describeLint(p)}`);
      console.log(`${file} (post with --cover-ms ${Math.round(Number(args.cover) * 1000)})`);
      return problems.length ? 1 : 0;
    }

    const duration = Number(args.duration || settings.duration);
    if (!(duration > 0)) fail('Set the length with <body data-duration="24"> on the page, or pass --duration.');
    for (const p of checkMix(settings, duration)) console.warn(`Warning${label}: ${p}`);
    if (args.check) {
      const lint = await lintTimeline(page, duration);
      for (const p of lint) console.warn(`${lintLabel(p)}${label}: ${describeLint(p)}`);
      const failing = lint.filter((p) => !p.advice);
      console.log(failing.length ? `${failing.length} layout problem(s) in ${pagePath}${label}` : `No layout problems in ${pagePath}${label}`);
      return failing.length || settings.problems.length ? 1 : 0;
    }
    if (args.slides) {
      const outdir = withVariant(args.outdir || path.join(pageDir, 'slides'), variant, many);
      fs.mkdirSync(outdir, { recursive: true });
      const lint = [];
      const times = await slideTimes(page, duration);
      for (let i = 0; i < times.length; i++) {
        await seek(page, times[i]);
        lint.push(...await lintLayout(page, times[i]));
        const file = path.join(outdir, `slide_${String(i + 1).padStart(2, '0')}.png`);
        await page.screenshot({ path: file });
        console.log(file);
      }
      for (const p of lint) console.warn(`Layout${label}: ${describeLint(p)}`);
      return 0;
    }
    const out = withVariant(outPath, variant, many);
    if (args.audioOnly) {
      const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'render-'));
      const { audio } = writeSoundtrack(settings, duration, tmp, null, out);
      fs.rmSync(tmp, { recursive: true, force: true });
      console.log(`Wrote ${out}: ${duration}s ${audio}`);
      return 0;
    }
    // a draft is half size at 15fps, quick to make and enough to check timing and sync
    const fps = Number(args.fps || (args.draft ? 15 : 30));
    const frames = Math.round(duration * fps);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'render-'));
    const videoOnly = path.join(tmp, 'video.mp4');
    const lintSeen = new Map();
    let lintEvery = 0;
    const timing = await renderFrames({
      chromium: args.chromium,
      open: async (b) => (await preparePage(b, pagePath, args, variant)).page,
      to: frames, fps, file: videoOnly,
      workers: Number(args.workers || defaultWorkers()),
      ...(args.draft ? { scale: 0.5, preset: 'ultrafast', crf: 26 } : {}),
      onFrame: async (p, t) => {
        if (lintEvery++ % 8) return;
        for (const x of await lintLayout(p, t)) if (!lintSeen.has(`${x.kind}|${x.text}`)) lintSeen.set(`${x.kind}|${x.text}`, x);
      },
    });
    let coverFile = '';
    let coverIssues = [];
    if (args.cover !== undefined) {
      coverFile = out.replace(/\.[^./]+$/, '') + '-cover.png';
      coverIssues = await writeCover(page, Number(args.cover), coverFile);
    }

    let audio = 'silent track';
    if (args.silent) muxSilence(videoOnly, out);
    else ({ audio } = writeSoundtrack(settings, duration, tmp, videoOnly, out));
    fs.rmSync(tmp, { recursive: true, force: true });
    for (const p of lintSeen.values()) console.warn(`Layout${label}: ${describeLint(p)}`);
    const size = args.draft ? `${WIDTH / 2}x${HEIGHT / 2} draft` : `${WIDTH}x${HEIGHT}`;
    console.log(`Wrote ${out}: ${size}, ${duration}s at ${fps}fps, ${audio} (rendered in ${Math.round(timing.seconds)}s on ${timing.workers} worker${timing.workers === 1 ? '' : 's'})`);
    if (voiced.cues.length) {
      // the captions as a track for the platforms' own caption upload (YouTube takes .srt)
      const srt = out.replace(/\.[^./]+$/, '') + '.srt';
      fs.writeFileSync(srt, captions.toSrt(voiced.cues.filter((c) => c.start < duration)));
      console.log(`Wrote ${srt}: ${voiced.cues.length} caption cues`);
    }
    if (coverFile) {
      for (const p of coverIssues) console.warn(`Cover${label}: ${describeLint(p)}`);
      console.log(`Wrote ${coverFile} (post with --cover-ms ${Math.round(Number(args.cover) * 1000)})`);
    }
    return 0;
  } finally {
    await page.close();
  }
}

// --batch: renders every page given, each to <page>.mp4 (in --outdir, or next to the page), every
// hook variant of a page with variants, one after another. For a week of queued videos.
async function batch(args) {
  const pages = args.positional;
  if (!pages.length) fail('Usage: node render.js --batch <page.html> [<page.html> ...] [--outdir dir] [--cover 0] [--draft]');
  for (const p of pages) if (!fs.existsSync(p)) fail(`No page found at ${p}`);
  requireFfmpeg();
  const { chromium } = loadPlaywright();
  args.chromium = chromium;
  const browser = await launchBrowser(chromium);
  const results = [];
  for (const pagePath of pages) {
    const out = path.join(args.outdir || path.dirname(path.resolve(pagePath)), `${path.basename(pagePath).replace(/\.html?$/, '')}.mp4`);
    if (args.outdir) fs.mkdirSync(args.outdir, { recursive: true });
    const probe = await openPage(browser, pagePath);
    const found = await variantsOf(probe.page);
    await probe.page.close();
    for (const v of found.length ? found : [null]) {
      console.log(`\n== ${pagePath}${v ? ` [variant ${v}]` : ''}`);
      let code;
      try {
        code = await runPage(browser, pagePath, out, args, v, found.length > 1);
      } catch (e) {
        console.error(e.message || e);
        code = 1;
      }
      results.push({ page: pagePath, variant: v, out: withVariant(out, v, found.length > 1), ok: code === 0 });
    }
  }
  await browser.close();
  console.log(`\nRendered ${results.filter((r) => r.ok).length} of ${results.length}:`);
  for (const r of results) console.log(`  ${r.ok ? 'ok    ' : 'FAILED'} ${r.out}`);
  process.exit(results.every((r) => r.ok) ? 0 : 1);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.sample) return sample(args);
  if (args.batch) return batch(args);
  const [pagePath, outPath] = args.positional;
  if (args.help || !pagePath || (!outPath && !args.stills && !args.check && !args.slides && !args.voiceLengths && args.cover === undefined)) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }
  if (!fs.existsSync(pagePath)) fail(`No page found at ${pagePath}`);
  if (args.cover !== undefined && !(Number(args.cover) >= 0)) fail('--cover takes the time of the cover frame in seconds, e.g. --cover 0');
  if (outPath && !args.stills && !args.check && !args.slides && !args.voiceLengths) requireFfmpeg();

  const { chromium } = loadPlaywright();
  args.chromium = chromium;
  const browser = await launchBrowser(chromium);
  const probe = await openPage(browser, pagePath);
  const found = await variantsOf(probe.page);
  await probe.page.close();
  const asked = String(args.variants || args.variant || '').split(',').map((v) => v.trim()).filter(Boolean);
  for (const v of asked) {
    if (!found.includes(v)) fail(found.length ? `No variant "${v}" on this page (it has ${found.join(', ')}).` : `This page has no data-variant elements, so there's no variant "${v}".`);
  }
  let variants = asked.length ? asked : found;
  const rendering = outPath && !args.stills && !args.check && !args.slides && !args.voiceLengths;
  if (rendering && found.length && !asked.length) {
    fail(`This page has hook variants (${found.join(', ')}). Render one with --variant ${found[0]}, or all with --variants ${found.join(',')}.`);
  }
  if (!variants.length) variants = [null];
  let code = 0;
  for (const v of variants) code = Math.max(code, await runPage(browser, pagePath, outPath, args, v, variants.length > 1));
  await browser.close();
  process.exit(code);
}

if (require.main === module) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}

module.exports = {
  WIDTH, HEIGHT, loadPlaywright, launchBrowser, openPage, prepareMedia, readPage, checkMusic, checkMix, mixVoice, seek,
  lintLayout, lintTimeline, describeLint, lintLabel, slideTimes, textSnapshot, retentionProblems, writeSoundtrack, measureAudio, muxSoundtrack,
  prepareVoice, prepareVoices, describeVoices, probeDuration, variantsOf, applyVariant, coverProblems,
  renderFrames, preparePage, defaultWorkers,
};
