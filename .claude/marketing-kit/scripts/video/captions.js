#!/usr/bin/env node
'use strict';
/*
 * Word-by-word captions for a voiceover line whose text is known: when each word starts
 * and ends in the clip, grouped into the short chunks a viewer reads at a glance, plus an
 * .srt file for the platforms' own caption tracks. render.js uses this for every element
 * with class "say auto" and a data-voice clip; the element's text is the line.
 *
 * How the timing is found, with no service or download:
 * - The clip's loudness is read every 10 ms, and the quiet stretches between phrases split
 *   it into spoken runs. The line's words are shared out across those runs so each run's
 *   words take about as long to say as the run lasts (word length in letters tracks that),
 *   with a strong preference for a pause after punctuation, then spread across their run.
 * - A line made by voice.js has a <name>.json next to it with each sentence's exact start
 *   and end; those are used as fixed boundaries.
 * - Optional, --whisper: word timestamps from Whisper through @huggingface/transformers
 *   (installed with kokoro-js), matched against the line's own words. Its word timing has
 *   had bugs between versions, so the result is checked and the method above is used if
 *   it doesn't hold up. The first run downloads the model (about 80 MB) from huggingface.co.
 *
 * Usage:
 *   node captions.js <clip> --text "the line, as written" [--whisper] [--json]
 *   node captions.js <clip> --text "..." --srt out.srt
 *
 * Checked against synthesized speech with known word timings: word starts land about 50 ms
 * from the truth on average, and 95% within 150 ms. Pauses and punctuation, where chunks
 * change, are the most accurate part. Look at the rendered video to check it.
 */
const { spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SR = 16000;
const HOP = 160; // 10 ms
const FRAME = HOP / SR;
const MIN_PAUSE = 0.15; // a quieter stretch shorter than this is inside a phrase
const MIN_RUN = 0.04;

function decode(file) {
  const run = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-ac', '1', '-ar', String(SR), '-f', 'f32le', '-'], { maxBuffer: 1 << 30 });
  if (run.error || run.status !== 0) throw new Error(`ffmpeg couldn't read ${file}: ${run.error ? run.error.message : run.stderr.toString().trim()}`);
  const b = run.stdout;
  return new Float32Array(b.buffer.slice(b.byteOffset, b.byteOffset + Math.floor(b.length / 4) * 4));
}

// Loudness in dB per 10 ms frame.
function envelope(samples) {
  const n = Math.floor(samples.length / HOP);
  const db = new Float64Array(n);
  for (let f = 0; f < n; f++) {
    let sum = 0;
    for (let i = f * HOP; i < (f + 1) * HOP; i++) sum += samples[i] * samples[i];
    db[f] = Math.max(-100, 10 * Math.log10(sum / HOP + 1e-12));
  }
  return db;
}

function percentile(values, p) {
  const sorted = Float64Array.from(values).sort();
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}

// Spoken runs [{ start, end }] in seconds, split at pauses of at least MIN_PAUSE.
function spokenRuns(db, from = 0, to = db.length * FRAME) {
  const a = Math.max(0, Math.floor(from / FRAME));
  const b = Math.min(db.length, Math.ceil(to / FRAME));
  const part = db.subarray(a, b);
  if (!part.length) return [];
  const floor = percentile(part, 0.1);
  const peak = percentile(part, 0.95);
  const threshold = Math.max(floor + 6, peak - 32);
  const runs = [];
  let start = -1;
  for (let f = a; f <= b; f++) {
    const voiced = f < b && db[f] > threshold;
    if (voiced && start < 0) start = f;
    if (!voiced && start >= 0) {
      runs.push({ start: start * FRAME, end: f * FRAME });
      start = -1;
    }
  }
  const merged = [];
  for (const r of runs) {
    const last = merged[merged.length - 1];
    if (last && r.start - last.end < MIN_PAUSE) last.end = r.end;
    else merged.push({ ...r });
  }
  return merged.filter((r) => r.end - r.start >= MIN_RUN);
}

// How long a word takes to say, in rough units: letters track it better than syllables
// (checked against synthesized speech with known word timings), plus a little per word.
// Digits are spoken as longer words ("2026" is "twenty twenty-six").
function wordWeight(word) {
  const w = word.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]/g, '');
  const digits = (w.match(/\d/g) || []).length;
  return w.length - digits + digits * 3 + 0.7;
}

const tokenize = (text) => text.trim().split(/\s+/).filter(Boolean);
const endsPhrase = (word) => /[.,!?;:…—–)"”']$/.test(word);
const norm = (word) => word.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]/g, '');

