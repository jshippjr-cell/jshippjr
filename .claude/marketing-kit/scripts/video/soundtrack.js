'use strict';
/*
 * Synthesizes an original soundtrack for a rendered video: music in one of
 * eleven genres, built around the project's signature hook, plus sound effects
 * (UI sounds and meme cues) placed on the page's own animation cues. It's all generated from scratch
 * and deterministic: the same page always sounds the same, there's nothing
 * to license, and it works when posting through an API, where in-app sounds
 * can't be added.
 *
 * The music, from <body data-*> (references/sound-guide.md explains how to
 * pick these per project):
 * - data-music: pop, house, hiphop, acoustic, cinematic, tech, lofi, calm, phonk,
 *   jersey, funk, or none
 * - data-bpm, data-key (C, F#, Bb, ...), data-mode (major or minor), data-energy (1-5)
 * - data-motif: the project's signature hook, two bars of scale degrees,
 *   e.g. "1 3 5 6 | 5 3 2 -". Each bar's tokens share it equally; ' and ,
 *   shift a note an octave up or down, - holds the previous note, . rests.
 * - data-drop: when the beat comes in. The intro builds into it.
 * - data-break="8.5-13.5": thins the music out under quieter moments.
 *
 * How it plays: the hook enters at the drop as the lead melody, answered by a
 * variation every four bars, over chords chosen to fit it. The video ends on
 * a "sonic logo": the hook's opening notes resolving to the home note on the
 * last beat, so every video for a project closes the same recognizable way.
 *
 * render.js reads the page and calls buildSoundtrack(); no dependencies.
 */

const SR = 48000;
const TAU = 2 * Math.PI;
const SOUNDS = [
  'pop', 'swish', 'tick', 'whoosh', 'click', 'chime',
  // meme sounds, all synthesized here (no samples)
  'boom', 'scratch', 'horn', 'rimshot', 'fail', 'drumroll', 'ding', 'buzzer', 'ping', 'typing', 'shutter', 'cash', 'glitch', 'bass',
];
// average level of the music bed, relative to the sound effects (about -19 dBFS RMS)
const MUSIC_RMS = 0.11;

// ---------- music theory ----------

const NOTE = { C: 0, 'C#': 1, Db: 1, D: 2, 'D#': 3, Eb: 3, E: 4, F: 5, 'F#': 6, Gb: 6, G: 7, 'G#': 8, Ab: 8, A: 9, 'A#': 10, Bb: 10, B: 11 };
const MODES = { major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10] };
const mtof = (m) => 440 * 2 ** ((m - 69) / 12);

// Scale degrees are 0-based here ("1" in a motif is degree 0); 7 is the next octave up.
class Key {
  constructor(name, mode) {
    this.tonic = 60 + (NOTE[name] ?? 0);
    if (this.tonic > 65) this.tonic -= 12; // keep every key's home note between G3 and F4
    this.scale = MODES[mode] || MODES.major;
  }

  midi(degree, octave = 0) {
    const i = ((degree % 7) + 7) % 7;
    return this.tonic + this.scale[i] + 12 * (Math.floor(degree / 7) + octave);
  }

  // Diatonic chord on a scale degree: 3 notes for a triad, 4 for a seventh.
  chord(root, size = 3, octave = 0) {
    return Array.from({ length: size }, (_, k) => this.midi(root + 2 * k, octave));
  }
}

// Parses a motif like "1 3 5 6 | 5 3 2 -" into notes with start and length in beats.
function parseMotif(text, beatsPerBar = 4) {
  const notes = [];
  const bars = String(text).split('|').map((b) => b.trim()).filter(Boolean);
  if (!bars.length) throw new Error('empty motif');
  bars.forEach((bar, bi) => {
    const tokens = bar.split(/\s+/);
    const step = beatsPerBar / tokens.length;
    tokens.forEach((tok, ti) => {
      const start = bi * beatsPerBar + ti * step;
      if (tok === '-') {
        if (notes.length) notes[notes.length - 1].dur += step;
        return;
      }
      if (tok === '.') return;
      const m = /^([1-7])([',]*)$/.exec(tok);
      if (!m) throw new Error(`"${tok}" isn't a scale degree 1-7, -, or .`);
      const octave = [...m[2]].reduce((o, c) => o + (c === "'" ? 1 : -1), 0);
      notes.push({ deg: Number(m[1]) - 1 + 7 * octave, start, dur: step });
    });
  });
  if (!notes.length) throw new Error('motif has no notes');
  return { notes, beats: bars.length * beatsPerBar };
}

// ---------- DSP building blocks ----------

const len = (dur) => Math.max(0, Math.floor(dur * SR));

function makeRng(seed) {
  let s = seed >>> 0;
  const u = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const n = () => Math.sqrt(-2 * Math.log(u() + 1e-12)) * Math.cos(TAU * u());
  return { u, n };
}

const hashString = (text) => [...text].reduce((h, c) => (Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0), 2166136261);

// Topology-preserving state-variable filter: resonant, stable under fast cutoff sweeps.
class SVF {
  constructor() { this.s1 = 0; this.s2 = 0; }
  step(x, cutoff, q) {
    const g = Math.tan(Math.PI * Math.min(Math.max(cutoff, 20), SR * 0.45) / SR);
    const k = 1 / q;
    const a1 = 1 / (1 + g * (g + k));
    const v3 = x - this.s2;
    const v1 = a1 * this.s1 + g * a1 * v3;
    const v2 = this.s2 + g * v1;
    this.s1 = 2 * v1 - this.s1;
    this.s2 = 2 * v2 - this.s2;
    this.lp = v2;
    this.bp = v1;
    this.hp = x - k * v1 - v2;
    return v2;
  }
}

function filter(x, type, cutoff, q = 0.707) {
  const f = new SVF();
  const out = new Float64Array(x.length);
  for (let i = 0; i < x.length; i++) {
    f.step(x[i], typeof cutoff === 'function' ? cutoff(i / SR) : cutoff, q);
    out[i] = f[type];
  }
  return out;
}

function noise(rng, n) {
  const x = new Float64Array(n);
  for (let i = 0; i < n; i++) x[i] = rng.n();
  return x;
}

// Band-limited sawtooth (polyBLEP), so bright synths don't alias.
function blep(t, dt) {
  if (t < dt) { t /= dt; return t + t - t * t - 1; }
  if (t > 1 - dt) { t = (t - 1) / dt; return t * t + t + t + 1; }
  return 0;
}

function addSaw(out, freq, phase, gain) {
  const dt = freq / SR;
  let p = phase;
  for (let i = 0; i < out.length; i++) {
    out[i] += (2 * p - 1 - blep(p, dt)) * gain;
    p += dt;
    if (p >= 1) p -= 1;
  }
}

// Attack/decay/sustain/release, with the note held for `hold` seconds.
function adsr(n, a, d, s, r, hold) {
  const env = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    let v = t < a ? t / a : t < a + d ? 1 - (1 - s) * ((t - a) / d) : s;
    if (t > hold) v *= Math.max(0, 1 - (t - hold) / r);
    env[i] = v;
  }
  return env;
}

const scale = (x, env) => { for (let i = 0; i < x.length; i++) x[i] *= env[i]; return x; };

// ---------- instruments ----------

// Detuned-saw chord or note through a filter whose cutoff falls from `bright` to `dark`: the modern pop/house pluck.
function supersaw(rng, notes, dur, { bright = 5000, dark = 900, fall = 0.18, attack = 0.004, sustain = 0.55, voices = 5, q = 0.9 } = {}) {
  const n = len(dur + 0.25);
  const x = new Float64Array(n);
  const spread = [0, -11, 11, -19, 19, -6, 6].slice(0, voices);
  for (const m of notes) for (const c of spread) addSaw(x, mtof(m) * 2 ** (c / 1200), rng.u(), 1 / (voices * notes.length));
  const out = filter(x, 'lp', (t) => dark + (bright - dark) * Math.exp(-t / fall), q);
  return scale(out, adsr(n, attack, 0.25, sustain, 0.2, dur));
}

// Slow-attack string pad (cinematic, calm).
function strings(rng, notes, dur, { cutoff = 1800, attack = 0.6 } = {}) {
  const n = len(dur + 0.6);
  const x = new Float64Array(n);
  for (const m of notes) for (const c of [0, -8, 8, -15, 15]) addSaw(x, mtof(m) * 2 ** (c / 1200), rng.u(), 1 / (5 * notes.length));
  return scale(filter(x, 'lp', cutoff, 0.6), adsr(n, attack, 0.5, 0.85, 0.6, dur));
}

// Karplus-Strong plucked string: guitar and harp.
function pluckString(rng, freq, dur, { bright = 0.5, decay = 0.996 } = {}) {
  const n = len(dur);
  const out = new Float64Array(n);
  const period = SR / freq;
  const size = Math.ceil(period) + 2;
  const buf = new Float64Array(size);
  for (let i = 0; i < size; i++) buf[i] = rng.u() * 2 - 1;
  // soften the excitation: darker strings average more of the burst
  for (let pass = 0; pass < Math.round((1 - bright) * 4); pass++) {
    for (let i = 1; i < size; i++) buf[i] = 0.5 * (buf[i] + buf[i - 1]);
  }
  let w = 0;
  for (let i = 0; i < n; i++) {
    // read with fractional delay (linear interpolation) so high notes stay in tune
    const rp = (w - period + size * 4) % size;
    const i0 = Math.floor(rp);
    const fr = rp - i0;
    const a = buf[i0 % size];
    const b = buf[(i0 + 1) % size];
    const y = a + (b - a) * fr;
    const prev = buf[(i0 - 1 + size) % size];
    buf[w] = decay * 0.5 * (y + prev);
    out[i] = y;
    w = (w + 1) % size;
  }
  const fade = len(0.04);
  for (let i = Math.max(0, n - fade); i < n; i++) out[i] *= (n - i) / fade;
  return out;
}

// FM electric piano (Rhodes-like): a bell-ish attack that mellows as the modulation index falls.
function epiano(freq, dur, { index = 2.2, decay = 1.4, tine = 0.18 } = {}) {
  const n = len(dur + 0.3);
  const out = new Float64Array(n);
  const wc = TAU * freq / SR;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const idx = index * Math.exp(-t / 0.25) + 0.35;
    const env = Math.min(1, t / 0.002) * Math.exp(-t / decay) * (t > dur ? Math.max(0, 1 - (t - dur) / 0.3) : 1);
    out[i] = (Math.sin(wc * i + idx * Math.sin(wc * i)) + tine * Math.sin(14 * wc * i) * Math.exp(-t / 0.05)) * env;
  }
  return out;
}

