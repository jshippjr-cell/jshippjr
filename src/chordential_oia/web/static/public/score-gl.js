
function boot(){
"use strict";
var cv = document.getElementById("gl");
var gl = cv.getContext("webgl2", {antialias:true, alpha:false, premultipliedAlpha:false});
if(!gl){ document.getElementById("fail").style.display="grid";
         document.getElementById("stage").style.display="none";
         document.getElementById("gauge").style.display="none";
         document.getElementById("hint").style.display="none";
         document.querySelectorAll(".beat .col").forEach(function(c){c.style.opacity=1;c.style.transform="none";});
         return; }

// ── payload ────────────────────────────────────────────────────────────────
// The scene ships as two cacheable static assets rather than inlined base64:
// 65 KB of JSON and the raw float buffer. The URLs ride on the canvas so this
// file stays a plain static script the browser can cache across deploys.
var META = window.__WORLD_META, BUF = window.__WORLD_BIN;
var NM = META.nMarks, NP = META.nPieces;
var MAT   = new Float32Array(BUF, META.offMarks,  NM*12);
var PIDX  = new Uint16Array (BUF, META.offPidx,   NM);
var HOME  = new Float32Array(BUF, META.offPieces, NP*4);   // cx,cy,cz,span
// …and where every piece goes when the cube becomes the delivery package:
// x,y,z, scale, then the quaternion that turns it onto its edge of the carton.
// Guarded, so a scene built before the package existed still boots.
var PACK  = (META.offPack != null && META.offPack + NP*32 <= BUF.byteLength)
            ? new Float32Array(BUF, META.offPack, NP*8) : null;

// ── gl program ─────────────────────────────────────────────────────────────
var VS = [
"#version 300 es",
"precision highp float;",
"layout(location=0) in vec2 aPos;",
"layout(location=1) in vec4 aM0;",
"layout(location=2) in vec4 aM1;",
"layout(location=3) in vec4 aM2;",
"layout(location=4) in uint aPiece;",
"uniform mat4 uVP;",
"uniform sampler2D uPie;",
"out float vDepth;",
"out float vTone;",
"vec3 qrot(vec4 q, vec3 v){ return v + 2.0*cross(q.xyz, cross(q.xyz,v) + q.w*v); }",
"void main(){",
"  int p = int(aPiece);",
"  vec4 r0 = texelFetch(uPie, ivec2(p,0), 0);",   // centroid.xyz, scale
"  vec4 r1 = texelFetch(uPie, ivec2(p,1), 0);",   // quaternion
"  vec4 r2 = texelFetch(uPie, ivec2(p,2), 0);",   // target centroid.xyz, tone
"  vec3 v  = vec3(aPos, 0.0);",
"  vec3 w  = vec3(dot(aM0.xyz,v)+aM0.w, dot(aM1.xyz,v)+aM1.w, dot(aM2.xyz,v)+aM2.w);",
"  vec3 fin = r2.xyz + qrot(r1, (w - r0.xyz) * r0.w);",
"  vec4 cp = uVP * vec4(fin,1.0);",
"  vDepth = cp.w;",
"  vTone  = r2.w;",
"  gl_Position = cp;",
"}"].join("\n");

var FS = [
"#version 300 es",
"precision highp float;",
"in float vDepth;",
"in float vTone;",
"uniform vec3 uInk;",
"uniform vec3 uBg;",
"uniform vec2 uFog;",
"uniform vec3 uEmber;",
"out vec4 frag;",
"void main(){",
"  float f = clamp((vDepth - uFog.x) / max(1.0, uFog.y - uFog.x), 0.0, 1.0);",
"  vec3 c = mix(uInk, uBg, f*0.30);",
"  if (vTone < 0.0) c = mix(uInk, uEmber, -vTone);",
"  else c = mix(c, uBg, vTone);",           // per-piece ink weight, keeps it from reading flat
"  frag = vec4(c, 1.0);",
"}"].join("\n");

function sh(t,src){ var s=gl.createShader(t); gl.shaderSource(s,src); gl.compileShader(s);
  if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
  return s; }
var prog = gl.createProgram();
gl.attachShader(prog, sh(gl.VERTEX_SHADER,VS));
gl.attachShader(prog, sh(gl.FRAGMENT_SHADER,FS));
gl.linkProgram(prog);
if(!gl.getProgramParameter(prog,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
gl.useProgram(prog);
var uVP  = gl.getUniformLocation(prog,"uVP");
var uPie = gl.getUniformLocation(prog,"uPie");
var uInk = gl.getUniformLocation(prog,"uInk");
var uBg  = gl.getUniformLocation(prog,"uBg");
var uEmber = gl.getUniformLocation(prog,"uEmber");
var uFog = gl.getUniformLocation(prog,"uFog");
gl.uniform1i(uPie, 0);
gl.uniform3f(uInk, 0.055, 0.043, 0.036);
gl.uniform3f(uBg,  0.878, 0.839, 0.761);
gl.uniform3f(uEmber, 0.894, 0.404, 0.122);   // #E4671F

// instance buffers (marks are pre-sorted by prototype, so each proto is one run)
var matBuf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, matBuf);
gl.bufferData(gl.ARRAY_BUFFER, MAT, gl.STATIC_DRAW);
var pieBuf = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, pieBuf);
gl.bufferData(gl.ARRAY_BUFFER, PIDX, gl.STATIC_DRAW);

var DRAWS = [], first = 0;
for(var pi=0; pi<META.protos.length; pi++){
  var n = META.counts[pi];
  if(!n){ continue; }
  var P = META.protos[pi];
  var vao = gl.createVertexArray();
  gl.bindVertexArray(vao);

  var vb = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, vb);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(P.v), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

  var ib = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(P.i), gl.STATIC_DRAW);

  gl.bindBuffer(gl.ARRAY_BUFFER, matBuf);
  for(var r=0;r<3;r++){
    gl.enableVertexAttribArray(1+r);
    gl.vertexAttribPointer(1+r, 4, gl.FLOAT, false, 48, first*48 + r*16);
    gl.vertexAttribDivisor(1+r, 1);
  }
  gl.bindBuffer(gl.ARRAY_BUFFER, pieBuf);
  gl.enableVertexAttribArray(4);
  gl.vertexAttribIPointer(4, 1, gl.UNSIGNED_SHORT, 2, first*2);
  gl.vertexAttribDivisor(4, 1);

  DRAWS.push({vao:vao, count:P.i.length, inst:n});
  first += n;
}
gl.bindVertexArray(null);

