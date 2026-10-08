#!/usr/bin/env node
'use strict';
/*
 * Finds and downloads background media for rendered videos: vertical photos
 * and video clips from Pexels, Pixabay, or Openverse. Files are saved into a
 * page's assets folder, with credits the skill turns into caption credit
 * lines.
 *
 * Usage:
 *   node media.js search "<query>" --out <assets dir> [--type photo|video|music] [--count 3]
 *                 [--provider pexels|pixabay|openverse]
 *   node media.js credit <file> --ai "<tool / model>" [--prompt "<prompt used>"]
 *   node media.js credit <file> --source "<library or site>" --license "<license>"
 *                 [--link "<page>"] [--creator "<name>"] [--line "<credit line, if one is required>"]
 *
 * Keys are free: PEXELS_API_KEY (pexels.com/api) and PIXABAY_API_KEY
 * (pixabay.com/api/docs). Openverse needs none, but only has photos and
 * allows about 100 requests a day without a key. With no --provider, search
 * tries the providers whose keys are set, then Openverse.
 *
 * Licensing, per each provider's API terms:
 * - Pexels requires crediting the photographer ("Photo by X on Pexels").
 * - Pixabay needs no credit, but files must be downloaded rather than
 *   hotlinked, searches are cached for 24 hours, and there are no bulk
 *   downloads (--count is capped at 10).
 * - Openverse results are limited to licenses that allow commercial use and
 *   modification (no NC or ND); CC BY and BY-SA need a credit.
 *
 * --type music searches Openverse's audio (music only, the same license limits) for a track to
 * use instead of the generated soundtrack, and reads each download's tempo with beats.js, so
 * the track can be started where its drop lands on the hook and the scenes cut on its beat.
 * Every file lands in credits.json and CREDITS.md next to it, with the exact
 * credit line to use, if one is needed.
 */
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

// Node's fetch ignores HTTP(S)_PROXY unless NODE_USE_ENV_PROXY is set at startup,
// so behind a proxy, re-run this script with it on.
if ((process.env.HTTPS_PROXY || process.env.https_proxy) && !process.env.NODE_USE_ENV_PROXY) {
  const run = spawnSync(process.execPath, process.argv.slice(1), {
    stdio: 'inherit',
    env: { ...process.env, NODE_USE_ENV_PROXY: '1', NODE_NO_WARNINGS: '1' },
  });
  process.exit(run.status ?? 1);
}

const BASES = {
  pexels: process.env.MEDIA_PEXELS_BASE || 'https://api.pexels.com',
  pixabay: process.env.MEDIA_PIXABAY_BASE || 'https://pixabay.com/api',
  openverse: process.env.MEDIA_OPENVERSE_BASE || 'https://api.openverse.org/v1',
};
const MIN_W = 1080;
const MIN_H = 1920;
const MAX_COUNT = 10;
const CACHE_HOURS = 24;
const MAX_VIDEO_BYTES = 150 * 1024 * 1024;

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

function parseArgs(argv) {
  const args = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (['--out', '--type', '--count', '--provider', '--ai', '--prompt', '--source', '--license', '--link', '--creator', '--line'].includes(a)) args[a.slice(2)] = argv[++i];
    else if (a === '-h' || a === '--help') args.help = true;
    else args.positional.push(a);
  }
  return args;
}

const slugify = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'media';

class ProviderError extends Error {}