function bell(freq, dur = 1.4) {
  const partials = [[1, 1.0, 0.6], [2.0, 0.5, 0.35], [2.76, 0.3, 0.2], [5.4, 0.15, 0.08]];
  const n = len(dur);
  const out = new Float64Array(n);
  for (const [ratio, amp, decay] of partials) {
    const w = TAU * freq * ratio / SR;
    for (let i = 0; i < n; i++) out[i] += amp * Math.sin(w * i) * Math.exp(-i / SR / decay);
  }
  return out;
}

// Drawbar-organ stab for house chords.
function organ(notes, dur) {
  const n = len(dur + 0.05);
  const out = new Float64Array(n);
  for (const m of notes) {
    const w = TAU * mtof(m) / SR;
    for (let i = 0; i < n; i++) out[i] += (Math.sin(w * i) + 0.6 * Math.sin(2 * w * i) + 0.35 * Math.sin(3 * w * i) + 0.2 * Math.sin(4 * w * i)) / notes.length;
  }
  return scale(out, adsr(n, 0.003, 0.12, 0.5, 0.05, dur));
}

// Bass: a clean sine with harmonics (audible on phone speakers), or a filtered saw.
function bass(freq, dur, type = 'sine') {
  const n = len(dur + 0.05);
  if (type === 'saw') {
    const x = new Float64Array(n);
    addSaw(x, freq, 0, 1);
    return scale(filter(x, 'lp', (t) => 260 + 900 * Math.exp(-t / 0.08), 1.1), adsr(n, 0.004, 0.15, 0.7, 0.05, dur));
  }
  const out = new Float64Array(n);
  const w = TAU * freq / SR;
  for (let i = 0; i < n; i++) out[i] = Math.sin(w * i) + 0.32 * Math.sin(2 * w * i) + 0.12 * Math.sin(3 * w * i);
  return scale(out, adsr(n, 0.006, 0.2, 0.75, 0.06, dur));
}

// 808: a sine that drops into pitch, long tail, driven into soft clipping (harder for phonk).
function sub808(freq, dur, drive = 2.2) {
  const n = len(dur + 0.1);
  const out = new Float64Array(n);
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * freq * (1 + 1.2 * Math.exp(-t / 0.03)) / SR;
    const env = Math.min(1, t / 0.002) * Math.exp(-t / Math.max(0.25, dur * 0.8)) * (t > dur ? Math.max(0, 1 - (t - dur) / 0.1) : 1);
    out[i] = Math.tanh(drive * Math.sin(p)) * env / Math.tanh(drive);
  }
  return out;
}

// Pitched 808-style cowbell: two squares a ratio of ~1.48 apart, band-passed. Phonk's lead.
function cowbell(freq, dur) {
  const n = len(Math.max(dur, 0.12) + 0.2);
  const x = new Float64Array(n);
  let p1 = 0;
  let p2 = 0;
  for (let i = 0; i < n; i++) {
    p1 = (p1 + freq / SR) % 1;
    p2 = (p2 + (freq * 1.481) / SR) % 1;
    x[i] = (p1 < 0.5 ? 1 : -1) + 0.7 * (p2 < 0.5 ? 1 : -1);
  }
  const out = filter(x, 'bp', freq * 2.2, 1.4);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] *= Math.min(1, t / 0.001) * (0.6 * Math.exp(-t / 0.06) + 0.4 * Math.exp(-t / 0.22));
  }
  return out;
}

function kick(rng, { pitch = 48, punch = 120, decay = 0.22, click = 0.3 } = {}) {
  const n = len(0.45);
  const out = new Float64Array(n);
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * (pitch + punch * Math.exp(-t / 0.032)) / SR;
    out[i] = Math.tanh(1.4 * Math.sin(p)) * Math.exp(-t / decay) + rng.n() * Math.exp(-t / 0.0015) * click;
  }
  return out;
}

function snare(rng, { tone = 185, decay = 0.13 } = {}) {
  const n = len(0.3);
  const body = filter(noise(rng, n), 'bp', 1900, 0.8);
  const w = TAU * tone / SR;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    body[i] = body[i] * 0.9 * Math.exp(-t / decay) + Math.sin(w * i) * 0.55 * Math.exp(-t / 0.05);
  }
  return body;
}