// Shares `words` (with weights) out over `runs`, keeping order. Each run's share of words
// should take about as long to say as the run lasts, at the line's average pace, and a pause
// after punctuation is much likelier than one mid-phrase. A run can end up with no words
// (a breath or a click), at a cost unless it's very short.
function assign(words, runs) {
  const N = words.length;
  const K = runs.length;
  if (K === 1 || N === 0) return [words.map((_, i) => i)];
  const wsum = [0];
  for (const w of words) wsum.push(wsum[wsum.length - 1] + w.weight);
  const total = runs.reduce((s, r) => s + r.end - r.start, 0);
  const pace = wsum[N] / total; // weight per second
  const fit = (j, a, b) => {
    const d = runs[j].end - runs[j].start;
    if (b === a) return d < 0.25 ? 0.3 : 3;
    return Math.log((wsum[b] - wsum[a]) / (pace * d)) ** 2;
  };
  const cutBonus = (b) => (b > 0 && b < N && endsPhrase(words[b - 1].text) ? 0.5 : 0);
  // best[j][b]: lowest cost for runs 0..j holding words 0..b-1
  const best = Array.from({ length: K }, () => new Array(N + 1).fill(Infinity));
  const from = Array.from({ length: K }, () => new Array(N + 1).fill(0));
  for (let b = 0; b <= N; b++) best[0][b] = fit(0, 0, b) - cutBonus(b);
  for (let j = 1; j < K; j++) {
    for (let b = 0; b <= N; b++) {
      if (j === K - 1 && b !== N) continue;
      for (let a = 0; a <= b; a++) {
        const c = best[j - 1][a] + fit(j, a, b) - (j < K - 1 ? cutBonus(b) : 0);
        if (c < best[j][b]) {
          best[j][b] = c;
          from[j][b] = a;
        }
      }
    }
  }
  const cuts = [N];
  for (let j = K - 1; j > 0; j--) cuts.unshift(from[j][cuts[0]]);
  const groups = [];
  let start = 0;
  for (const c of cuts) {
    groups.push(Array.from({ length: c - start }, (_, i) => start + i));
    start = c;
  }
  return groups;
}

// Shares a run out among its words by weight. (Moving boundaries to loudness dips was tried
// against synthesized speech with known word timings, and did worse on continuous speech:
// dips fall inside words as often as between them.)
function placeInRun(words, idx, run) {
  const weight = idx.reduce((s, i) => s + words[i].weight, 0);
  let t = run.start;
  for (const i of idx) {
    words[i].start = t;
    t += ((run.end - run.start) * words[i].weight) / weight;
    words[i].end = t;
  }
}

function alignRange(words, db, from, to) {
  let runs = spokenRuns(db, from, to);
  if (!runs.length) runs = [{ start: from, end: to }];
  const groups = assign(words, runs);
  groups.forEach((idx, j) => placeInRun(words, idx, runs[j]));
}

// The sentence timings voice.js writes next to a generated line, moved by `shift` seconds
// (the silence the renderer trimmed from the start), if they still match the line's text.
function readSidecar(file, words, shift) {
  const json = file.replace(/\.[^.]+$/, '.json');
  if (!fs.existsSync(json)) return null;
  let data;
  try {
    data = JSON.parse(fs.readFileSync(json, 'utf8'));
  } catch {
    return null;
  }
  const sentences = (data.sentences || []).map((s) => ({ words: tokenize(s.text), start: s.start - shift, end: s.end - shift }));
  const flat = sentences.flatMap((s) => s.words.map(norm)).join(' ');
  if (!sentences.length || flat !== words.map((w) => norm(w.text)).join(' ')) return null;
  return sentences;
}

async function whisperWords(file) {
  let transformers;
  try {
    transformers = await import('@huggingface/transformers');
  } catch {
    throw new Error('--whisper needs @huggingface/transformers (it comes with kokoro-js: npm install kokoro-js)');
  }
  const asr = await transformers.pipeline('automatic-speech-recognition', 'onnx-community/whisper-base_timestamped', { dtype: 'q8', device: 'cpu' });
  const out = await asr(decode(file), { return_timestamps: 'word', chunk_length_s: 30 });
  return (out.chunks || []).map((c) => ({ text: c.text.trim(), start: c.timestamp[0], end: c.timestamp[1] }));
}