// piece-state texture: row0 centroid+scale, row1 quat, row2 target+tone
var PSTATE = new Float32Array(NP*4*3);
var tex = gl.createTexture();
gl.activeTexture(gl.TEXTURE0);
gl.bindTexture(gl.TEXTURE_2D, tex);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA32F, NP, 3, 0, gl.RGBA, gl.FLOAT, null);

// ── per-piece scatter law ──────────────────────────────────────────────────
var seed = 1337;
function rnd(){ seed ^= seed<<13; seed ^= seed>>>17; seed ^= seed<<5; seed>>>=0;
                return seed/4294967296; }

var CX = META.center[0], CY = META.center[1], CZ = META.center[2];
var order = [];
for(var i=0;i<NP;i++) order.push(i);
order.sort(function(a,b){ return HOME[b*4+3] - HOME[a*4+3]; });  // big first

var BD = new Float32Array(NP*3);   // burst direction (unit)
var BR = new Float32Array(NP);     // burst radius
var AX = new Float32Array(NP*3);   // tumble axis
var SP = new Float32Array(NP);     // total tumble angle
var OM = new Float32Array(NP);     // orbital rate
var PH = new Float32Array(NP);     // orbital phase
var IN = new Float32Array(NP);     // orbital inclination
var ST = new Float32Array(NP);     // assembly stagger
var TN = new Float32Array(NP);     // ink tone jitter
var KS = new Float32Array(NP);     // scattered legibility scale

var maxR = 0;
for(var k=0;k<NP;k++){
  var id = order[k], t = k/(NP-1);      // t=0 biggest slab … t=1 smallest mark
  var u = rnd()*2-1, th = rnd()*6.2831853, s = Math.sqrt(1-u*u);
  BD[id*3]=s*Math.cos(th); BD[id*3+1]=u*0.72; BD[id*3+2]=s*Math.sin(th);
  var r = 80 + 640*Math.pow(t,0.70)*(0.55+rnd()*0.85);
  BR[id] = r; if(r>maxR) maxR=r;
  var a=rnd()*2-1, b=rnd()*6.2831853, c=Math.sqrt(1-a*a);
  AX[id*3]=c*Math.cos(b); AX[id*3+1]=a; AX[id*3+2]=c*Math.sin(b);
  SP[id] = (0.8+rnd()*2.6) * 6.2831853 * (rnd()<0.5?-1:1);
  PH[id] = rnd()*6.2831853;
  IN[id] = (rnd()-0.5)*0.55;
  TN[id] = rnd()*0.13;
}
for(var i2=0;i2<NP;i2++){
  OM[i2] = 0.052 * Math.pow(320/(BR[i2]+220), 0.5) * (i2%7===0?-1:1);  // slower further out
  ST[i2] = 0.62 * (BR[i2]/maxR);
  KS[i2] = Math.max(0, Math.min(2.2, 46/(HOME[i2*4+3]+14) - 0.4));
}