function clap(rng) {
  const n = len(0.32);
  const x = filter(noise(rng, n), 'bp', 1300, 1.2);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    let env = 0;
    for (const off of [0, 0.011, 0.022]) if (t >= off) env += Math.exp(-(t - off) / (off < 0.02 ? 0.01 : 0.11));
    x[i] *= env * 0.8;
  }
  return x;
}

function hat(rng, open = false) {
  const n = len(open ? 0.32 : 0.07);
  const x = filter(noise(rng, n), 'hp', 7500, 0.8);
  for (let i = 0; i < n; i++) x[i] *= Math.exp(-i / SR / (open ? 0.11 : 0.018)) * 0.5;
  return x;
}

function shaker(rng) {
  const n = len(0.12);
  const x = filter(noise(rng, n), 'bp', 6000, 0.7);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    x[i] *= Math.min(1, t / 0.012) * Math.exp(-t / 0.035) * 0.6;
  }
  return x;
}

function tom(rng, freq) {
  const n = len(0.5);
  const out = new Float64Array(n);
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * freq * (1 + 0.5 * Math.exp(-t / 0.05)) / SR;
    out[i] = Math.sin(p) * Math.exp(-t / 0.25) + rng.n() * Math.exp(-t / 0.01) * 0.15;
  }
  return out;
}

// Cinematic low hit at the drop.
function impact(rng) {
  const n = len(2.2);
  const out = new Float64Array(n);
  let p = 0;
  const air = filter(noise(rng, n), 'lp', 900, 0.7);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * (34 + 70 * Math.exp(-t / 0.12)) / SR;
    out[i] = Math.tanh(2 * Math.sin(p)) * Math.exp(-t / 0.7) + air[i] * Math.exp(-t / 0.3) * 0.5;
  }
  return out;
}

function crash(rng, dur = 1.6) {
  const n = len(dur);
  const x = filter(noise(rng, n), 'hp', 5000, 0.7);
  for (let i = 0; i < n; i++) x[i] *= Math.exp(-i / SR / 0.5) * 0.35;
  return x;
}

function riser(rng, dur) {
  const n = len(dur);
  const out = new Float64Array(n);
  const f = new SVF();
  let phase = 0;
  for (let i = 0; i < n; i++) {
    const p = i / n;
    f.step(rng.n(), 400 + 7000 * p * p, 1.5);
    phase += TAU * (220 + 900 * p * p) / SR;
    out[i] = (f.bp * 0.5 + Math.sin(phase) * 0.12) * p ** 2.2;
  }
  return out;
}

function vinyl(rng, dur) {
  const n = len(dur);
  const out = filter(noise(rng, n), 'bp', 3000, 0.5);
  for (let i = 0; i < n; i++) {
    out[i] *= 0.02;
    if (rng.u() < 6 / SR) out[i] += (rng.u() - 0.5) * 0.6; // the odd crackle
  }
  return out;
}

// ---------- sound effects (placed on the page's cues) ----------

function sfxPluck(rng, f, dur = 0.35) {
  const n = len(dur);
  const out = new Float64Array(n);
  const w = TAU * f / SR;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = Math.sin(w * i) * Math.exp(-t / 0.12) + 0.35 * Math.sin(2 * w * i) * Math.exp(-t / 0.05) + rng.n() * Math.exp(-t / 0.003) * 0.15;
  }
  return out;
}

function marimba(f, dur = 0.4) {
  const n = len(dur);
  const out = new Float64Array(n);
  const w = TAU * f / SR;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    out[i] = Math.sin(w * i) * Math.exp(-t / 0.13) + 0.25 * Math.sin(3.93 * w * i) * Math.exp(-t / 0.03);
  }
  return out;
}

function swish(rng, dur = 0.22, bright = 1) {
  const n = len(dur);
  const x = filter(noise(rng, n), bright > 1 ? 'hp' : 'bp', bright > 1 ? 4000 : 2500, 0.6);
  for (let i = 0; i < n; i++) x[i] *= Math.sin(Math.PI * i / n) ** 2 * 0.45;
  return x;
}

function whoosh(rng, dur = 0.5) {
  const n = len(dur);
  const out = new Float64Array(n);
  const f = new SVF();
  for (let i = 0; i < n; i++) {
    const p = i / n;
    f.step(rng.n(), 300 + 5000 * p, 1.2);
    out[i] = f.bp * Math.sin(Math.PI * p) ** 3 * 0.7;
  }
  return out;
}

function click(rng) {
  const n = len(0.03);
  const out = new Float64Array(n);
  const w = TAU * 2800 / SR;
  for (let i = 0; i < n; i++) out[i] = (rng.n() * 0.5 + Math.sin(w * i)) * Math.exp(-i / SR / 0.004);
  return out;
}

// ---- meme sounds: original syntheses of the classic comedic beats ----

// A deep, distorted impact with a long room tail (the punchline hit).
function boom(rng) {
  const n = len(2.4);
  const dry = new Float64Array(n);
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * (40 + 110 * Math.exp(-t / 0.05)) / SR;
    dry[i] = (Math.tanh(3.2 * Math.sin(p)) * Math.exp(-t / 0.55) + rng.n() * Math.exp(-t / 0.004) * 0.4) * 0.8;
  }
  const wet = reverb(dry, dry, { room: 0.88, damp: 0.25 });
  for (let i = 0; i < n; i++) dry[i] += (wet.L[i] + wet.R[i]) * 0.9;
  return dry;
}

// Record scratch: noise and a tone dragged back and forth in pitch.
function scratch(rng) {
  const n = len(0.5);
  const out = new Float64Array(n);
  const f = new SVF();
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    const drag = Math.abs(Math.sin(TAU * 5.5 * t)) ** 1.4;
    f.step(rng.n(), 400 + 3200 * drag, 3);
    p += TAU * (180 + 700 * drag) / SR;
    out[i] = (f.bp * 0.9 + Math.sin(p) * 0.35) * Math.sin(Math.PI * t / 0.5) ** 0.5;
  }
  return out;
}

// Airhorn: three blasts of detuned, driven saws.
function horn(rng) {
  const blasts = [[0, 0.14], [0.19, 0.14], [0.38, 0.55]];
  const n = len(1.0);
  const x = new Float64Array(n);
  for (const f0 of [466, 470, 698]) addSaw(x, f0, rng.u(), 1 / 3);
  const out = filter(x, 'bp', 1500, 0.9);
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    let env = 0;
    for (const [a, d] of blasts) if (t >= a && t < a + d) env = Math.min(1, (t - a) / 0.01, (a + d - t) / 0.03);
    out[i] = Math.tanh(3 * out[i]) * env;
  }
  return out;
}

// Ba-dum-tss.
function rimshot(rng) {
  const n = len(1.4);
  const out = new Float64Array(n);
  const put = (sig, t0, g) => { const o = len(t0); for (let i = 0; i < sig.length && i + o < n; i++) out[i + o] += sig[i] * g; };
  put(snare(rng, { decay: 0.09 }), 0, 0.8);
  put(tom(rng, 130), 0.17, 0.8);
  put(crash(rng, 1.1), 0.34, 1.6);
  return out;
}