// Copies Whisper's times onto the line's own words, matching them in order (an edit-distance
// alignment, so a misheard or missing word doesn't shift the rest). Words with no match get
// times shared out between their matched neighbours. Returns false if the result can't be trusted.
function applyWhisper(words, heard, duration) {
  const a = words.map((w) => norm(w.text));
  const b = heard.map((h) => norm(h.text));
  const n = a.length;
  const m = b.length;
  const d = Array.from({ length: n + 1 }, (_, i) => Array.from({ length: m + 1 }, (_, j) => (i === 0 ? j : j === 0 ? i : 0)));
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  }
  const match = new Array(n).fill(-1);
  for (let i = n, j = m; i > 0 && j > 0;) {
    if (d[i][j] === d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)) {
      if (a[i - 1] === b[j - 1]) match[i - 1] = j - 1;
      i--;
      j--;
    } else if (d[i][j] === d[i - 1][j] + 1) i--;
    else j--;
  }
  const matched = match.filter((x) => x >= 0).length;
  if (matched < Math.max(1, 0.6 * n)) return false;
  const times = heard.map((h) => [h.start, h.end]);
  if (times.some(([s, e]) => !(s >= 0) || !(e >= s) || e > duration + 0.3)) return false;
  if (new Set(times.map(([s]) => s.toFixed(2))).size < Math.min(3, heard.length)) return false;
  for (let i = 0; i < n; i++) {
    if (match[i] >= 0) [words[i].start, words[i].end] = times[match[i]];
  }
  // fill the gaps between matched words
  for (let i = 0; i < n;) {
    if (match[i] >= 0) {
      i++;
      continue;
    }
    let j = i;
    while (j < n && match[j] < 0) j++;
    const lo = i > 0 ? words[i - 1].end : 0;
    const hi = j < n ? words[j].start : duration;
    const weight = words.slice(i, j).reduce((s, w) => s + w.weight, 0);
    let t = lo;
    for (let k = i; k < j; k++) {
      words[k].start = t;
      t += ((hi - lo) * words[k].weight) / weight;
      words[k].end = t;
    }
    i = j;
  }
  for (let i = 1; i < n; i++) if (words[i].start < words[i - 1].start) return false;
  return true;
}

const CACHE = path.join(os.tmpdir(), 'render-video-cache', 'captions');

// When each word of `text` is said in `file`. `shift` is how much silence was trimmed from the
// start of the original clip (for voice.js's sentence timings). Returns { words, method, duration }.
async function alignWords(file, text, { whisper = false, shift = 0, sidecarFor } = {}) {
  const st = fs.statSync(file);
  const key = crypto.createHash('sha1').update(JSON.stringify([file, st.size, st.mtimeMs, text, whisper, shift, sidecarFor || '', 2])).digest('hex');
  const cached = path.join(CACHE, `${key}.json`);
  if (fs.existsSync(cached)) return JSON.parse(fs.readFileSync(cached, 'utf8'));

  const words = tokenize(text).map((t) => ({ text: t, weight: wordWeight(t), start: 0, end: 0 }));
  const samples = decode(file);
  const duration = samples.length / SR;
  const db = envelope(samples);
  let method = 'pauses';
  const notes = [];
  if (whisper) {
    try {
      if (applyWhisper(words, await whisperWords(file), duration)) method = 'whisper';
      else notes.push("Whisper's word timing didn't hold up for this clip; used pauses and loudness instead");
    } catch (e) {
      notes.push(`Whisper unavailable (${e.message.split('\n')[0]}); used pauses and loudness instead`);
    }
  }
  if (method === 'pauses' && words.length) {
    const sentences = readSidecar(sidecarFor || file, words, shift);
    if (sentences) {
      method = 'sentences';
      let i = 0;
      for (const s of sentences) {
        alignRange(words.slice(i, i + s.words.length), db, Math.max(0, s.start), Math.min(duration, s.end));
        i += s.words.length;
      }
    } else {
      alignRange(words, db, 0, duration);
    }
  }
  const result = { words: words.map(({ text: t, start, end }) => ({ text: t, start: +start.toFixed(3), end: +end.toFixed(3) })), method, duration: +duration.toFixed(3), notes };
  fs.mkdirSync(CACHE, { recursive: true });
  fs.writeFileSync(cached, JSON.stringify(result));
  return result;
}