// ── the order the package gets packed in ───────────────────────────────────
// A box is built and then filled; it does not arrive all at once. Every piece
// gets a start point in the fold, taken from where it is GOING rather than
// from anything extra in the file: the pieces that draw the carton's outline
// go first, bottom rail to open flap, and the ones that are contents follow,
// lowest layer first. Without this the whole model turns over simultaneously
// and the middle of the fold reads as an explosion rather than as packing.
var PST = new Float32Array(NP);
if(PACK){
  var eLo=1e9,eHi=-1e9,cLo=1e9,cHi=-1e9;
  for(var i3=0;i3<NP;i3++){
    var z3 = PACK[i3*8+2];
    if(PACK[i3*8+3] >= 0.40){ if(z3<eLo)eLo=z3; if(z3>eHi)eHi=z3; }
    else { if(z3<cLo)cLo=z3; if(z3>cHi)cHi=z3; }
  }
  for(var i4=0;i4<NP;i4++){
    var z4 = PACK[i4*8+2];
    PST[i4] = PACK[i4*8+3] >= 0.40
      ? 0.34 * ((z4-eLo)/Math.max(1e-3, eHi-eLo))          // the carton, upward
      : 0.30 + 0.45 * ((z4-cLo)/Math.max(1e-3, cHi-cLo));  // then what is in it
  }
}
// where to look once it is a package: the middle of what the package actually
// occupies, read off the targets rather than written down twice
var PACK_EYE = PACK ? (Math.min(eLo, cLo) + Math.max(eHi, cHi)) / 2 : CZ;

// ── camera ─────────────────────────────────────────────────────────────────
function perspective(out, fovy, asp, n, f){
  var t = 1/Math.tan(fovy/2);
  out[0]=t/asp;out[1]=0;out[2]=0;out[3]=0;
  out[4]=0;out[5]=t;out[6]=0;out[7]=0;
  out[8]=0;out[9]=0;out[10]=(f+n)/(n-f);out[11]=-1;
  out[12]=0;out[13]=0;out[14]=2*f*n/(n-f);out[15]=0;
  return out;
}
// world is engraving-space: +x right, +y depth, +z up (same handedness as the
// Blender build, so the camera angle below is literally the approved r21 angle).
function lookAt(out, ex,ey,ez, cx,cy,cz){
  var zx=ex-cx, zy=ey-cy, zz=ez-cz;
  var l=Math.hypot(zx,zy,zz)||1; zx/=l; zy/=l; zz/=l;
  var xx = -zy, xy = zx, xz = 0;                 // cross(up=(0,0,1), z)
  l = Math.hypot(xx,xy,xz)||1; xx/=l; xy/=l; xz/=l;
  var yx = zy*xz - zz*xy, yy = zz*xx - zx*xz, yz = zx*xy - zy*xx;
  out[0]=xx;out[1]=yx;out[2]=zx;out[3]=0;
  out[4]=xy;out[5]=yy;out[6]=zy;out[7]=0;
  out[8]=xz;out[9]=yz;out[10]=zz;out[11]=0;
  out[12]=-(xx*ex+xy*ey+xz*ez);
  out[13]=-(yx*ex+yy*ey+yz*ez);
  out[14]=-(zx*ex+zy*ey+zz*ez);
  out[15]=1;
  return out;
}
function mul(out,a,b){
  for(var c=0;c<4;c++)for(var r=0;r<4;r++){
    out[c*4+r]=a[0*4+r]*b[c*4+0]+a[1*4+r]*b[c*4+1]+a[2*4+r]*b[c*4+2]+a[3*4+r]*b[c*4+3];
  }
  return out;
}
var Pm=new Float32Array(16), Vm=new Float32Array(16), VP=new Float32Array(16);
var shiftX = 0, wantShift = 0, shiftY = 0, wantShiftY = 0;

// ── frame ──────────────────────────────────────────────────────────────────
// Engraved hairlines are thinner than one CSS pixel at this scale, so the
// backing store is supersampled and the browser downsamples on composite —
// the same trick the offline renders needed to keep staff lines from dropping.
var DPR = Math.min(2.5, (window.devicePixelRatio||1) * 2);
var W=0,H=0;
function resize(){
  var w = Math.round(cv.clientWidth*DPR), h = Math.round(cv.clientHeight*DPR);
  if(w!==W||h!==H){ W=w;H=h; cv.width=w; cv.height=h; gl.viewport(0,0,w,h); }
}
gl.enable(gl.DEPTH_TEST);
gl.disable(gl.CULL_FACE);
gl.clearColor(0.878,0.839,0.761,1);