// Sad trombone: four descending notes, the last one wobbling.
function fail(rng) {
  const notes = [[293.7, 0, 0.32], [277.2, 0.36, 0.32], [261.6, 0.72, 0.32], [246.9, 1.08, 1.0]];
  const n = len(2.2);
  const out = new Float64Array(n);
  for (const [f0, t0, d] of notes) {
    const m = len(d + 0.1);
    const x = new Float64Array(m);
    let p = 0;
    for (let i = 0; i < m; i++) {
      const t = i / SR;
      const vib = d > 0.5 ? 1 + 0.025 * Math.sin(TAU * 5 * Math.max(0, t - 0.2)) : 1;
      p = (p + f0 * vib * (1 - 0.03 * Math.min(1, t / d)) / SR) % 1;
      x[i] = 2 * p - 1;
    }
    // the "wah": a filter that opens and closes on each note
    const y = filter(x, 'lp', (t) => 500 + 1700 * Math.sin(Math.PI * Math.min(1, t / d)), 2);
    const o = len(t0);
    for (let i = 0; i < m && i + o < n; i++) out[i + o] += y[i] * Math.min(1, i / SR / 0.02, (d + 0.1 - i / SR) / 0.1) * 0.8;
  }
  return out;
}

// A snare roll that builds for 1.5s (pair it with a boom or chime on the reveal).
function drumroll(rng) {
  const n = len(1.5);
  const out = new Float64Array(n);
  for (let t0 = 0; t0 < 1.45; t0 += 0.045) {
    const s = snare(rng, { decay: 0.05 });
    const g = 0.15 + 0.85 * (t0 / 1.45) ** 1.5;
    const o = len(t0);
    for (let i = 0; i < s.length && i + o < n; i++) out[i + o] += s[i] * g * 0.6;
  }
  return out;
}

// Correct: two bright bell notes going up.
function ding() {
  const n = len(1.2);
  const out = new Float64Array(n);
  const a = bell(1318.5, 1.0);
  const b = bell(1760, 1.1);
  for (let i = 0; i < n; i++) out[i] = (a[i] || 0) * 0.5 + (i >= len(0.1) ? (b[i - len(0.1)] || 0) * 0.6 : 0);
  return out;
}

// Wrong: a low, buzzing square.
function buzzer() {
  const n = len(0.65);
  const out = new Float64Array(n);
  let p1 = 0;
  let p2 = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p1 = (p1 + 110 / SR) % 1;
    p2 = (p2 + 116.5 / SR) % 1;
    out[i] = Math.tanh(2 * ((p1 < 0.5 ? 1 : -1) + (p2 < 0.5 ? 1 : -1)) * 0.5) * Math.min(1, t / 0.01, (0.65 - t) / 0.05) * 0.6;
  }
  return filter(out, 'lp', 2500, 0.7);
}

// A message notification: two soft rising blips.
function ping() {
  const n = len(0.6);
  const out = new Float64Array(n);
  for (const [f0, t0] of [[1046.5, 0], [1568, 0.09]]) {
    const o = len(t0);
    for (let i = o; i < n; i++) {
      const t = (i - o) / SR;
      out[i] += Math.sin(TAU * f0 * t) * Math.exp(-t / 0.12) * Math.min(1, t / 0.003) * 0.5;
    }
  }
  return out;
}

// A short burst of keyboard typing.
function typing(rng) {
  const n = len(0.9);
  const out = new Float64Array(n);
  let t0 = 0;
  while (t0 < 0.8) {
    const o = len(t0);
    const tone = 2500 + rng.u() * 1500;
    for (let i = 0; i < len(0.025) && i + o < n; i++) {
      const t = i / SR;
      out[i + o] += (rng.n() * 0.6 + Math.sin(TAU * tone * t) * 0.3) * Math.exp(-t / 0.004) * (0.6 + 0.4 * rng.u());
    }
    t0 += 0.06 + rng.u() * 0.09;
  }
  return filter(out, 'hp', 1200, 0.7);
}

// Camera shutter: two mechanical clicks and a breath of noise.
function shutter(rng) {
  const n = len(0.25);
  const out = new Float64Array(n);
  for (const t0 of [0, 0.045]) {
    const o = len(t0);
    for (let i = 0; i < len(0.03) && i + o < n; i++) out[i + o] += rng.n() * Math.exp(-i / SR / 0.006) * 0.8;
  }
  return filter(out, 'hp', 1500, 0.7);
}

// Ka-ching: a metallic hit, then coins.
function cash(rng) {
  const n = len(1.1);
  const out = new Float64Array(n);
  const hit = bell(2093, 0.9);
  for (let i = 0; i < hit.length && i < n; i++) out[i] += hit[i] * 0.5;
  for (let k = 0; k < 9; k++) {
    const o = len(0.12 + rng.u() * 0.5);
    const f0 = 3000 + rng.u() * 3000;
    for (let i = 0; i < len(0.25) && i + o < n; i++) {
      const t = i / SR;
      out[i + o] += Math.sin(TAU * f0 * t) * Math.exp(-t / 0.05) * 0.18;
    }
  }
  return out;
}

// Glitch: a stuttering, bit-crushed burst.
function glitch(rng) {
  const n = len(0.45);
  const out = new Float64Array(n);
  let held = 0;
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * (220 + 1800 * rng.u() * (Math.floor(t * 18) % 2)) / SR;
    if (i % 24 === 0) held = Math.round((Math.sin(p) * 0.6 + rng.n() * 0.3) * 4) / 4; // sample-and-hold + 3-bit crush
    const gate = Math.floor(t * 30) % 3 !== 2 ? 1 : 0;
    out[i] = held * gate * 0.7;
  }
  return out;
}

// Sub drop: a sine sliding down into the floor.
function subDrop() {
  const n = len(1.4);
  const out = new Float64Array(n);
  let p = 0;
  for (let i = 0; i < n; i++) {
    const t = i / SR;
    p += TAU * (95 * Math.exp(-t / 0.5) + 30) / SR;
    out[i] = Math.tanh(1.8 * Math.sin(p)) * Math.min(1, t / 0.005) * Math.exp(-t / 0.9);
  }
  return out;
}

// cue name -> [synth, gain, start offset in seconds]
// (gains balanced so punchline hits land a little above the existing effects and small UI
// sounds a little below, all within about 8 dB)
const MEME = {
  boom: [boom, 0.65, 0], scratch: [scratch, 0.7, 0], horn: [horn, 0.63, 0], rimshot: [rimshot, 0.7, 0],
  fail: [fail, 0.55, 0], drumroll: [drumroll, 1.29, 0], ding: [ding, 0.6, 0], buzzer: [buzzer, 0.5, 0],
  ping: [ping, 0.85, 0], typing: [typing, 1.38, 0], shutter: [shutter, 1.44, 0], cash: [cash, 0.73, 0],
  glitch: [glitch, 0.67, 0], bass: [subDrop, 0.5, 0],
};

// ---------- mixing ----------

class Bus {
  constructor(n) {
    this.L = new Float64Array(n);
    this.R = new Float64Array(n);
  }

  add(sig, t0, gain = 1, pan = 0) {
    const start = Math.round(t0 * SR);
    const gl = gain * Math.sqrt((1 - pan) / 2);
    const gr = gain * Math.sqrt((1 + pan) / 2);
    const n = this.L.length;
    for (let i = Math.max(0, -start); i < sig.length && start + i < n; i++) {
      this.L[start + i] += sig[i] * gl;
      this.R[start + i] += sig[i] * gr;
    }
  }
}

