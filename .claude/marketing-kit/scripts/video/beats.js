#!/usr/bin/env node
'use strict';
/*
 * Finds the rhythm of a music track, so a page can cut on its beats: the tempo, every beat,
 * the bars (assuming 4/4), and where the track lifts (a drop or chorus), with how confident
 * it is. Runs locally with ffmpeg; no service or key.
 *
 * Usage:
 *   node beats.js <track>                                   # tempo, bars, the biggest lifts, confidence
 *   node beats.js <track> --align 2.2 --duration 24          # also: the data-music-start that lands the
 *                                                            # biggest lift at 2.2s into a 24s video, and
 *                                                            # every beat and bar in video time
 *   node beats.js <track> --start 32 --duration 24           # beat and bar times in video time for a start you chose
 *   node beats.js <track> ... --json                         # the same, as JSON
 *
 * It works well on music with a steady beat (pop, house, hip-hop, most library tracks) and
 * poorly on ambient or free-tempo music; a low confidence means don't snap cuts to it, time
 * them to the voiceover or reading pace instead. You can't hear the track, so send the user a
 * short render to check the sync.
 */
const { spawnSync } = require('child_process');
const fs = require('fs');

const SR = 22050;
const WIN = 1024;
const HOP = 256;
const FPS = SR / HOP;

function fail(message) {
  console.error(message);
  process.exit(2);
}

function decode(file) {
  const run = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-ac', '1', '-ar', String(SR), '-f', 'f32le', '-'], { maxBuffer: 1 << 30 });
  if (run.error || run.status !== 0) fail(`ffmpeg couldn't read ${file}: ${run.error ? run.error.message : run.stderr.toString().trim()}`);
  const b = run.stdout;
  return new Float32Array(b.buffer, b.byteOffset, Math.floor(b.length / 4));
}

// in-place radix-2 FFT
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const a = (-2 * Math.PI) / len;
    const wr = Math.cos(a);
    const wi = Math.sin(a);
    for (let i = 0; i < n; i += len) {
      let cr = 1;
      let ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ur = re[i + k];
        const ui = im[i + k];
        const vr = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci;
        const vi = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr;
        re[i + k] = ur + vr;
        im[i + k] = ui + vi;
        re[i + k + len / 2] = ur - vr;
        im[i + k + len / 2] = ui - vi;
        [cr, ci] = [cr * wr - ci * wi, cr * wi + ci * wr];
      }
    }
  }
}

// Onset strength per frame: how much the (log) spectrum rises, broadband and in the bass
// (kicks), plus each frame's loudness.
function analyse(x) {
  const frames = Math.max(0, Math.floor((x.length - WIN) / HOP) + 1);
  const hann = Float64Array.from({ length: WIN }, (_, i) => 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / WIN));
  const bins = WIN / 2;
  const top = Math.floor((8000 / SR) * WIN);
  const bass = Math.max(2, Math.floor((160 / SR) * WIN));
  let prev = new Float64Array(bins);
  const flux = new Float64Array(frames);
  const low = new Float64Array(frames);
  const rms = new Float64Array(frames);
  // pitch class (0-11) of each bin from 80 Hz to 2 kHz, for a per-frame chroma (chord) profile
  const pc = Int8Array.from({ length: bins }, (_, k) => {
    const hz = (k * SR) / WIN;
    return hz < 80 || hz > 2000 ? -1 : ((Math.round(12 * Math.log2(hz / 440)) % 12) + 12) % 12;
  });
  const chroma = new Float32Array(frames * 12);
  const bassE = new Float64Array(frames);
  const re = new Float64Array(WIN);
  const im = new Float64Array(WIN);
  for (let f = 0; f < frames; f++) {
    let e = 0;
    for (let i = 0; i < WIN; i++) {
      const s = x[f * HOP + i];
      e += s * s;
      re[i] = s * hann[i];
      im[i] = 0;
    }
    rms[f] = Math.sqrt(e / WIN);
    fft(re, im);
    const cur = new Float64Array(bins);
    let fl = 0;
    let lo = 0;
    for (let k = 1; k < top; k++) {
      const mag = Math.hypot(re[k], im[k]);
      if (pc[k] >= 0) chroma[f * 12 + pc[k]] += mag;
      cur[k] = Math.log1p(100 * mag);
      const d = cur[k] - prev[k];
      if (d > 0) {
        fl += d;
        if (k <= bass) lo += d;
      }
      if (k <= bass) bassE[f] += mag * mag;
    }
    flux[f] = fl;
    low[f] = lo;
    prev = cur;
  }
  return { flux: normalize(flux), low: normalize(low), rms, chroma, bassE };
}