// Groups words into on-screen chunks. A phrase ends at punctuation or a pause; a long phrase
// is split into the fewest even chunks that keep each one within `maxWords` words,
// `maxChars` characters, and `maxDur` seconds, so no word is left on its own.
function chunkWords(words, { maxWords = 4, maxChars = 22, pause = 0.25, maxDur = 1.8 } = {}) {
  const phrases = [];
  let cur = [];
  words.forEach((w, i) => {
    cur.push(w);
    const next = words[i + 1];
    if (!next || endsPhrase(w.text) || next.start - w.end >= pause) {
      phrases.push(cur);
      cur = [];
    }
  });
  const chunks = [];
  const fits = (part) => part.length <= maxWords && part.map((x) => x.text).join(' ').length <= maxChars
    && part[part.length - 1].end - part[0].start <= maxDur;
  for (const phrase of phrases) {
    let parts;
    for (let k = Math.ceil(phrase.length / maxWords); k <= phrase.length; k++) {
      parts = Array.from({ length: k }, (_, i) => phrase.slice(Math.round((i * phrase.length) / k), Math.round(((i + 1) * phrase.length) / k)));
      if (parts.every((p) => p.length === 1 || fits(p))) break;
    }
    for (const p of parts) chunks.push({ words: p, start: p[0].start, end: p[p.length - 1].end });
  }
  return chunks;
}

// Styles for injected captions: each chunk cuts in whole (so the line never shifts as words
// arrive), and the word being said is highlighted (--hi, default yellow) from its start to
// its end.
const CAPTION_CSS = `
  .say.auto { display: grid; place-items: center; }
  .say.auto > .cc { grid-area: 1 / 1; display: block; animation: ccIn .08s ease-out var(--in) both, ccOut .01s linear var(--out, 999s) forwards; }
  .say.auto .cc i { font-style: normal; display: inline-block; color: #fff;
    animation: ccHi .04s linear var(--in) forwards, ccDone .04s linear var(--done) forwards; }
  @keyframes ccIn { from { opacity: 0; transform: scale(.92); } to { opacity: 1; transform: none; } }
  @keyframes ccOut { to { opacity: 0; } }
  @keyframes ccHi { to { color: var(--hi, #ffd23f); } }
  @keyframes ccDone { to { color: #fff; } }
`;

const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

// The markup for one line's chunks, with times offset by `t0` (when the clip starts playing).
// The last chunk stays up until `holdUntil`, if given.
function captionMarkup(chunks, t0, holdUntil) {
  return chunks.map((c, i) => {
    const next = chunks[i + 1];
    const out = next ? t0 + next.start : Math.max(t0 + c.end + 0.4, holdUntil || 0);
    const words = c.words.map((w) => `<i style="--in:${(t0 + w.start).toFixed(3)}s; --done:${(t0 + w.end).toFixed(3)}s">${escapeHtml(w.text)}</i>`).join(' ');
    return `<span class="cc" style="--in:${(t0 + c.start).toFixed(3)}s; --out:${out.toFixed(3)}s">${words}</span>`;
  }).join(' ');
}

const srtTime = (t) => {
  const ms = Math.max(0, Math.round(t * 1000));
  const p = (n, w = 2) => String(n).padStart(w, '0');
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
};

// An .srt file from [{ start, end, text }] in video time.
function toSrt(cues) {
  return cues.map((c, i) => `${i + 1}\n${srtTime(c.start)} --> ${srtTime(c.end)}\n${c.text}\n`).join('\n');
}

async function main() {
  const argv = process.argv.slice(2);
  const args = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--whisper') args.whisper = true;
    else if (argv[i] === '--json') args.json = true;
    else if (['--text', '--srt'].includes(argv[i])) args[argv[i].slice(2)] = argv[++i];
    else if (argv[i] === '-h' || argv[i] === '--help') args.help = true;
    else args.positional.push(argv[i]);
  }
  const file = args.positional[0];
  if (args.help || !file || !args.text) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }
  const result = await alignWords(file, args.text, { whisper: args.whisper });
  for (const n of result.notes) console.warn(`Note: ${n}`);
  const chunks = chunkWords(result.words);
  if (args.srt) fs.writeFileSync(args.srt, toSrt(chunks.map((c) => ({ start: c.start, end: c.end, text: c.words.map((w) => w.text).join(' ') }))));
  if (args.json) {
    console.log(JSON.stringify({ ...result, chunks: chunks.map((c) => ({ start: c.start, end: c.end, text: c.words.map((w) => w.text).join(' ') })) }, null, 2));
    return;
  }
  console.log(`${path.basename(file)}: ${result.duration}s, timed by ${result.method}`);
  for (const c of chunks) console.log(`  ${c.start.toFixed(2)}-${c.end.toFixed(2)}s  ${c.words.map((w) => `${w.text}@${w.start.toFixed(2)}`).join(' ')}`);
}

if (require.main === module) {
  main().catch((e) => {
    console.error(e.message || e);
    process.exit(1);
  });
}

module.exports = { assign, applyWhisper, alignWords, chunkWords, captionMarkup, toSrt, CAPTION_CSS, wordWeight, spokenRuns, envelope, decode };