// Freeverb-style room: parallel damped combs into allpasses, spread between channels.
function reverb(L, R, { room = 0.82, damp = 0.35 } = {}) {
  const k = SR / 44100;
  const combs = [1116, 1188, 1277, 1356, 1422, 1491];
  const passes = [556, 441, 341];
  const run = (input, spread) => {
    const out = new Float64Array(input.length);
    for (const d of combs) {
      const size = Math.round((d + spread) * k);
      const buf = new Float64Array(size);
      let idx = 0;
      let store = 0;
      for (let i = 0; i < input.length; i++) {
        const y = buf[idx];
        store = y * (1 - damp) + store * damp;
        buf[idx] = input[i] * 0.015 + store * room;
        out[i] += y;
        idx = idx + 1 === size ? 0 : idx + 1;
      }
    }
    for (const d of passes) {
      const size = Math.round((d + spread) * k);
      const buf = new Float64Array(size);
      let idx = 0;
      for (let i = 0; i < out.length; i++) {
        const b = buf[idx];
        buf[idx] = out[i] + b * 0.5;
        out[i] = b - out[i];
        idx = idx + 1 === size ? 0 : idx + 1;
      }
    }
    return out;
  };
  const mono = new Float64Array(L.length);
  for (let i = 0; i < L.length; i++) mono[i] = (L[i] + R[i]) * 0.5;
  return { L: run(mono, 0), R: run(mono, 23) };
}

// ---------- genres ----------
// Patterns are 16 steps per bar: x is a full hit, o a soft one, . nothing.
// Bass: R root, O root an octave up, F the fifth, - holds, . rests.
// Chords: x starts a chord that lasts until the next x (or the bar's end).
// Progressions are scale degrees (0 = I), one chord per bar; the one that
// best fits the hook is used.

const GENRES = {
  pop: {
    bpm: 118, mode: 'major', motif: '1 3 5 3 | 6 5 3 -', swing: 0,
    progressions: [[0, 4, 5, 3], [5, 3, 0, 4], [0, 5, 3, 4]],
    drums: { kick: 'x.....x.x.......', clap: '....x.......x...', hat: 'x.o.x.o.x.o.x.o.', open: '..............x.' },
    bass: { type: 'saw', pattern: 'R.R.R.R.R.R.R.OR' },
    chords: { sound: 'supersaw', pattern: 'x..x..x...x..x..', size: 3 }, pad: 0.35,
    lead: 'pluck', duck: 0.4, verb: 0.2,
  },
  house: {
    bpm: 124, mode: 'minor', motif: '1 . 3 5 | 4 3 1 -', swing: 0,
    progressions: [[0, 5, 2, 6], [0, 3, 5, 4], [0, 6, 5, 6]],
    drums: { kick: 'x...x...x...x...', clap: '....x.......x...', hat: 'oooooooooooooooo', open: '..x...x...x...x.' },
    bass: { type: 'saw', pattern: '..O...O...O...O.' },
    chords: { sound: 'organ', pattern: '...x..x....x..x.', size: 4 }, pad: 0.2,
    lead: 'pluck', duck: 0.55, verb: 0.16,
  },
  hiphop: {
    bpm: 140, mode: 'minor', motif: '5 . 3 1 | 2 . 1 -', swing: 0,
    progressions: [[0, 5, 3, 4], [0, 3, 5, 6], [0, 0, 5, 4]],
    drums: { kick: 'x......x..x.....', snare: '........x.......', hat: 'x.x.x.x.x.x.x.x.', roll: true },
    bass: { type: '808', pattern: 'R------R--R-----' },
    chords: { sound: 'strings', pattern: 'x...............', size: 3 }, pad: 0,
    lead: 'bell', duck: 0.25, verb: 0.14,
  },
  acoustic: {
    bpm: 100, mode: 'major', motif: '1 2 3 5 | 3 2 1 -', swing: 0.04,
    progressions: [[0, 4, 5, 3], [0, 3, 4, 3], [0, 5, 3, 4]],
    drums: { kick: 'x.......x.......', snap: '....x.......x...', shaker: 'oxoxoxoxoxoxoxox' },
    bass: { type: 'sine', pattern: 'R.......F.......' },
    chords: { sound: 'guitar', pattern: 'x..x..x.x..x..x.', size: 3 }, pad: 0,
    lead: 'harp', duck: 0.15, verb: 0.24,
  },
  cinematic: {
    bpm: 90, mode: 'minor', motif: '1 - 5 4 | 3 - 2 -', swing: 0,
    progressions: [[0, 5, 2, 6], [0, 3, 5, 4], [0, 5, 3, 4]],
    drums: { boom: 'x...............', tom: 'x..x..x...x.x.x.', hat: '' },
    bass: { type: 'sine', pattern: 'R---------------' },
    chords: { sound: 'strings', pattern: 'x...............', size: 3 }, pad: 0,
    lead: 'strings', duck: 0.1, verb: 0.38, impact: true,
  },
  tech: {
    bpm: 112, mode: 'major', motif: '1 5 3 5 | 6 5 3 2', swing: 0,
    progressions: [[0, 4, 5, 3], [3, 0, 4, 5], [0, 3, 5, 4]],
    drums: { kick: 'x...x...x...x...', clap: '....x.......x...', hat: 'oxoxoxoxoxoxoxox' },
    bass: { type: 'sine', pattern: 'R.R.R.R.R.R.R.R.' },
    chords: { sound: 'arp', pattern: 'xxxxxxxxxxxxxxxx', size: 3 }, pad: 0.3,
    lead: 'keys', duck: 0.3, verb: 0.2,
  },
  lofi: {
    bpm: 84, mode: 'minor', motif: '3 . 1 5, | 1 - . .', swing: 0.12,
    progressions: [[0, 5, 2, 6], [5, 3, 0, 4], [0, 3, 6, 2]],
    drums: { kick: 'x......xx.......', snare: '....x.......x...', hat: 'x.o.x.o.x.o.x.oo' },
    bass: { type: 'sine', pattern: 'R......R..R.....' },
    chords: { sound: 'keys', pattern: 'x.......x.......', size: 4 }, pad: 0,
    lead: 'keys', duck: 0.35, verb: 0.2, vinyl: true,
  },
  calm: {
    bpm: 88, mode: 'major', motif: '5 3 2 1 | 2 - 1 -', swing: 0,
    progressions: [[0, 4, 5, 3], [0, 3, 0, 4], [3, 0, 4, 0]],
    drums: { kick: 'x...............', shaker: '..o...o...o...o.' },
    bass: { type: 'sine', pattern: 'R-------F-------' },
    chords: { sound: 'keys', pattern: 'x.......x.......', size: 3 }, pad: 0.45,
    lead: 'bell', duck: 0, verb: 0.32,
  },
  // drift phonk: cowbell plays the hook over a hard, distorted 808 and half-time drums
  phonk: {
    bpm: 140, mode: 'minor', motif: '1 1 3 1 | 4 3 1 5,', swing: 0,
    progressions: [[0, 5, 6, 4], [0, 3, 5, 4], [0, 0, 5, 6]],
    drums: { kick: 'x......x..x.....', clap: '........x.......', hat: 'x.x.x.x.x.x.x.x.', roll: true },
    bass: { type: '808', pattern: 'R------R--R-----', drive: 4 },
    chords: { sound: 'strings', pattern: 'x...............', size: 3 }, pad: 0,
    lead: 'cowbell', duck: 0.3, verb: 0.12,
  },
  // jersey club: the bouncing 3-3-2 kick, stabbed chords, tom fills
  jersey: {
    bpm: 140, mode: 'minor', motif: '1 . 1 3 | 5 . 4 3', swing: 0,
    progressions: [[0, 5, 2, 6], [0, 3, 4, 3], [0, 6, 5, 4]],
    drums: { kick: 'x..x..x.x..x..x.', clap: '....x.......x...', hat: '..o...o...o...o.', open: '......x.......x.' },
    bass: { type: 'saw', pattern: 'R..R..R.R..R..R.' },
    chords: { sound: 'stab', pattern: '..x...x...x..x..', size: 3 }, pad: 0,
    lead: 'pluck', duck: 0.35, verb: 0.12, toms: true,
  },
  // Brazilian funk: the tamborzao groove, sliding 808 under cowbell and stabs
  funk: {
    bpm: 130, mode: 'minor', motif: '1 3 1 . | 5, 1 3 .', swing: 0,
    progressions: [[0, 0, 5, 4], [0, 5, 3, 4], [0, 3, 0, 4]],
    drums: { kick: 'x..x..x...x..x..', clap: '....x.......x..x', hat: 'x.o.x.o.x.o.x.o.' },
    bass: { type: '808', pattern: 'R..R..R...R..R..', drive: 3 },
    chords: { sound: 'stab', pattern: 'x.....x.....x...', size: 3 }, pad: 0,
    lead: 'cowbell', duck: 0.3, verb: 0.1,
  },
};