// remove the slow trend (about half a second), keep the rises, scale to unit spread
function normalize(v) {
  const w = Math.round(FPS * 0.5);
  const out = new Float64Array(v.length);
  let sum = 0;
  const q = [];
  for (let i = 0; i < v.length; i++) {
    q.push(v[i]);
    sum += v[i];
    if (q.length > 2 * w + 1) sum -= q.shift();
    const center = i - w;
    if (center >= 0) out[center] = Math.max(0, v[center] - sum / q.length);
  }
  for (let i = Math.max(0, v.length - w); i < v.length; i++) out[i] = Math.max(0, v[i] - sum / q.length);
  let m = 0;
  for (const a of out) m += a * a;
  const sd = Math.sqrt(m / Math.max(1, out.length)) || 1;
  for (let i = 0; i < out.length; i++) out[i] /= sd;
  return out;
}

// Tempo from the onset curve's autocorrelation, weighted toward ~120 BPM so a double- or
// half-time reading only wins when the evidence for it is clearly stronger.
function tempo(env) {
  const minLag = Math.floor((60 / 200) * FPS);
  const maxLag = Math.ceil((60 / 55) * FPS);
  const ac = new Float64Array(3 * maxLag + 4);
  for (let lag = minLag - 1; lag <= 3 * maxLag + 3; lag++) {
    let s = 0;
    for (let i = lag; i < env.length; i++) s += env[i] * env[i - lag];
    ac[lag] = s / (env.length - lag);
  }
  // comb: a true period also scores at 2x and 3x the lag
  const comb = (lag) => ac[lag] + 0.5 * (ac[2 * lag] ?? 0) + 0.25 * (ac[3 * lag] ?? 0);
  const score = (lag) => {
    const bpm = (60 * FPS) / lag;
    return comb(lag) * Math.exp(-0.5 * (Math.log2(bpm / 120) / 0.9) ** 2);
  };
  let best = minLag;
  const scores = [];
  for (let lag = minLag; lag <= maxLag; lag++) {
    const s = score(lag);
    scores.push(s);
    if (s > score(best)) best = lag;
  }
  // a fast reading (hi-hats on every eighth) whose half-time is nearly as strong is the half-time
  if ((60 * FPS) / best > 145 && 2 * best + 1 <= maxLag) {
    let half = 2 * best - 1;
    for (const l of [2 * best, 2 * best + 1]) if (score(l) > score(half)) half = l;
    if (score(half) > 0.6 * score(best)) best = half;
  }
  // parabolic refinement of the peak
  const [a, b, c] = [score(best - 1), score(best), score(best + 1)];
  const shift = a - 2 * b + c !== 0 ? (0.5 * (a - c)) / (a - 2 * b + c) : 0;
  const period = best + Math.max(-0.5, Math.min(0.5, shift));
  const mean = scores.reduce((s, v) => s + v, 0) / scores.length;
  const sd = Math.sqrt(scores.reduce((s, v) => s + (v - mean) ** 2, 0) / scores.length) || 1;
  // the strongest rival that isn't the same tempo, double, or half (e.g. 120 against 90)
  const related = (lag) => [1, 2, 0.5, 3, 1 / 3].some((m) => Math.abs(lag / (period * m) - 1) < 0.06);
  let rival = 0;
  for (let lag = minLag; lag <= maxLag; lag++) {
    const isPeak = score(lag) >= score(lag - 1) && score(lag) >= score(lag + 1);
    if (isPeak && !related(lag)) rival = Math.max(rival, score(lag));
  }
  const lag0 = (() => { let z = 0; for (const v of env) z += v * v; return z / env.length; })();
  const rho = lag0 ? ac[Math.round(period)] / lag0 : 0;
  return { period, peak: (score(best) - mean) / sd, clarity: Math.max(0, 1 - rival / score(best)), rho };
}

// Beat tracking by dynamic programming (Ellis 2007): beats sit on strong onsets, about one
// period apart, with a penalty for stretching or squeezing the gap.
function track(env, period) {
  const n = env.length;
  const score = new Float64Array(n);
  const back = new Int32Array(n).fill(-1);
  const tight = 400;
  for (let t = 0; t < n; t++) {
    let bestV = 0;
    let bestI = -1;
    for (let tau = t - Math.round(2 * period); tau <= t - Math.round(period / 2); tau++) {
      if (tau < 0) continue;
      const v = score[tau] - tight * Math.log((t - tau) / period) ** 2;
      if (v > bestV) {
        bestV = v;
        bestI = tau;
      }
    }
    score[t] = env[t] + bestV;
    back[t] = bestI;
  }
  let t = n - 1;
  for (let i = Math.max(0, n - Math.round(period)); i < n; i++) if (score[i] > score[t]) t = i;
  const beats = [];
  for (; t >= 0; t = back[t]) beats.push(t);
  return beats.reverse();
}