function ease(x){ return x<0.5 ? 4*x*x*x : 1-Math.pow(-2*x+2,3)/2; }

var gaugeDot = document.querySelector("#gauge i");
var gaugeLab = document.querySelector("#gauge b");
var veil = document.getElementById("veil");
var gauge = document.getElementById("gauge");
var hint = document.getElementById("hint");
// the renderer owns which beat reads from here on; before this the hero is
// visible by default so a slow scene fetch never shows a blank page
document.documentElement.classList.add("lit-managed");
// ── the live notes ────────────────────────────────────────────────────────────
// A handful of pieces carry the ember and can be pressed. This is the page's own
// grammar: interaction owns INK, scroll owns position — a live note never moves,
// it only stops being engraved black. The hotspots are DOM, projected onto the
// piece each frame, so a click target exists without picking against 7,419
// instanced marks.
var LIVE = (function () {
  var want = (window.__SCORE_TRACKS || []).length;
  if (!want) return [];
  // Pick pieces that actually CONTAIN a clef or a notehead. Marks are grouped by
  // prototype (META.counts, in prototype order), and PIDX maps a mark to its
  // piece — so this asks the scene which pieces are musical rather than guessing
  // from a bounding span. Span alone lit a stem and a barline tick: technically a
  // piece of the score, but not a thing anyone would press.
  var names = META.protos.map(function (x) { return x.name; });
  var wanted = ["treble", "bass", "head"];
  var byPiece = {};
  var base = 0;
  for (var pi2 = 0; pi2 < META.counts.length; pi2++) {
    var n = META.counts[pi2];
    if (n && wanted.indexOf(names[pi2]) >= 0) {
      var rank = names[pi2] === "head" ? 1 : 2;      // a clef beats a notehead
      for (var m2 = base; m2 < base + n; m2++) {
        var owner = PIDX[m2];
        if (!byPiece[owner] || byPiece[owner] < rank) byPiece[owner] = rank;
      }
    }
    base += n;
  }
  var cand = Object.keys(byPiece).map(Number);
  // Keep to the UPPER half of the cube. On portrait the world sits above the copy
  // and the copy parks sticky over the lower part of the frame, so a note near the
  // cube's foot is behind the reading column and cannot be seen or pressed. Z is
  // the cube's tall axis (it is twice as tall as it is wide).
  var high = cand.filter(function (i) { return HOME[i * 4 + 2] > CZ; });
  if (high.length >= want * 3) cand = high;
  if (cand.length < want) return [];
  // clefs first, then front-most, so the lit pieces are legible and unobscured
  cand.sort(function (a, b) {
    if (byPiece[b] !== byPiece[a]) return byPiece[b] - byPiece[a];
    return HOME[b * 4 + 2] - HOME[a * 4 + 2];
  });
  // Depth was the wrong axis. It put every lit note in the densest part of the
  // cloud, where an ember glyph reads as a smudge among 700 grey neighbours.
  // Burst radius is the right one: the outer pieces sit alone against cream at the
  // hero, which is where something asking to be pressed has to be.
  cand.sort(function (a, b) { return BR[b] - BR[a]; });
  // Not the outermost — those orbit clean off the frame at the hero and the note
  // is unreachable. A band below the extreme: clear of the dense core, still
  // inside the picture.
  var lo = Math.floor(cand.length * 0.22), hi = Math.floor(cand.length * 0.55);
  var outer = cand.slice(lo, Math.max(hi, lo + want * 4));
  // then spread them around the ring so they do not stack in one vertical line
  outer.sort(function (a, b) {
    return Math.atan2(BD[a*3+1], BD[a*3]) - Math.atan2(BD[b*3+1], BD[b*3]);
  });
  // Spread them where they END UP as well as where they start. The scattered
  // cloud is 800 units across and the packed carton is 300, so four notes that
  // sit comfortably apart on the cube can arrive within 20px of each other on
  // the carton floor — and a 112px hit target on top of another one means the
  // note underneath cannot be pressed at all. This is the last thing on the
  // page that plays music; it does not get to be unreachable.
  function packAt(i) {
    return PACK ? [PACK[i*8], PACK[i*8+1], PACK[i*8+2]]
                : [HOME[i*4], HOME[i*4+1], HOME[i*4+2]];
  }
  function clearOf(c, chosen, sep) {
    var p = packAt(c);
    for (var j = 0; j < chosen.length; j++) {
      var q = packAt(chosen[j]);
      if (Math.hypot(p[0]-q[0], p[1]-q[1], p[2]-q[2]) < sep) return false;
    }
    return true;
  }
  var picked = [];
  for (var sep = 96; sep > 1; sep *= 0.55) {
    picked = [];
    for (var k = 0; k < want; k++) {
      // the even spacing round the ring stays the intent; separation only
      // decides which neighbour of that position gets taken
      var start = Math.floor(k * outer.length / want);
      for (var off = 0; off < outer.length; off++) {
        var c = outer[(start + off) % outer.length];
        if (picked.indexOf(c) < 0 && clearOf(c, picked, sep)) { picked.push(c); break; }
      }
    }
    if (picked.length === want) break;
  }
  return picked;
})();
// Where the lit notes go once it is a package. The scattered cloud is 800
// units across and the carton is 300, so four notes that sit comfortably apart
// on the cube arrive within 25px of each other on a phone — four 112px hit
// targets do not fit in a box that size, and the one underneath cannot be
// pressed at all. In the package they take its four upper corners instead: as
// far apart as the object allows, on the silhouette where they read. This is
// the last thing on the page that plays music and it does not get to be
// unreachable.
var LIVESLOT = new Int32Array(NP).fill(-1);
var LIVEPACK = null;
if (PACK && META.carton && LIVE.length) {
  var cw = META.carton[0] / 2 - 34, cd = META.carton[1] / 2 - 30;
  var ch = CZ + META.carton[2] * 0.16;
  // Two of the four corners lie almost on top of each other from this angle —
  // the near and far corners of a box seen three-quarters on differ in depth,
  // which the camera mostly foreshortens away. So those two are also given
  // different heights, which does not foreshorten at all.
  var CORN = [[-cw, -cd, 0], [cw, -cd, -48], [cw, cd, 0], [-cw, cd, 52]];
  LIVEPACK = LIVE.map(function (pieceIndex, l) {
    LIVESLOT[pieceIndex] = l;
    var c = CORN[l % 4];
    return [c[0], c[1], ch + c[2]];
  });
}
var LIVE_PACK_SCALE = 0.62;      // legible as notation, not as a speck