// Picks the progression whose chords contain the most hook notes on strong beats.
function pickProgression(genre, motif, key) {
  let best = genre.progressions[0];
  let bestScore = -1;
  for (const prog of genre.progressions) {
    let score = 0;
    for (const note of motif.notes) {
      const chord = key.chord(prog[Math.floor(note.start / 4) % prog.length]).map((m) => m % 12);
      const weight = note.start % 2 === 0 ? 2 : 1;
      if (chord.includes(key.midi(note.deg) % 12)) score += weight;
    }
    if (score > bestScore) { best = prog; bestScore = score; }
  }
  return best;
}

// The answer phrase: the hook again, with strong-beat notes nudged onto the chord and the last note resolved to its root.
function answerPhrase(motif, key, chordDegrees) {
  return motif.notes.map((note, i) => {
    const chordRoot = chordDegrees[Math.floor(note.start / 4) % chordDegrees.length];
    const tones = [0, 2, 4].map((k) => chordRoot + k);
    let deg = note.deg;
    const strong = note.start % 2 === 0 || i === motif.notes.length - 1;
    if (i === motif.notes.length - 1) {
      deg = chordRoot + 7 * Math.round((note.deg - chordRoot) / 7);
    } else if (strong && !tones.some((t) => ((t - deg) % 7 + 7) % 7 === 0)) {
      let bestDeg = deg;
      let bestDist = 99;
      for (const t of tones) for (const o of [-7, 0, 7]) {
        const candidate = t + o + 7 * Math.floor(note.deg / 7);
        const dist = Math.abs(key.midi(candidate) - key.midi(note.deg));
        if (dist < bestDist) { bestDist = dist; bestDeg = candidate; }
      }
      deg = bestDeg;
    }
    return { ...note, deg };
  });
}

// ---------- arrangement ----------

function inWindow(t, windows) {
  return windows.some(([a, b]) => t >= a && t < b);
}