async function getJson(url, headers, cacheDir) {
  // cached for 24h: Pixabay's API terms require it, and it spares everyone's rate limits
  const key = crypto.createHash('sha1').update(url.replace(/key=[^&]+/, 'key=')).digest('hex').slice(0, 16);
  const cacheFile = path.join(cacheDir, `${key}.json`);
  if (fs.existsSync(cacheFile) && Date.now() - fs.statSync(cacheFile).mtimeMs < CACHE_HOURS * 3600e3) {
    return JSON.parse(fs.readFileSync(cacheFile, 'utf8'));
  }
  let res;
  try {
    res = await fetch(url, { headers });
  } catch (e) {
    throw new ProviderError(`couldn't reach ${new URL(url).host} (${e.cause?.code || e.message})`);
  }
  if (res.status === 401 || res.status === 403) throw new ProviderError(`rejected the API key (HTTP ${res.status})`);
  if (res.status === 429) throw new ProviderError('rate limit reached (HTTP 429); try again later or use another provider');
  if (!res.ok) throw new ProviderError(`HTTP ${res.status}`);
  const data = await res.json();
  fs.mkdirSync(cacheDir, { recursive: true });
  fs.writeFileSync(cacheFile, JSON.stringify(data));
  return data;
}

// Each provider returns candidates: { id, url (file to download), width, height, creator, source, license, required, line }
const PROVIDERS = {
  pexels: {
    key: 'PEXELS_API_KEY',
    async search(q, type, n, cacheDir) {
      const headers = { Authorization: process.env.PEXELS_API_KEY };
      const per = Math.min(80, n * 3);
      if (type === 'photo') {
        const d = await getJson(`${BASES.pexels}/v1/search?query=${encodeURIComponent(q)}&orientation=portrait&size=large&per_page=${per}`, headers, cacheDir);
        return (d.photos || []).filter((p) => p.width >= MIN_W && p.height >= MIN_H).map((p) => ({
          id: `pexels-${p.id}`,
          // Pexels serves resized crops through query parameters on the original URL
          url: `${p.src.original}?auto=compress&cs=tinysrgb&fit=crop&w=${MIN_W}&h=${MIN_H}`,
          width: MIN_W, height: MIN_H,
          creator: p.photographer, source: p.url, license: 'Pexels License',
          required: true, line: `Photo by ${p.photographer} on Pexels`,
        }));
      }
      const d = await getJson(`${BASES.pexels}/videos/search?query=${encodeURIComponent(q)}&orientation=portrait&size=medium&per_page=${per}`, headers, cacheDir);
      return (d.videos || []).map((v) => {
        const files = (v.video_files || []).filter((f) => f.file_type === 'video/mp4' && f.height > f.width);
        const big = files.filter((f) => f.width >= MIN_W && f.height >= MIN_H).sort((a, b) => a.width * a.height - b.width * b.height);
        const pick = big[0] || files.sort((a, b) => b.width * b.height - a.width * a.height)[0];
        return pick && {
          id: `pexels-video-${v.id}`, url: pick.link, width: pick.width, height: pick.height, duration: v.duration,
          creator: v.user?.name, source: v.url, license: 'Pexels License',
          required: true, line: `Video by ${v.user?.name} on Pexels`,
        };
      }).filter(Boolean);
    },
  },

  pixabay: {
    key: 'PIXABAY_API_KEY',
    async search(q, type, n, cacheDir) {
      const key = encodeURIComponent(process.env.PIXABAY_API_KEY);
      const per = Math.max(3, Math.min(200, n * 3));
      if (type === 'photo') {
        const d = await getJson(`${BASES.pixabay}/?key=${key}&q=${encodeURIComponent(q)}&image_type=photo&orientation=vertical&min_width=${MIN_W}&min_height=${MIN_H}&safesearch=true&per_page=${per}`, {}, cacheDir);
        return (d.hits || []).map((h) => {
          // largeImageURL is capped at 1280px unless the key has full API access, which adds fullHDURL
          const url = h.fullHDURL || h.largeImageURL;
          const scale = h.fullHDURL ? 1920 / Math.max(h.imageWidth, h.imageHeight) : 1280 / Math.max(h.imageWidth, h.imageHeight);
          return {
            id: `pixabay-${h.id}`, url, width: Math.round(h.imageWidth * Math.min(1, scale)), height: Math.round(h.imageHeight * Math.min(1, scale)),
            creator: h.user, source: h.pageURL, license: 'Pixabay Content License',
            required: false, line: `Image by ${h.user} from Pixabay`,
          };
        });
      }
      const d = await getJson(`${BASES.pixabay}/videos/?key=${key}&q=${encodeURIComponent(q)}&safesearch=true&per_page=${per}`, {}, cacheDir);
      return (d.hits || []).map((h) => {
        const sizes = Object.values(h.videos || {}).filter((v) => v && v.url);
        // vertical clips first; otherwise the renderer crops the center of a landscape one
        const tall = sizes.filter((v) => v.height > v.width && v.width >= MIN_W);
        const pick = tall.sort((a, b) => a.width - b.width)[0] || sizes.filter((v) => v.height >= MIN_W).sort((a, b) => a.height - b.height)[0];
        return pick && {
          id: `pixabay-video-${h.id}`, url: pick.url, width: pick.width, height: pick.height, duration: h.duration,
          creator: h.user, source: h.pageURL, license: 'Pixabay Content License',
          required: false, line: `Video by ${h.user} from Pixabay`,
        };
      }).filter(Boolean).sort((a, b) => (b.height > b.width) - (a.height > a.width));
    },
  },

  openverse: {
    key: null,
    async search(q, type, n, cacheDir) {
      if (type === 'music') {
        const d = await getJson(`${BASES.openverse}/audio/?q=${encodeURIComponent(q)}&license_type=commercial,modification&category=music&mature=false&page_size=${Math.min(20, n * 4)}`, {}, cacheDir);
        // long enough to sit under a whole short (Openverse gives the length in milliseconds)
        return (d.results || []).filter((r) => r.url && (!r.duration || r.duration >= 20000)).map((r) => {
          const free = ['cc0', 'pdm'].includes(r.license);
          const license = r.license === 'pdm' ? 'Public Domain Mark'
            : `${r.license === 'cc0' ? 'CC0' : `CC ${String(r.license).toUpperCase()}`} ${r.license_version || ''}`.trim();
          return {
            id: `openverse-audio-${r.id}`, url: r.url, duration: r.duration ? r.duration / 1000 : undefined, title: r.title,
            creator: r.creator || 'unknown', source: r.foreign_landing_url, license,
            required: !free, line: free ? '' : `"${r.title || 'Track'}" by ${r.creator || 'unknown'}, ${license}`,
          };
        });
      }
      if (type !== 'photo') throw new ProviderError('has no video clips');
      const d = await getJson(`${BASES.openverse}/images/?q=${encodeURIComponent(q)}&license_type=commercial,modification&aspect_ratio=tall&size=large&mature=false&page_size=${Math.min(20, n * 3)}`, {}, cacheDir);
      return (d.results || []).filter((r) => !r.width || (r.width >= MIN_W * 0.75 && r.height >= MIN_H * 0.75)).map((r) => {
        const free = ['cc0', 'pdm'].includes(r.license);
        const license = r.license === 'pdm' ? 'Public Domain Mark'
          : `${r.license === 'cc0' ? 'CC0' : `CC ${r.license.toUpperCase()}`} ${r.license_version || ''}`.trim();
        return {
          id: `openverse-${r.id}`, url: r.url, width: r.width, height: r.height,
          creator: r.creator || 'unknown', source: r.foreign_landing_url, license,
          required: !free, line: free ? '' : `"${r.title || 'Photo'}" by ${r.creator || 'unknown'}, ${license}`,
        };
      });
    },
  },
};