// The biggest lifts: beats where the next couple of bars are much louder than the last couple,
// weighted toward the bass arriving (a drop, the beat coming in) so a riser's build-up before
// the drop doesn't win by a beat.
function lifts(rms, bassE, beatFrames, span = 8) {
  const db = (arr, i0, i1) => {
    let s = 0;
    let n = 0;
    for (let i = Math.max(0, i0); i < Math.min(beatFrames.length - 1, i1); i++) {
      for (let f = beatFrames[i]; f < beatFrames[i + 1]; f++) {
        s += arr === rms ? rms[f] * rms[f] : arr[f];
        n++;
      }
    }
    return n ? 10 * Math.log10(s / n + 1e-12) : -120;
  };
  const out = [];
  for (let i = 2; i < beatFrames.length - 2; i++) {
    const before = Math.min(span, i);
    const broad = db(rms, i, i + span) - db(rms, i - before, i);
    const low = db(bassE, i, i + span) - db(bassE, i - before, i);
    const jump = db(bassE, i, i + 1) - db(bassE, i - 1, i);
    out.push({ frame: beatFrames[i], rise: broad, score: broad + low + 0.5 * jump });
  }
  const w = span * (beatFrames.length > 1 ? (beatFrames[beatFrames.length - 1] - beatFrames[0]) / (beatFrames.length - 1) : FPS);
  return out.sort((a, b) => b.score - a.score)
    .filter((c, i, all) => all.slice(0, i).every((d) => Math.abs(d.frame - c.frame) > w))
    .filter((c) => c.rise > 1)
    .slice(0, 3);
}

function analyseTrack(file) {
  const x = decode(file);
  const duration = x.length / SR;
  if (duration < 4) fail(`${file} is only ${duration.toFixed(1)}s; need a few bars of music to find a beat.`);
  const { flux, low, rms, chroma, bassE } = analyse(x);
  const env = flux.map((v, i) => v + 0.5 * low[i]);
  const { period, peak, clarity, rho } = tempo(env);
  const beatFrames = track(env, period);
  // frames are centred half a window after their start
  const toTime = (f) => (f * HOP + WIN / 2) / SR;
  const beats = beatFrames.map(toTime);
  // tempo from the tracked beats themselves (a straight-line fit), finer than the period
  let bpm = (60 * FPS) / period;
  if (beats.length > 8) {
    const k = beats.map((_, i) => i);
    const mk = k.reduce((s, v) => s + v, 0) / k.length;
    const mt = beats.reduce((s, v) => s + v, 0) / beats.length;
    const slope = k.reduce((s, v, i) => s + (v - mk) * (beats[i] - mt), 0) / k.reduce((s, v) => s + (v - mk) ** 2, 0);
    if (slope > 0) bpm = 60 / slope;
  }
  // how many beats land on a real onset, versus the track's typical frame
  const sorted = [...env].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];
  const strong = beatFrames.filter((f) => Math.max(env[f - 1] ?? 0, env[f], env[f + 1] ?? 0) > median + 1).length / Math.max(1, beatFrames.length);
  // bars: the beat phase (of 4) where the bass hits hardest and the chords change most. Chord
  // change at beat i = how different the chroma of the two beats after it is from the two before.
  const span = (i0, i1) => {
    const v = new Float64Array(12);
    for (let f = beatFrames[Math.max(0, i0)]; f < (beatFrames[Math.min(beatFrames.length - 1, i1)] ?? f); f++) for (let c = 0; c < 12; c++) v[c] += chroma[f * 12 + c];
    return v;
  };
  const cosDist = (a, b) => {
    let ab = 0;
    let aa = 0;
    let bb = 0;
    for (let c = 0; c < 12; c++) {
      ab += a[c] * b[c];
      aa += a[c] * a[c];
      bb += b[c] * b[c];
    }
    return aa && bb ? 1 - ab / Math.sqrt(aa * bb) : 0;
  };
  const change = beatFrames.map((_, i) => (i >= 2 && i + 2 < beatFrames.length ? cosDist(span(i - 2, i), span(i, i + 2)) : 0));
  const byPhase = (val) => [0, 1, 2, 3].map((p) => {
    let s = 0;
    let n = 0;
    for (let i = p; i < beatFrames.length; i += 4) {
      s += val(i);
      n++;
    }
    return n ? s / n : 0;
  });
  const unit = (v) => {
    const m = Math.max(...v);
    return m > 0 ? v.map((x) => x / m) : v;
  };
  const hits = unit(byPhase((i) => low[beatFrames[i]] + 0.5 * env[beatFrames[i]]));
  const chords = unit(byPhase((i) => change[i]));
  const phaseScore = hits.map((h, p) => h + chords[p]);
  const order = [...phaseScore].sort((a, b) => b - a);
  const phase = phaseScore.indexOf(order[0]);
  const barFrames = beatFrames.filter((_, i) => i % 4 === phase);
  if (process.env.BEATS_DEBUG) console.error({ peak: round(peak, 2), strong: round(strong, 2), clarity: round(clarity, 2), rho: round(rho, 2) });
  // Confidence rests on the two measures that separate a real beat from none: how many tracked
  // beats land on an actual hit, and how strongly the onsets repeat at the period. (Checked
  // against the plugin's own music in eight genres, noise, and a sustained pad.)
  const ramp = (v, lo, hi) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  const confidence = 0.5 * ramp(strong, 0.6, 0.95) + 0.5 * ramp(rho, 0.4, 0.7);
  return {
    file,
    duration: round(duration),
    bpm: round(bpm, 1),
    confidence: round(confidence, 2),
    barConfidence: round(order[0] > 0 ? (order[0] - order[1]) / order[0] : 0, 2),
    beats: beats.map((t) => round(t)),
    bars: barFrames.map((f) => round(toTime(f))),
    lifts: lifts(rms, bassE, beatFrames).map((l) => ({ time: round(toTime(l.frame)), rise: round(l.rise, 1) })),
  };
}