function buildMusic(opts, key) {
  const g = opts.genreSpec;
  const n = len(opts.duration);
  const beat = 60 / opts.bpm;
  const bar = 4 * beat;
  const stepDur = beat / 4;
  const drop = opts.drop;
  const end = Math.max(drop, opts.duration - 1.0); // the beat stops; the sonic logo lands here and rings out
  const energy = opts.energy;
  const breaks = opts.breaks;
  const rng = makeRng(opts.seed);
  const motif = opts.motif;
  const progression = opts.progression;

  const drums = new Bus(n);
  const low = new Bus(n);
  const harm = new Bus(n);
  const lead = new Bus(n);
  const send = new Bus(n);
  const kicks = [];

  const stepTime = (b, s) => drop + b * bar + s * stepDur + (s % 2 === 1 ? g.swing * stepDur * 2 : 0);
  const hit = (pattern, s) => (pattern ? pattern[s % pattern.length] : '.');
  const vel = (c) => (c === 'x' ? 1 : c === 'o' ? 0.55 : 0);

  // ---- intro: the chord before the drop, plus a riser into it
  if (drop > 0) {
    const introChord = key.chord(progression[progression.length - 1], 4, 0);
    const pad = strings(rng, introChord, drop, { cutoff: 1000, attack: 0.35 });
    harm.add(pad, 0, 0.35);
    send.add(pad, 0, 0.35);
    if (drop >= 1.5) drums.add(riser(rng, 1.5), drop - 1.5, 0.55);
    if (drop >= 0.5) {
      drums.add(g.impact ? impact(rng) : crash(rng), drop, g.impact ? 0.8 : 0.6);
    }
  }

  // ---- the groove, bar by bar from the drop
  for (let b = 0; drop + b * bar < end - 1e-6; b++) {
    const barStart = drop + b * bar;
    const chordDeg = progression[b % progression.length];
    const broken = inWindow(barStart + bar / 2, breaks);
    const chordNotes = key.chord(chordDeg, g.chords.size, 0);
    const rootMidi = key.midi(chordDeg % 7) - 24;

    // pad under everything (or alone, in a break)
    if (g.pad || broken) {
      const p = strings(rng, key.chord(chordDeg, 4, 0), bar, { cutoff: broken ? 900 : 1600, attack: 0.25 });
      harm.add(p, barStart, (broken ? 0.4 : g.pad) * 0.6);
      send.add(p, barStart, 0.4);
    }

    for (let s = 0; s < 16; s++) {
      const t = stepTime(b, s);
      if (t >= end - 1e-6) break;
      const d = g.drums;
      if (broken) {
        // a break keeps only a soft pulse
        if (s % 4 === 0 && d.hat) drums.add(hat(rng), t, 0.25, 0.2);
        continue;
      }
      const lastBar = b % 4 === 3;
      // drums
      if (vel(hit(d.kick, s))) { drums.add(kick(rng, g === GENRES.house || g === GENRES.tech ? { decay: 0.18 } : {}), t, vel(hit(d.kick, s))); kicks.push(t); }
      if (vel(hit(d.clap, s))) { const c = clap(rng); drums.add(c, t, 0.55 * vel(hit(d.clap, s))); send.add(c, t, 0.15); }
      if (vel(hit(d.snare, s))) { const c = snare(rng); drums.add(c, t, 0.6 * vel(hit(d.snare, s))); send.add(c, t, 0.12); }
      if (vel(hit(d.snap, s))) drums.add(clap(rng), t, 0.3);
      if (d.hat && energy >= 2) {
        let v = vel(hit(d.hat, s));
        if (energy >= 4 && !v) v = 0.35;
        if (v) drums.add(hat(rng), t, 0.32 * v, 0.25);
        if (d.roll && lastBar && s >= 12) { // trap-style hat roll into the next phrase
          for (let r = 1; r < 3; r++) drums.add(hat(rng), t + r * stepDur / 3, 0.18, 0.25);
        }
      }
      if (vel(hit(d.open, s)) && energy >= 3) drums.add(hat(rng, true), t, 0.22, -0.2);
      if (vel(hit(d.shaker, s))) drums.add(shaker(rng), t, 0.35 * vel(hit(d.shaker, s)), 0.3);
      if (vel(hit(d.boom, s))) { drums.add(kick(rng, { pitch: 38, punch: 60, decay: 0.5 }), t, 0.9); kicks.push(t); }
      if (vel(hit(d.tom, s)) && energy >= 2) drums.add(tom(rng, [110, 98, 82][s % 3]), t, 0.45, s % 2 ? 0.3 : -0.3);
      if (g.toms && lastBar && s >= 10 && s % 2 === 0) drums.add(tom(rng, [196, 165, 147, 131][(s - 10) / 2 % 4]), t, 0.45, s % 4 ? 0.3 : -0.3);
      // a small fill closing every fourth bar
      if (lastBar && energy >= 3 && s >= 13 && (d.snare || d.clap)) drums.add(snare(rng, { decay: 0.07 }), t, 0.25 + 0.1 * (s - 13));

      // bass
      const bc = g.bass.pattern[s];
      if (bc && 'ROF'.includes(bc)) {
        let holdSteps = 1;
        while (s + holdSteps < 16 && g.bass.pattern[s + holdSteps] === '-') holdSteps++;
        const m = bc === 'O' ? rootMidi + 12 : bc === 'F' ? rootMidi + 7 : rootMidi;
        const dur = holdSteps * stepDur * (g.bass.type === '808' ? 1 : 0.9);
        const sig = g.bass.type === '808' ? sub808(mtof(m), dur, g.bass.drive) : bass(mtof(m), dur, g.bass.type);
        low.add(sig, t, g.bass.type === '808' ? 0.55 : 0.5);
      }

      // chords
      if (g.chords.pattern[s] === 'x') {
        let next = s + 1;
        while (next < 16 && g.chords.pattern[next] !== 'x') next++;
        const dur = (next - s) * stepDur;
        let sig;
        let gain = 0.3;
        switch (g.chords.sound) {
          case 'supersaw': sig = supersaw(rng, chordNotes, Math.min(dur, beat), { bright: 4200, dark: 700 }); gain = 0.42; break;
          case 'organ': sig = organ(chordNotes, Math.min(dur, beat * 0.6)); gain = 0.18; break;
          case 'strings': sig = strings(rng, key.chord(chordDeg, 4, 0), bar * 0.98, { cutoff: 2000, attack: 0.3 }); gain = 0.3; break;
          case 'keys': {
            sig = new Float64Array(len(dur + 0.3));
            for (const m of key.chord(chordDeg, 4, 0)) { const e = epiano(mtof(m), dur, { index: 1.6, decay: 1.6 }); for (let i = 0; i < sig.length && i < e.length; i++) sig[i] += e[i] / 4; }
            gain = 0.45;
            break;
          }
          case 'guitar': { // a strum: strings a few ms apart, alternating direction
            const strum = key.chord(chordDeg, 3, 0).concat(key.chord(chordDeg, 3, 1).slice(0, 2));
            const order = s % 4 === 0 ? strum : [...strum].reverse();
            sig = new Float64Array(len(dur + 0.5));
            order.forEach((m, k) => {
              const p = pluckString(rng, mtof(m - 12), dur + 0.4, { bright: 0.45, decay: 0.995 });
              const off = len(0.012 * k);
              for (let i = 0; i < p.length && i + off < sig.length; i++) sig[i + off] += p[i] / order.length;
            });
            gain = s % 4 === 0 ? 0.7 : 0.45;
            break;
          }
          case 'arp': { // one chord tone per step, up and down
            const tones = [...chordNotes, chordNotes[0] + 12];
            const seq = [0, 1, 2, 3, 2, 1];
            sig = supersaw(rng, [tones[seq[s % seq.length]] + 12], stepDur * 0.9, { bright: 3800, dark: 900, fall: 0.06, voices: 3 });
            gain = 0.22;
            break;
          }
          case 'stab': sig = supersaw(rng, key.chord(chordDeg, 3, 1), Math.min(dur, beat * 0.4), { bright: 7000, dark: 500, fall: 0.05, voices: 5 }); gain = 0.4; break;
          default: sig = new Float64Array(1);
        }
        harm.add(sig, t, gain, s % 2 ? 0.15 : -0.15);
        send.add(sig, t, gain * 0.5);
      }
    }

    // lead: the hook on the first two bars of every four, the answer on the next two
    if (!broken && b % 2 === 0) {
      const phrase = b % 4 === 0 ? motif.notes : answerPhrase(motif, key, [progression[b % 4], progression[(b + 1) % 4]]);
      const callOnly = energy <= 2 && b % 4 !== 0;
      if (!callOnly) {
        for (const note of phrase) {
          const t = barStart + note.start * beat;
          if (t >= end - 2 * beat) continue; // leave room for the sonic logo
          if (inWindow(t, breaks)) continue; // a phrase that started before a break stops at it
          playLead(lead, send, rng, g.lead, key.midi(note.deg, 1), note.dur * beat, t, energy);
        }
      }
    }
  }

  // ---- outro: the sonic logo. The hook's first notes, then home on the final beat.
  const opening = motif.notes.slice(0, 3);
  const eighth = beat / 2;
  opening.forEach((note, i) => {
    const t = end - (opening.length - i) * eighth;
    if (t > drop) playLead(lead, send, rng, g.lead, key.midi(note.deg, 1), eighth * 0.95, t, energy);
  });
  const homeTop = key.midi(0, 1) + (key.midi(opening[opening.length - 1]?.deg ?? 0, 1) - key.midi(0, 1) > 6 ? 12 : 0);
  playLead(lead, send, rng, g.lead, homeTop, 1.0, end, energy);
  const b1 = bell(mtof(homeTop + 12), 1.0);
  lead.add(b1, end, 0.2);
  send.add(b1, end, 0.3);
  const finalChord = strings(rng, key.chord(0, 4, 0), opts.duration - end, { cutoff: 1800, attack: 0.02 });
  harm.add(finalChord, end, 0.35);
  send.add(finalChord, end, 0.4);
  low.add(g.bass.type === '808' ? sub808(mtof(key.midi(0) - 24), 0.9, g.bass.drive) : bass(mtof(key.midi(0) - 24), 0.9, 'sine'), end, 0.5);
  if (end > drop) {
    drums.add(kick(rng), end, 0.9);
    kicks.push(end);
    drums.add(crash(rng, 1.0), end, 0.5);
  }

  if (g.vinyl) drums.add(vinyl(rng, opts.duration), 0, 1);

  // ---- sidechain: duck the bass and chords under each kick for movement
  if (g.duck) {
    const duck = new Float64Array(n).fill(1);
    const span = len(0.28);
    for (const kt of kicks) {
      const i0 = Math.round(kt * SR);
      for (let i = i0; i < Math.min(n, i0 + span); i++) duck[i] = Math.min(duck[i], 1 - g.duck * Math.exp(-(i - i0) / SR / 0.1));
    }
    for (const bus of [low, harm]) for (let i = 0; i < n; i++) { bus.L[i] *= duck[i]; bus.R[i] *= duck[i]; }
  }

  const wet = reverb(send.L, send.R, { room: 0.84, damp: 0.3 });
  const L = new Float64Array(n);
  const R = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    L[i] = drums.L[i] + low.L[i] + harm.L[i] + lead.L[i] + wet.L[i] * g.verb * 2.2;
    R[i] = drums.R[i] + low.R[i] + harm.R[i] + lead.R[i] + wet.R[i] * g.verb * 2.2;
  }
  return { L, R };
}