var liveEls = [];
(function () {
  var layer = document.getElementById("livelayer");
  if (!layer) return;
  LIVE.forEach(function (pieceIndex, k) {
    var t = window.__SCORE_TRACKS[k];
    var el = document.createElement("button");
    el.type = "button";
    el.className = "livenote";
    el.setAttribute("aria-label", "Hear " + t.title);
    el.dataset.track = String(k);
    // three rings on one cycle, staggered: a radar sweep rather than a blink
    el.innerHTML = '<i class="r1"></i><i class="r2"></i><i class="r3"></i>'
                 + '<b class="core"></b>';
    layer.appendChild(el);
    liveEls.push(el);
  });
})();

var beats = Array.prototype.slice.call(document.querySelectorAll(".beat"));
var cols  = beats.map(function(b){ return b.querySelector(".col"); });
var LABELS = ["scattered","gathering","gathering","converging","converging",
              "closing","closing","assembled"];

// The arc of the world, in scroll fraction. Measured against where the beats
// actually sit — beat 06, "one complete handoff", reads from about 0.77 to
// 0.95 on desktop and 0.70 to 0.86 on portrait, so everything the last act has
// to say happens inside the narrower of the two.
//
//   …0.68  the cube closes, as the handoff section comes up
//   0.705  the notes ignite, one after another, on the closed cube
//   0.80   the cube folds down into the delivery package
//   0.965  sealed, as the call to action arrives
var ASSEMBLE_AT = 0.68;
var PACK_FROM = 0.80, PACK_TO = 0.965;

var progress = 0, target = 0, shiftRamp = 0;
function onScroll(){
  var max = document.documentElement.scrollHeight - window.innerHeight;
  target = max>0 ? Math.min(1, Math.max(0, window.scrollY/max)) : 0;
  // the world clears the reading column as the hero leaves, as a continuous
  // function of the wheel — not a step the moment a new section takes over
  var vh = window.innerHeight || 1;
  shiftRamp = Math.min(1, Math.max(0, (window.scrollY - vh*0.10) / (vh*0.80)));
}
window.addEventListener("scroll", onScroll, {passive:true});
window.addEventListener("resize", onScroll);
onScroll();

