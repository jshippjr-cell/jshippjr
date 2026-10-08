#!/usr/bin/env node
'use strict';
/*
 * Free voiceover: turns a script into one WAV per line with Kokoro, an open-weight
 * text-to-speech model (Apache-2.0) that runs on this machine. No account, no API key,
 * no per-use cost. The files plug straight into render.js (data-voice on each scene).
 *
 * Usage:
 *   node voice.js <script> --out <dir> [--voice am_michael] [--speed 1] [--line 3] [--prefix voice-]
 *   node voice.js --voices                                   # every voice, with its quality grade
 *   node voice.js --audition <dir> "a line" [--voices af_heart,af_bella,am_michael,am_fenrir]
 *                                                           # the same line in several voices, to pick one
 *
 * <script> is a text or Markdown file. Numbered lines ("1. ...") become voice-1.wav,
 * voice-2.wav, ...; with no numbered lines, each paragraph is a line. Anything after the
 * first "## " heading is ignored, so notes can follow the script. Each WAV gets a .json next
 * to it with its sentences' start and end times, which captions.js uses to time captions.
 *
 * One-time setup, from this folder: `npm install kokoro-js` (about 600 MB, mostly the ONNX
 * runtime). The first run also downloads the model (about 90 MB) from Hugging Face and
 * caches it; after that it works offline.
 *
 * These are synthetic stock voices, not clones of anyone. If a platform asks whether a
 * video uses AI-generated audio, say yes.
 */
const fs = require('fs');
const path = require('path');

const MODEL = 'onnx-community/Kokoro-82M-v1.0-ONNX';
const DEFAULT_VOICE = 'af_heart';
const SENTENCE_GAP = 0.12; // seconds of silence between sentences of one line

function fail(message) {
  console.error(message);
  process.exit(2);
}

function parseArgs(argv) {
  const args = { positional: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--voices' && (argv[i + 1] === undefined || argv[i + 1].startsWith('--'))) args.listVoices = true;
    else if (['--out', '--voice', '--speed', '--line', '--prefix', '--audition', '--voices', '--quality'].includes(a)) args[a.slice(2)] = argv[++i];
    else if (a === '-h' || a === '--help') args.help = true;
    else args.positional.push(a);
  }
  return args;
}