function playLead(lead, send, rng, sound, midi, dur, t, energy) {
  let sig;
  let gain;
  switch (sound) {
    case 'pluck': sig = supersaw(rng, [midi], Math.max(dur, 0.12), { bright: 6000, dark: 1400, fall: 0.12, voices: 3, sustain: 0.4 }); gain = 0.34; break;
    case 'bell': sig = epiano(mtof(midi), Math.max(dur, 0.2), { index: 3.5, decay: 0.9, tine: 0.3 }); gain = 0.3; break;
    case 'keys': sig = epiano(mtof(midi), Math.max(dur, 0.2), { index: 2.2, decay: 1.2 }); gain = 0.36; break;
    case 'harp': sig = pluckString(rng, mtof(midi), Math.max(dur, 0.25) + 0.6, { bright: 0.75, decay: 0.997 }); gain = 0.5; break;
    case 'strings': sig = strings(rng, [midi], dur, { cutoff: 2600, attack: 0.12 }); gain = 0.42; break;
    case 'cowbell': sig = cowbell(mtof(midi), Math.max(dur, 0.12)); gain = 0.5; break;
    default: return;
  }
  lead.add(sig, t, gain);
  send.add(sig, t, gain * 0.6);
  if (energy >= 5) { // octave double for the highest energy
    lead.add(sig, t + 0.012, gain * 0.25, 0.4);
  }
}

// ---------- public ----------

/**
 * @param {Array<{sound: string, time: number}>} cues  sound effects to place, from the page's data-sfx
 * @param {{duration: number, music?: string, drop?: number, bpm?: number, key?: string, mode?: string,
 *          energy?: number, motif?: string, breaks?: Array<[number, number]>}} opts
 * @returns {{L: Float64Array, R: Float64Array, silent: boolean}}
 */
function buildSoundtrack(cues, opts) {
  const duration = opts.duration;
  const genreName = opts.music === undefined || opts.music === false ? 'lofi' : opts.music;
  const genreSpec = GENRES[genreName] || null;
  const spec = genreSpec || GENRES.pop;
  const mode = opts.mode === 'minor' || opts.mode === 'major' ? opts.mode : spec.mode;
  const key = new Key(opts.key || 'C', mode);
  let motif;
  try {
    motif = parseMotif(opts.motif || spec.motif);
  } catch {
    motif = parseMotif(spec.motif);
  }
  const drop = Math.max(0, opts.drop || 0);
  const bpm = opts.bpm || spec.bpm;
  const progression = pickProgression(spec, motif, key);
  const beat = 60 / bpm;
  const end = Math.max(drop, duration - 1.0);

  // what's sounding when, for the sound effects to harmonize with
  const chordAt = (t) => {
    if (t >= end) return key.chord(0, 3, 0);
    if (t < drop) return key.chord(progression[progression.length - 1], 3, 0);
    return key.chord(progression[Math.floor((t - drop) / (4 * beat)) % progression.length], 3, 0);
  };

  const n = len(duration);
  let music = { L: new Float64Array(n), R: new Float64Array(n) };
  if (genreSpec) {
    music = buildMusic({
      genreSpec, duration, drop, bpm, energy: Math.min(5, Math.max(1, Math.round(opts.energy || 3))),
      breaks: opts.breaks || [], seed: hashString(`${genreName}|${opts.key}|${mode}|${opts.motif || spec.motif}|${bpm}`),
      motif, progression,
    }, key);
  }

  // sound effects, placed on the page's own cues and kept in the music's key
  const rng = makeRng(hashString(`sfx|${opts.motif || ''}`));
  const sfx = new Bus(n);
  const pent = (mode === 'minor' ? [0, 2, 3, 4, 6] : [0, 1, 2, 4, 5]);
  const tickNotes = Array.from({ length: 10 }, (_, i) => key.midi(pent[i % 5] + 7 * Math.floor(i / 5), 1));
  const sorted = [...cues].sort((a, b) => a.time - b.time);
  let popGroup = 0;
  let lastPop = -Infinity;
  let tickIndex = 0;
  let lastTick = -Infinity;
  let swishCount = 0;
  for (const { sound, time } of sorted) {
    if (sound === 'pop') {
      popGroup = time - lastPop < 0.6 ? popGroup + 1 : 0;
      lastPop = time;
      const tones = chordAt(time).map((m) => m + 12).sort((a, b) => a - b);
      sfx.add(sfxPluck(rng, mtof(tones[popGroup % tones.length] + 12 * Math.floor(popGroup / tones.length))), time + 0.04, 0.5);
      sfx.add(swish(rng, 0.12, 2), time, 0.4);
    } else if (sound === 'tick') {
      tickIndex = time - lastTick < 1.5 ? tickIndex + 1 : 0;
      lastTick = time;
      sfx.add(marimba(mtof(tickNotes[tickIndex % tickNotes.length])), time, 0.45);
    } else if (sound === 'swish') {
      sfx.add(swish(rng), time, 0.55, swishCount++ % 2 ? 0.4 : -0.4);
    } else if (sound === 'whoosh') {
      sfx.add(whoosh(rng), time - 0.1, 0.8);
    } else if (sound === 'click') {
      sfx.add(click(rng), time + 0.02, 0.55);
      sfx.add(click(rng), time + 0.14, 0.28);
    } else if (sound === 'chime') {
      sfx.add(bell(mtof(key.midi(4, 1))), time, 0.3);
      sfx.add(bell(mtof(key.midi(7, 1))), time + 0.09, 0.34);
    } else if (MEME[sound]) {
      const [make, gain, offset] = MEME[sound];
      sfx.add(make(rng), time + offset, gain);
    }
  }

  // Every genre's bed is brought to the same average level (RMS), so it sits under the
  // effects the same way whatever the style; a gentle saturation then rounds off peaks.
  let sumSq = 0;
  for (let i = 0; i < n; i++) sumSq += music.L[i] ** 2 + music.R[i] ** 2;
  const rms = Math.sqrt(sumSq / (2 * n));
  const musicGain = rms > 0 ? MUSIC_RMS / rms : 0;
  const L = new Float64Array(n);
  const R = new Float64Array(n);
  const fadeLen = len(0.3);
  let peak = 0;
  for (let i = 0; i < n; i++) {
    const fade = Math.min(1, (n - i) / fadeLen);
    L[i] = Math.tanh(music.L[i] * musicGain + sfx.L[i]) * fade;
    R[i] = Math.tanh(music.R[i] * musicGain + sfx.R[i]) * fade;
    peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
  }
  if (peak > 0) for (let i = 0; i < n; i++) { L[i] *= 0.89 / peak; R[i] *= 0.89 / peak; }
  return { L, R, silent: peak === 0 };
}

function wavBuffer(L, R) {
  const n = L.length;
  const buf = Buffer.alloc(44 + n * 4);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + n * 4, 4);
  buf.write('WAVEfmt ', 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20); // PCM
  buf.writeUInt16LE(2, 22); // stereo
  buf.writeUInt32LE(SR, 24);
  buf.writeUInt32LE(SR * 4, 28);
  buf.writeUInt16LE(4, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(n * 4, 40);
  const clamp = (v) => Math.max(-32768, Math.min(32767, Math.round(v * 32767)));
  for (let i = 0; i < n; i++) {
    buf.writeInt16LE(clamp(L[i]), 44 + i * 4);
    buf.writeInt16LE(clamp(R[i]), 46 + i * 4);
  }
  return buf;
}

module.exports = { buildSoundtrack, wavBuffer, parseMotif, SOUNDS, GENRES, SAMPLE_RATE: SR };