const EXTENSIONS = {
  'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov',
  'audio/mpeg': 'mp3', 'audio/mp3': 'mp3', 'audio/ogg': 'ogg', 'audio/wav': 'wav', 'audio/x-wav': 'wav', 'audio/flac': 'flac',
  'audio/x-flac': 'flac', 'audio/mp4': 'm4a', 'audio/aac': 'aac',
};
const URL_EXTENSIONS = /\.(jpe?g|png|webp|mp4|webm|mov|mp3|ogg|wav|flac|m4a|aac)$/i;

// Returns the file's bytes and an extension taken from its content type (Openverse URLs don't reliably have one).
async function download(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const type = (res.headers.get('content-type') || '').split(';')[0].trim();
  // some hosts send a generic content type; the file name says what it is
  const fromUrl = (URL_EXTENSIONS.exec(new URL(url).pathname) || [])[1];
  if (!EXTENSIONS[type] && !fromUrl) throw new Error(`not a supported image, video, or audio file (${type || 'no content type'})`);
  const len = Number(res.headers.get('content-length') || 0);
  if (len > MAX_VIDEO_BYTES) throw new Error(`too large (${Math.round(len / 1e6)} MB)`);
  return { bytes: Buffer.from(await res.arrayBuffer()), ext: EXTENSIONS[type] || fromUrl.toLowerCase().replace('jpeg', 'jpg') };
}