// The lines to speak: numbered lines if there are any, otherwise paragraphs.
function parseScript(text) {
  const body = text.split(/\n## /)[0];
  const numbered = [...body.matchAll(/^\s*(\d+)[.)]\s+(.+)$/gm)].map((m) => ({ n: Number(m[1]), text: m[2].trim() }));
  if (numbered.length) return numbered;
  return body.split(/\n\s*\n/).map((p) => p.replace(/^#.*$/gm, '').replace(/\s+/g, ' ').trim()).filter(Boolean)
    .map((t, i) => ({ n: i + 1, text: t }));
}

// 16-bit mono WAV from float samples.
function wav(samples, rate) {
  const buf = Buffer.alloc(44 + samples.length * 2);
  buf.write('RIFF', 0);
  buf.writeUInt32LE(36 + samples.length * 2, 4);
  buf.write('WAVEfmt ', 8);
  buf.writeUInt32LE(16, 16);
  buf.writeUInt16LE(1, 20);
  buf.writeUInt16LE(1, 22);
  buf.writeUInt32LE(rate, 24);
  buf.writeUInt32LE(rate * 2, 28);
  buf.writeUInt16LE(2, 32);
  buf.writeUInt16LE(16, 34);
  buf.write('data', 36);
  buf.writeUInt32LE(samples.length * 2, 40);
  for (let i = 0; i < samples.length; i++) buf.writeInt16LE(Math.round(Math.max(-1, Math.min(1, samples[i])) * 32767), 44 + i * 2);
  return buf;
}

async function loadKokoro() {
  let mod;
  try {
    mod = await import('kokoro-js');
  } catch (e) {
    if (e.code !== 'ERR_MODULE_NOT_FOUND' && e.code !== 'MODULE_NOT_FOUND') throw e;
    fail('The free voice needs kokoro-js. From this folder (scripts/video) run, once:\n  npm install kokoro-js\n(about 600 MB, mostly the ONNX runtime it runs on).');
  }
  return mod.KokoroTTS;
}

// The voice list ships inside kokoro-js, so it's readable without loading the model.
async function voiceList() {
  const KokoroTTS = await loadKokoro();
  return new KokoroTTS(null, null).voices;
}

async function loadModel(quality) {
  const KokoroTTS = await loadKokoro();
  try {
    return await KokoroTTS.from_pretrained(MODEL, { dtype: quality || 'q8', device: 'cpu' });
  } catch (e) {
    fail(`Couldn't load the voice model (${e.message.split('\n')[0]}).\n` +
      'The first run downloads it once (about 90 MB) from huggingface.co and caches it; check the connection, or that huggingface.co is allowed on this network.');
  }
}

// Speaks one line, sentence by sentence (the model handles a few hundred characters at a
// time), with a short pause between sentences. Returns { samples, rate, sentences }, where
// sentences holds each sentence's text and start and end in seconds (captions.js uses them as
// exact boundaries when timing word-by-word captions).
async function speak(tts, text, voice, speed) {
  const chunks = [];
  const texts = [];
  let rate = 24000;
  for await (const { text: said, audio } of tts.stream(text, { voice, speed })) {
    rate = audio.sampling_rate;
    chunks.push(audio.audio);
    texts.push(typeof said === 'string' ? said.trim() : null);
  }
  const gap = Math.round(SENTENCE_GAP * rate);
  const total = chunks.reduce((n, c) => n + c.length, 0) + gap * Math.max(0, chunks.length - 1);
  const samples = new Float32Array(total);
  const sentences = [];
  let at = 0;
  chunks.forEach((c, i) => {
    samples.set(c, at);
    sentences.push({ text: texts[i], start: +(at / rate).toFixed(3), end: +((at + c.length) / rate).toFixed(3) });
    at += c.length + (i < chunks.length - 1 ? gap : 0);
  });
  return { samples, rate, sentences: sentences.every((x) => x.text) ? sentences : [] };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help || (!args.listVoices && !args.audition && !args.positional.length)) {
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^[\s\S]*?\/\*/, '').replace(/^ \* ?/gm, ''));
    process.exit(args.help ? 0 : 2);
  }

  if (args.listVoices) {
    const voices = await voiceList();
    for (const [id, v] of Object.entries(voices)) {
      console.log(`${id.padEnd(14)} ${v.name.padEnd(10)} ${v.language.padEnd(6)} ${v.gender.padEnd(7)} grade ${v.overallGrade}`);
    }
    return;
  }

  const speed = args.speed ? Number(args.speed) : 1;
  if (!(speed > 0.5 && speed < 2)) fail('--speed should be between 0.5 and 2.');

  if (args.audition) {
    const text = args.positional.join(' ').trim();
    if (!text) fail('Give the line to audition, e.g. node voice.js --audition samples "Here is how it works."');
    const ids = (args.voices || 'af_heart,af_bella,am_michael,am_fenrir').split(',').map((v) => v.trim()).filter(Boolean);
    const known = await voiceList();
    for (const id of ids) if (!known[id]) fail(`Unknown voice "${id}"; node voice.js --voices lists them.`);
    const tts = await loadModel(args.quality);
    fs.mkdirSync(args.audition, { recursive: true });
    for (const id of ids) {
      const { samples, rate } = await speak(tts, text, id, speed);
      const file = path.join(args.audition, `${id}.wav`);
      fs.writeFileSync(file, wav(samples, rate));
      console.log(`${file}: ${(samples.length / rate).toFixed(2)}s`);
    }
    return;
  }

  const scriptFile = args.positional[0];
  if (!fs.existsSync(scriptFile)) fail(`No script at ${scriptFile}`);
  if (!args.out) fail('Pass --out <dir> for the voice files (usually the page\'s assets/ folder).');
  const lines = parseScript(fs.readFileSync(scriptFile, 'utf8')).filter((l) => !args.line || l.n === Number(args.line));
  if (!lines.length) fail(args.line ? `No line ${args.line} in ${scriptFile}` : `No lines found in ${scriptFile}`);
  const voice = args.voice || DEFAULT_VOICE;
  if (!(await voiceList())[voice]) fail(`Unknown voice "${voice}"; node voice.js --voices lists them.`);
  const tts = await loadModel(args.quality);
  fs.mkdirSync(args.out, { recursive: true });
  for (const { n, text } of lines) {
    const { samples, rate, sentences } = await speak(tts, text, voice, speed);
    const file = path.join(args.out, `${args.prefix || 'voice-'}${n}.wav`);
    fs.writeFileSync(file, wav(samples, rate));
    // sentence timings for captions.js, next to the clip
    fs.writeFileSync(file.replace(/\.wav$/, '.json'), JSON.stringify({ text, voice, speed, sentences }, null, 2) + '\n');
    console.log(`${file}: ${(samples.length / rate).toFixed(2)}s  ${text.slice(0, 50)}${text.length > 50 ? '...' : ''}`);
  }
}

if (require.main === module) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}

module.exports = { parseScript, wav, speak };