var t0 = performance.now();
function draw(now){
  resize();
  var time = (now - t0)/1000;
  progress += (target - progress) * 0.10;

  // pieces reassemble across the scroll, landing on the handoff section
  var p = Math.min(1, progress/ASSEMBLE_AT);
  // …and then the cube folds down into the package it has been describing.
  // Every piece is still on screen: 80 of them lay themselves along the
  // carton's edges, so its outline is literally staff paper, and the other 648
  // stack flat inside it. One delivery, nothing missing — which is what the
  // words beside this say, so the picture says it too.
  var mk = PACK ? Math.min(1, Math.max(0,
             (progress - PACK_FROM) / (PACK_TO - PACK_FROM))) : 0;
  var m = ease(mk);

  for(var i=0;i<NP;i++){
    var e = ST[i] >= 1 ? 1 : Math.min(1, Math.max(0, (p - ST[i])/(1 - ST[i])));
    var a = ease(e);
    var hx = HOME[i*4], hy = HOME[i*4+1], hz = HOME[i*4+2];

    // scattered position: every piece on its own slow orbit about the cube's
    // centre, revolving in the horizontal (x,y) plane and breathing in z.
    var ang = PH[i] + OM[i]*time;
    var ca = Math.cos(ang), sa = Math.sin(ang);
    var dx = BD[i*3], dy = BD[i*3+1], dz = BD[i*3+2];
    var ox = dx*ca - dy*sa, oy = dx*sa + dy*ca;
    var oz = dz + Math.sin(ang*0.83 + PH[i])*IN[i];
    var r  = BR[i];
    // the cube is twice as tall as it is wide, so the cloud is too
    var sx = CX + ox*r, sy = CY + oy*r, sz = CZ + oz*r*1.35;

    var px = sx + (hx-sx)*a, py = sy + (hy-sy)*a, pz = sz + (hz-sz)*a;

    var ta = SP[i]*(1-a);
    var hs = Math.sin(ta/2);
    var sc = 1 + KS[i]*(1-a);
    var qx = AX[i*3]*hs, qy = AX[i*3+1]*hs, qz = AX[i*3+2]*hs, qw = Math.cos(ta/2);

    if(mk > 0 && mk > PST[i]){
      var b8 = i*8;
      var mm = ease((mk - PST[i]) / (1 - PST[i]));
      var slot = LIVESLOT[i];
      var tx = slot >= 0 ? LIVEPACK[slot][0] : PACK[b8];
      var ty = slot >= 0 ? LIVEPACK[slot][1] : PACK[b8+1];
      var tz = slot >= 0 ? LIVEPACK[slot][2] : PACK[b8+2];
      px += (tx - px) * mm;
      py += (ty - py) * mm;
      pz += (tz - pz) * mm;
      sc += ((slot >= 0 ? LIVE_PACK_SCALE : PACK[b8+3]) - sc) * mm;
      // The turn onto the carton is a real rotation, often most of a half
      // turn, so it slerps rather than lerps — a straight blend of two
      // quaternions crosses through the middle and the piece visibly shrinks
      // and swells on its way round. By now the tumble has run out (the cube
      // closed at 0.68), so this rotates from rest, and a rotation from rest
      // is just the same axis at a fraction of the angle.
      var th = Math.acos(Math.min(1, Math.max(-1, PACK[b8+7])));
      var sn = Math.sin(th);
      if(sn > 1e-5){
        var f = Math.sin(th*mm)/sn;
        qx = PACK[b8+4]*f; qy = PACK[b8+5]*f; qz = PACK[b8+6]*f;
        qw = Math.cos(th*mm);
      }
    }

    PSTATE[i*4+0]=hx; PSTATE[i*4+1]=hy; PSTATE[i*4+2]=hz;
    PSTATE[i*4+3]=sc;
    var o1=(NP+i)*4;
    PSTATE[o1]=qx; PSTATE[o1+1]=qy; PSTATE[o1+2]=qz; PSTATE[o1+3]=qw;
    var o2=(NP*2+i)*4;
    PSTATE[o2]=px; PSTATE[o2+1]=py; PSTATE[o2+2]=pz;
    PSTATE[o2+3]=TN[i]*(1-a*0.55);
  }
  // live pieces take the ember. Negative tone is the sentinel the shader reads;
  // the slight breathe is state, not decoration — it says "this one answers".
  // The notes wake AFTER the cube closes. Lit from the hero they competed with
  // the convergence the whole page is built around; lit at the end they are the
  // reward for having watched it land.
  // Each note IGNITES rather than appearing: the ember rises as its piece settles
  // into place, one after another, so they arrive with the cube instead of being
  // switched on after it. `kOf` is that per-note ramp, 0 -> 1.
  // Tuned against the measured ramp: the last note used to still be at 44% when the
  // visitor hit the bottom of the page, which reads as unfinished rather than as
  // arriving. Ignition starts just past the cube's landing and the fourth note is
  // fully lit by ~0.76 — before the package starts folding at 0.80, so the notes
  // arrive on a finished cube and then ride their own pieces into the carton.
  var IGN_FROM = 0.705, IGN_SPAN = 0.032, IGN_STAGGER = 0.009;
  function kOf(idx) {
    var a0 = IGN_FROM + idx * IGN_STAGGER;
    return Math.max(0, Math.min(1, (progress - a0) / IGN_SPAN));
  }
  var liveOn = progress > IGN_FROM;
  if (LIVE.length && liveOn) {
    var pulse = 0.92 + 0.08 * Math.sin(time * 1.8);
    for (var L = 0; L < LIVE.length; L++) {
      var li = LIVE[L];
      var kk = ease(kOf(L));
      if (kk <= 0) continue;
      // cross the normal engraved tone into the ember rather than replacing it
      var normal = TN[li] * (1 - ease(ST[li] >= 1 ? 1 : Math.min(1, Math.max(0,
                     (p - ST[li]) / (1 - ST[li])))) * 0.55);
      PSTATE[(NP * 2 + li) * 4 + 3] = normal * (1 - kk) + (-pulse) * kk;
      // and bigger than their neighbours while scattered, easing back to true size
      // as the cube closes — the same rule the whole scene follows. This MULTIPLIES
      // what the loop above wrote rather than replacing it, so a lit note packs
      // into the carton with everything else instead of staying cube-sized while
      // the world around it folds.
      var la = ease(ST[li] >= 1 ? 1 : Math.min(1, Math.max(0, (p - ST[li]) / (1 - ST[li]))));
      PSTATE[li * 4 + 3] *= (1 + 1.4 * (1 - la));
    }
  }
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texSubImage2D(gl.TEXTURE_2D,0,0,0,NP,3,gl.RGBA,gl.FLOAT,PSTATE);

  // camera: settles onto the approved three-quarter angle as the cube closes
  var az = 0.785 + (1-p)*0.55 + time*0.017;
  var el = 0.235 + (1-p)*0.10;
  var dist = 1000 + 1050*p;
  var asp = W/Math.max(1,H);
  shiftX += (wantShift - shiftX) * 0.07;
  shiftY += (wantShiftY - shiftY) * 0.07;
  var halfH = 380 + 52*p;                       // half-height of what we frame
  if(asp < 1.0) halfH = halfH/Math.max(0.62, asp);
  // The package needs its own framing: half the cube's height, but half again
  // as wide across its open flaps. Closing in by a fixed amount put the flaps
  // off both sides of a phone — so the pull-in is driven by the aspect, and
  // the wider the frame the closer the camera comes.
  halfH += (Math.max(330, 340/Math.max(0.30, asp)) - halfH) * m;
  var fov = 2*Math.atan(halfH/dist);
  perspective(Pm, fov, asp, 60, 9000);
  Pm[8] = shiftX; Pm[9] = shiftY;                // off-axis: shifts, never skews
  // the package is not centred where the cube was — it stands in the cube's
  // lower half with its flaps reaching up, so the eye line rises as it folds
  var lz = CZ + (PACK_EYE - CZ)*m;
  var ex = CX + Math.sin(az)*Math.cos(el)*dist;
  var ey = CY - Math.cos(az)*Math.cos(el)*dist;
  var ez = lz + Math.sin(el)*dist;
  lookAt(Vm, ex,ey,ez, CX,CY,lz);
  mul(VP, Pm, Vm);
  gl.uniformMatrix4fv(uVP, false, VP);
  gl.uniform2f(uFog, dist-420, dist+760);

  // project each live piece into screen space with the SAME matrix the scene is
  // drawn with, so the target sits exactly on the note however the world drifts
  for (var q = 0; q < liveEls.length; q++) {
    var kq = liveOn ? ease(kOf(q)) : 0;
    if (kq <= 0.001) { liveEls[q].style.display = "none"; continue; }
    liveEls[q].style.opacity = kq;
    var pi = LIVE[q];
    // the piece's CURRENT position, not its home. Until the cube closes a piece is
    // out on its own orbit, so projecting HOME put the target on empty paper and
    // left the lit glyph somewhere else on screen entirely.
    var o2p = (NP*2 + pi) * 4;
    var wx = PSTATE[o2p], wy = PSTATE[o2p+1], wz = PSTATE[o2p+2];
    var cx4 = VP[0]*wx + VP[4]*wy + VP[8]*wz  + VP[12];
    var cy4 = VP[1]*wx + VP[5]*wy + VP[9]*wz  + VP[13];
    var cw4 = VP[3]*wx + VP[7]*wy + VP[11]*wz + VP[15];
    var el = liveEls[q];
    if (cw4 <= 0) { el.style.display = "none"; continue; }
    var sx = (cx4 / cw4 * 0.5 + 0.5) * cv.clientWidth;
    var sy = (1 - (cy4 / cw4 * 0.5 + 0.5)) * cv.clientHeight;
    el.style.display = "block";
    el.style.left = sx + "px";
    el.style.top  = sy + "px";
  }

  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  for(var d=0; d<DRAWS.length; d++){
    gl.bindVertexArray(DRAWS[d].vao);
    gl.drawElementsInstanced(gl.TRIANGLES, DRAWS[d].count, gl.UNSIGNED_SHORT, 0, DRAWS[d].inst);
  }

  // chrome. The read-out reports the SAME two scalars the world is drawn from —
  // the cube closing, then the package folding — rather than running a timeline
  // of its own. Two surfaces answering "how far along is this?" is how they come
  // to disagree on a day nobody is looking.
  var k = Math.min(1, progress/ASSEMBLE_AT);
  gaugeDot.style.left = ((k*0.66 + mk*0.34)*100)+"%";
  gaugeLab.textContent = mk > 0
    ? (mk >= 0.995 ? "delivered" : "packing")
    : LABELS[Math.min(LABELS.length-1, Math.floor(k*LABELS.length))];
  hint.style.opacity  = progress < 0.02 ? 1 : 0;

  // exactly one beat reads at a time: the one nearest the reading line. Two
  // lit at once is what made the copy collide with itself on portrait.
  var vh = window.innerHeight, want = 0;
  var anchor = vh * (asp >= 0.95 ? 0.50 : 0.66);
  var best = -1, bestD = 1e9;
  for(var b=0;b<beats.length;b++){
    var rc = cols[b].getBoundingClientRect();
    if(rc.bottom < 0 || rc.top > vh) continue;
    var d = Math.abs((rc.top + rc.bottom)/2 - anchor);
    if(d < bestD){ bestD = d; best = b; }
  }
  for(var b2=0;b2<beats.length;b2++){
    var on = (b2 === best);
    beats[b2].classList.toggle("lit", on);
    if(on && beats[b2].dataset.veil === "1") want = 1;
  }
  veil.classList.toggle("on", !!want);
  // The package list is a third reporter of the assembly scalar, beside the cube
  // and the gauge — it writes itself as the model closes rather than running a
  // timeline of its own. Two surfaces answering "is it delivered?" is how they
  // come to disagree on a day nobody is looking.
  for(var b3=0;b3<beats.length;b3++){
    if(beats[b3].querySelector(".pack"))
      beats[b3].classList.toggle("packed",
        mk > 0.10 && beats[b3].classList.contains("lit"));
  }
  // the read-out has said its piece once the model is assembled. It clears on
  // the closing beat so it never sits under the call to action — keyed to the
  // beat that is actually lit, not to a guessed scroll fraction.
  // The read-out is fixed in the copy column's own gutter, so a tall beat scrolls
  // its last lines underneath it. On the beats where the visitor is doing something
  // rather than reading — listening, leaving a note — it steps aside; the assembly
  // state is not what they are attending to there.
  var quiet = best >= 0 && beats[best].dataset.quiet === "1";
  gauge.style.opacity =
    (progress < 0.02 || quiet || best === beats.length - 1) ? 0 : 1;
  // desktop: text left, world right — eased along the scroll itself, so the
  // world drifts out of the column instead of jumping when a section lights
  var sr = shiftRamp*shiftRamp*(3 - 2*shiftRamp);
  // …and it sits back toward the middle as it packs: at full shift the open
  // flap on the far side ran off the right edge of a 1440 frame.
  wantShift  = asp >= 0.95 ? -0.46*sr*(1 - 0.15*m) : 0;
  // portrait: world above the copy — and a little higher again once it is a
  // package, whose open flaps stand taller off its centre than the cube did
  wantShiftY = asp <  0.95 ? -0.34 - 0.12*m : 0;

  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
}

// fetch both, then boot. A failure lands on the same no-WebGL2 path: the words
// below still say everything the picture does.
(function(){
  // The artifact build inlines the scene and sets these before this file loads,
  // because a published single-file page has no origin to fetch from. Same
  // renderer, same scene, one less round trip.
  if (window.__WORLD_META && window.__WORLD_BIN) { boot(); return; }
  var cv = document.getElementById("gl");
  var m = cv.getAttribute("data-meta"), b = cv.getAttribute("data-bin");
  Promise.all([
    fetch(m).then(function(r){ if(!r.ok) throw 0; return r.json(); }),
    fetch(b).then(function(r){ if(!r.ok) throw 0; return r.arrayBuffer(); })
  ]).then(function(v){
    window.__WORLD_META = v[0]; window.__WORLD_BIN = v[1];
    boot();
  }).catch(function(){
    document.getElementById("fail").style.display = "grid";
    document.getElementById("stage").style.display = "none";
    document.getElementById("gauge").style.display = "none";
    document.getElementById("hint").style.display = "none";
    document.querySelectorAll(".beat .col").forEach(function(c){
      c.style.opacity = 1; c.style.transform = "none"; });
  });
})();
