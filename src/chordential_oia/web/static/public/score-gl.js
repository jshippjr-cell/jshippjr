
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
"out vec4 frag;",
"void main(){",
"  float f = clamp((vDepth - uFog.x) / max(1.0, uFog.y - uFog.x), 0.0, 1.0);",
"  vec3 c = mix(uInk, uBg, f*0.30);",
"  c = mix(c, uBg, vTone);",           // per-piece ink weight, keeps it from reading flat
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
var uFog = gl.getUniformLocation(prog,"uFog");
gl.uniform1i(uPie, 0);
gl.uniform3f(uInk, 0.055, 0.043, 0.036);
gl.uniform3f(uBg,  0.878, 0.839, 0.761);

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
var beats = Array.prototype.slice.call(document.querySelectorAll(".beat"));
var cols  = beats.map(function(b){ return b.querySelector(".col"); });
var LABELS = ["scattered","gathering","gathering","converging","converging",
              "closing","closing","assembled"];

// the model is not fully closed until the handoff section reads — the last
// pieces land exactly as "one complete handoff" comes up the screen
var ASSEMBLE_AT = 0.88;

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
    PSTATE[i*4+0]=hx; PSTATE[i*4+1]=hy; PSTATE[i*4+2]=hz;
    PSTATE[i*4+3]=1 + KS[i]*(1-a);
    var o1=(NP+i)*4;
    PSTATE[o1]=AX[i*3]*hs; PSTATE[o1+1]=AX[i*3+1]*hs; PSTATE[o1+2]=AX[i*3+2]*hs;
    PSTATE[o1+3]=Math.cos(ta/2);
    var o2=(NP*2+i)*4;
    PSTATE[o2]=px; PSTATE[o2+1]=py; PSTATE[o2+2]=pz;
    PSTATE[o2+3]=TN[i]*(1-a*0.55);
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
  var fov = 2*Math.atan(halfH/dist);
  perspective(Pm, fov, asp, 60, 9000);
  Pm[8] = shiftX; Pm[9] = shiftY;                // off-axis: shifts, never skews
  var ex = CX + Math.sin(az)*Math.cos(el)*dist;
  var ey = CY - Math.cos(az)*Math.cos(el)*dist;
  var ez = CZ + Math.sin(el)*dist;
  lookAt(Vm, ex,ey,ez, CX,CY,CZ);
  mul(VP, Pm, Vm);
  gl.uniformMatrix4fv(uVP, false, VP);
  gl.uniform2f(uFog, dist-420, dist+760);

  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  for(var d=0; d<DRAWS.length; d++){
    gl.bindVertexArray(DRAWS[d].vao);
    gl.drawElementsInstanced(gl.TRIANGLES, DRAWS[d].count, gl.UNSIGNED_SHORT, 0, DRAWS[d].inst);
  }

  // chrome
  var k = Math.min(1, progress/ASSEMBLE_AT);
  gaugeDot.style.left = (k*100)+"%";
  gaugeLab.textContent = LABELS[Math.min(LABELS.length-1, Math.floor(k*LABELS.length))];
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
  // the read-out has said its piece once the model is assembled. It clears on
  // the closing beat so it never sits under the call to action — keyed to the
  // beat that is actually lit, not to a guessed scroll fraction.
  gauge.style.opacity =
    (progress < 0.02 || best === beats.length - 1) ? 0 : 1;
  // desktop: text left, world right — eased along the scroll itself, so the
  // world drifts out of the column instead of jumping when a section lights
  var sr = shiftRamp*shiftRamp*(3 - 2*shiftRamp);
  wantShift  = asp >= 0.95 ? -0.46*sr : 0;
  wantShiftY = asp <  0.95 ? -0.34 : 0;            // portrait: world above the copy

  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
}

// fetch both, then boot. A failure lands on the same no-WebGL2 path: the words
// below still say everything the picture does.
(function(){
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