function loadCredits(dir) {
  const f = path.join(dir, 'credits.json');
  return fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : [];
}

function saveCredits(dir, credits) {
  fs.writeFileSync(path.join(dir, 'credits.json'), JSON.stringify(credits, null, 2) + '\n');
  const needed = credits.filter((c) => c.required).map((c) => c.line);
  const md = [
    '# Media credits',
    '',
    'Written by `scripts/video/media.js`. Every file in this folder that came',
    'from a stock library or an AI tool is listed here.',
    '',
    needed.length
      ? `**Credit required.** Put this in the post caption or description:\n\n> ${[...new Set(needed)].join(' · ')}`
      : 'No credit is required for these files (crediting anyway is good practice).',
    '',
    '| File | Source | Creator | License | Link |',
    '|---|---|---|---|---|',
    ...credits.map((c) => `| ${c.file} | ${c.provider === 'ai' ? `AI: ${c.tool}` : c.provider} | ${c.creator || ''} | ${c.license || ''} | ${c.source || ''} |`),
    '',
  ];
  if (credits.some((c) => c.provider === 'ai')) {
    md.push('AI-generated files: if any looks photorealistic, switch on the platform\'s AI-content label when posting (TikTok, YouTube, and Instagram all ask for it).', '');
  }
  fs.writeFileSync(path.join(dir, 'CREDITS.md'), md.join('\n'));
}

// A track's tempo and how steady its beat is, from beats.js, so a fitting one can be picked
// and the video cut on it.
function rhythm(file) {
  const run = spawnSync(process.execPath, [path.join(__dirname, 'beats.js'), file, '--json'], { encoding: 'utf8', maxBuffer: 1 << 26 });
  try {
    const d = JSON.parse(run.stdout);
    return { bpm: d.bpm, beatConfidence: d.confidence, duration: d.duration };
  } catch {
    return {};
  }
}

function nextName(dir, slug, ext) {
  for (let i = 1; ; i++) {
    const name = `${slug}-${i}.${ext}`;
    if (!fs.existsSync(path.join(dir, name))) return name;
  }
}