const round = (v, d = 3) => Math.round(v * 10 ** d) / 10 ** d;
const clock = (t) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, '0')}`;

function parseArgs(argv) {
  const args = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--json') args.json = true;
    else if (['--align', '--duration', '--start'].includes(a)) args[a.slice(2)] = Number(argv[++i]);
    else if (a === '-h' || a === '--help') args.help = true;
    else args.positional.push(a);
  }
  return args;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const file = args.positional[0];
  if (args.help || !file) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }
  if (!fs.existsSync(file)) fail(`No track at ${file}`);
  const r = analyseTrack(file);
  const notes = [];

  // where the music starts in the video, and the rhythm in video time
  let start = Number.isFinite(args.start) ? args.start : undefined;
  if (Number.isFinite(args.align)) {
    const lift = r.lifts[0];
    if (!lift) notes.push('no clear lift in this track to align; starting it at 0');
    start = lift ? lift.time - args.align : 0;
    if (start < 0) {
      notes.push(`the lift is at ${lift.time}s, so it can't land at ${args.align}s; it lands at ${round(lift.time, 2)}s with the track starting at 0`);
      start = 0;
    }
  }
  if (start !== undefined) {
    const d = Number.isFinite(args.duration) ? args.duration : r.duration - start;
    if (start + d > r.duration) notes.push(`the track has only ${round(r.duration - start, 1)}s from ${round(start, 2)}s, less than the ${d}s video; the music will stop early`);
    const inVideo = (ts) => ts.map((t) => round(t - start)).filter((t) => t >= 0 && t <= d);
    r.musicStart = round(start, 2);
    r.video = { beats: inVideo(r.beats), bars: inVideo(r.bars), lifts: r.lifts.map((l) => ({ ...l, time: round(l.time - start) })).filter((l) => l.time >= 0 && l.time <= d) };
  }
  if (r.confidence < 0.5) notes.push('low confidence: this track has no steady beat to cut on; time scenes to the voiceover or reading pace instead');
  else if (r.barConfidence < 0.15) notes.push('the beats are clear but which beat starts a bar is a guess; cut on any beat rather than relying on bar starts');
  r.notes = notes;

  if (args.json) {
    console.log(JSON.stringify(r, null, 2));
    return;
  }
  const beat = 60 / r.bpm;
  console.log(`${file}: ${clock(r.duration)} long, ${r.bpm} BPM (a beat every ${round(beat, 3)}s, a bar every ${round(beat * 4, 3)}s), confidence ${r.confidence}`);
  console.log(`first beat at ${r.beats[0]}s, first bar at ${r.bars[0]}s, ${r.beats.length} beats`);
  for (const l of r.lifts) console.log(`lift at ${clock(l.time)} (${l.time}s): +${l.rise} dB over the next bars`);
  if (r.musicStart !== undefined) {
    console.log(`\ndata-music-start="${r.musicStart}"`);
    console.log(`bars in the video (s): ${r.video.bars.join(', ')}`);
    console.log(`beats in the video (s): ${r.video.beats.join(', ')}`);
  }
  for (const n of notes) console.log(`Note: ${n}`);
}

if (require.main === module) main();

module.exports = { analyseTrack };