async function search(args) {
  const query = args.positional[1];
  const out = args.out;
  const type = args.type || 'photo';
  const count = Math.min(MAX_COUNT, Math.max(1, Number(args.count || 3)));
  if (!query || !out) fail('Usage: node media.js search "<query>" --out <assets dir> [--type photo|video|music] [--count 3] [--provider ...]');
  if (!['photo', 'video', 'music'].includes(type)) fail('--type must be photo, video, or music.');
  if (args.provider && !PROVIDERS[args.provider]) fail(`Unknown --provider "${args.provider}" (use ${Object.keys(PROVIDERS).join(', ')}).`);

  let order;
  if (args.provider) {
    const p = PROVIDERS[args.provider];
    if (p.key && !process.env[p.key]) fail(`--provider ${args.provider} needs ${p.key}. Get a free key and set it as an environment variable.`);
    order = [args.provider];
  } else {
    order = Object.keys(PROVIDERS).filter((name) => !PROVIDERS[name].key || process.env[PROVIDERS[name].key]);
    if (type === 'video') order = order.filter((name) => name !== 'openverse');
    if (type === 'music') order = ['openverse'];
    if (!order.length) {
      fail('Video clips need a Pexels or Pixabay key: set PEXELS_API_KEY or PIXABAY_API_KEY (both free).');
    }
  }

  fs.mkdirSync(out, { recursive: true });
  const cacheDir = path.join(out, '.media-cache');
  const credits = loadCredits(out);
  const have = new Set(credits.map((c) => c.id));
  const problems = [];
  for (const name of order) {
    let candidates;
    try {
      candidates = await PROVIDERS[name].search(query, type, count, cacheDir);
    } catch (e) {
      if (!(e instanceof ProviderError)) throw e;
      problems.push(`${name}: ${e.message}`);
      continue;
    }
    const files = [];
    const fresh = candidates.filter((c) => !have.has(c.id));
    for (const c of fresh) {
      if (files.length >= count) break;
      let got;
      try {
        got = await download(c.url);
      } catch (e) {
        problems.push(`${name}: skipped ${c.source} (${e.message})`);
        continue;
      }
      const file = nextName(out, slugify(query), got.ext);
      fs.writeFileSync(path.join(out, file), got.bytes);
      const entry = { file, id: c.id, provider: name, type, width: c.width, height: c.height, duration: c.duration,
                      creator: c.creator, source: c.source, license: c.license, required: c.required, line: c.line, query };
      if (type === 'music') Object.assign(entry, { title: c.title }, rhythm(path.join(out, file)));
      // below full 1080x1920 it gets upscaled, so it will look soft once the Ken Burns zoom kicks in
      if (c.width && c.height && (Math.min(c.width, c.height) < MIN_W || Math.max(c.width, c.height) < MIN_H)) entry.soft = true;
      credits.push(entry);
      files.push(entry);
    }
    if (files.length) {
      saveCredits(out, credits);
      for (const p of problems) console.error(`Note: ${p}`);
      console.log(JSON.stringify({ provider: name, query, type, files }, null, 2));
      return;
    }
    const what = { photo: 'photos', video: 'clips', music: 'tracks' }[type];
    problems.push(candidates.length && !fresh.length
      ? `${name}: every result for "${query}" is already in ${out}; try a different query`
      : `${name}: no usable ${what} at least ${MIN_W}x${MIN_H} for "${query}"`);
  }
  fail(`No ${type}s downloaded.\n${problems.map((p) => `- ${p}`).join('\n')}\nTry a broader query (a setting or mood, not a specific product).`, 3);
}

// Records a file that didn't come through `search`: an AI-generated image, or a licensed music track.
function credit(args) {
  const file = args.positional[1];
  if (!file || !(args.ai || (args.source && args.license))) {
    fail('Usage: node media.js credit <file> --ai "<tool / model>" [--prompt "..."]\n' +
         '   or: node media.js credit <file> --source "<library or site>" --license "<license>" [--link ...] [--creator ...] [--line "<credit line>"]');
  }
  if (!fs.existsSync(file)) fail(`No file at ${file}`);
  const dir = path.dirname(path.resolve(file));
  const name = path.basename(file);
  const credits = loadCredits(dir).filter((c) => c.file !== name);
  if (args.ai) {
    credits.push({ file: name, id: `ai-${name}`, provider: 'ai', tool: args.ai, prompt: args.prompt,
                   license: 'AI-generated (check the tool\'s commercial-use terms)', required: false, line: '' });
  } else {
    credits.push({ file: name, id: `manual-${name}`, provider: args.source, creator: args.creator, source: args.link,
                   license: args.license, required: !!args.line, line: args.line || '' });
  }
  saveCredits(dir, credits);
  console.log(`Recorded ${name} (${args.ai ? `AI-generated with ${args.ai}` : `${args.source}, ${args.license}`}) in ${path.join(dir, 'CREDITS.md')}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const cmd = args.positional[0];
  if (args.help || !['search', 'credit'].includes(cmd)) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }
  if (cmd === 'credit') return credit(args);
  return search(args);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
