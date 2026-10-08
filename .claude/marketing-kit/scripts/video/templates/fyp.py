"""Everyday / FYP templates: the memeable, comment-driven formats that fill most
of a brand's feed (references/fyp-formats.md). build.py imports FYP_TEMPLATES
and builds them with the same shared base and kit as the marketing templates.

The copy is a neutral, playful default for a fictional invoicing app for
freelancers. The short-form-video skill rewrites it in the brand's own voice.
"""

FYP_TEMPLATES = {}


def words(text, start, step=0.22):
    """Word-by-word captions: one <i> per word, each popping in `step` seconds after the last."""
    return " ".join(f'<i style="--in:{start + i * step:.2f}s">{w}</i>' for i, w in enumerate(text.split()))


def attrs(duration, drop, music, bpm, key, mode, energy, motif, extra=""):
    return (f'class="fyp" data-duration="{duration}" data-drop="{drop}" data-music="{music}" data-bpm="{bpm}" '
            f'data-key="{key}" data-mode="{mode}" data-energy="{energy}" data-motif="{motif}"{extra}')


FICTION = """
  Skits are fiction: never use a real person's name, handle, photo, post,
  or messages, and never write a fake review."""

# =================================================================== meme captions

FYP_TEMPLATES["pov.html"] = dict(
    bgs=[(0, 3.4), (3.4, 7.2), (7.2, 10.4), (10.4, 12)],
    g1="#9d498f", g2="#32658f",
    doc="""  Template: POV (references/fyp-formats.md, meme captions). 12 seconds:
  "POV: you..." puts the viewer in a moment they've lived, the turn lands
  on a record scratch, the punchline on a boom, and a soft brand line
  closes it.

  Rewrite the three captions around your audience's own moment, in the
  brand's voice, each under about 12 words. Emoji are optional; drop them
  if brand-voice.md rules them out. A photo or clip of the moment in each
  background slot makes it feel filmed.""",
    body_attrs=attrs(12, 1.5, "hiphop", 140, "A", "minor", 3, "5 . 3 1 | 2 . 1 -", ' data-break="3.4-4.4"'),
    css="",
    body="""
  <!-- 0–3.4s: the setup -->
  <div class="scene center" style="--out:3.2s">
    <div class="sticker now" style="--in:.1s" data-sfx="pop">POV</div>
    <div class="cap now" style="--in:.45s; margin-top: 34px" data-sfx="swish"><span>you finally sent every invoice before Friday</span></div>
    <div class="emoji" style="--in:1.5s; margin-top: 30px">😌</div>
  </div>

  <!-- 3.4–7.2s: the turn -->
  <div class="scene center" style="--out:7.0s">
    <div class="cap dark pop" style="--in:3.45s" data-sfx="scratch"><span>the client, four minutes later:</span></div>
    <div class="cap pop" style="--in:4.4s; margin-top: 26px" data-sfx="ping"><span>"can we pay next month?"</span></div>
    <div class="emoji" style="--in:5.3s; margin-top: 30px">🫠</div>
  </div>

  <!-- 7.2–10.4s: the punchline -->
  <div class="scene center" style="--out:10.2s">
    <div class="hit" style="--hit:7.6s">
      <div class="cap dark pop" style="--in:7.25s" data-sfx="swish"><span>me, with automatic reminders on:</span></div>
      <div class="emoji" style="--in:7.6s; margin-top: 30px" data-sfx="boom">😎</div>
    </div>
  </div>

  <!-- 10.4–12s: soft close -->
  <div class="scene center">
    <div class="cap hl pop" style="--in:10.45s" data-sfx="chime"><span>reminders that send themselves</span></div>
    <div class="small fade" style="--in:10.6s; margin-top: 24px">follow for more freelancer life</div>
  </div>
""")

FYP_TEMPLATES["nobody-me.html"] = dict(
    bgs=[(0, 3.4), (3.4, 8), (8, 10)],
    g1="#65328f", g2="#8f5432",
    doc="""  Template: "nobody: / me:" (references/fyp-formats.md, meme captions).
  10 seconds: the three-line setup builds to the drop, then the oddly
  specific habit plays out, then a comment prompt.

  The joke is a habit your audience will recognize as their own; keep it
  affectionate. Swap the file names for any small escalating ritual
  (tabs, coffee orders, renamed folders).""",
    body_attrs=attrs(10, 3.4, "phonk", 140, "D", "minor", 4, "1 1 3 1 | 4 3 1 5,"),
    css="""
  .fname { display: flex; align-items: center; gap: 18px; background: #fff; color: #121212; border-radius: 26px;
           padding: 24px 34px; font-size: 42px; font-weight: 700; box-shadow: 0 30px 80px rgba(0,0,0,.45); }
  .fname::before { content: '📄'; font-size: 54px; }
""",
    body="""
  <!-- 0–3.4s: the setup, building into the drop -->
  <div class="scene" style="--out:3.2s">
    <div class="cap out left now" style="--in:.1s" data-sfx="pop">nobody:</div>
    <div class="cap out left rise" style="--in:.8s; margin-top: 34px" data-sfx="pop">absolutely no one:</div>
    <div class="cap out left rise" style="--in:1.6s; margin-top: 34px" data-sfx="pop">me at 2am:</div>
  </div>

  <!-- 3.4–8s: the habit, escalating -->
  <div class="scene center" style="--out:7.8s">
    <div class="hit" style="--hit:6.15s">
      <div class="stack">
        <div class="fname swap" style="--in:3.45s; --out:4.3s" data-sfx="typing">invoice.pdf</div>
        <div class="fname swap" style="--in:4.35s; --out:5.2s" data-sfx="typing">invoice_final.pdf</div>
        <div class="fname swap" style="--in:5.25s; --out:6.1s" data-sfx="typing">invoice_final_v2.pdf</div>
        <div class="fname swap" style="--in:6.15s" data-sfx="boom">invoice_FINAL_final_v3.pdf</div>
      </div>
    </div>
    <div class="emoji" style="--in:6.6s; margin-top: 40px">🫠</div>
  </div>

  <!-- 8–10s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:8.05s" data-sfx="pop"><span>be honest: how many versions? 👇</span></div>
  </div>
""")

FYP_TEMPLATES["expectation-reality.html"] = dict(
    bgs=[(0, 10), (10, 12)],
    g1="#32658f", g2="#8f5432",
    doc="""  Template: expectation vs reality (references/fyp-formats.md, meme
  captions). 12 seconds: the expectation pane, then reality slams in on a
  record scratch while the beat drops out, then a comment prompt.

  Keep both panes about the same thing, so the gap is the joke. For real
  photos, put an <img class="bg-media" src="..."> inside each .pane; the
  pane keeps its label and caption on top.""",
    body_attrs=attrs(12, 1.2, "pop", 118, "F", "major", 3, "1 3 5 3 | 6 5 3 -", ' data-break="4.2-5.6"'),
    css="""
  .pane .emoji { font-size: 150px; }
""",
    body="""
  <!-- 0–10s: expectation, then reality -->
  <div class="scene" style="--out:9.8s">
    <div class="split">
      <div class="pane now" style="--in:.1s" data-sfx="swish">
        <div class="sticker light">expectation</div>
        <div class="emoji" style="--in:.6s">😎</div>
        <div class="cap"><span>working for yourself: set your own hours</span></div>
      </div>
      <div class="pane pop" style="--in:4.2s" data-sfx="scratch">
        <div class="sticker">reality</div>
        <div class="emoji" style="--in:4.5s">🫠</div>
        <div class="cap"><span>set your own hours. all of them.</span></div>
      </div>
    </div>
  </div>

  <!-- 10–12s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:10.05s" data-sfx="pop"><span>tag the friend who's living this 👇</span></div>
  </div>
""")

FYP_TEMPLATES["tell-me-without.html"] = dict(
    bgs=[(0, 2.8), (2.8, 10.4), (10.4, 12)],
    g1="#8f5432", g2="#328f70",
    doc="""  Template: "tell me you're a ___ without telling me" (references/
  fyp-formats.md, meme captions). 12 seconds: the prompt, four quick
  answers on the beat, and "your turn".

  Write answers only an insider would get: specific beats general. Four
  is plenty; each one holds about two seconds.""",
    body_attrs=attrs(12, 2.8, "jersey", 140, "G", "minor", 4, "1 . 1 3 | 5 . 4 3"),
    css="",
    body="""
  <!-- 0–2.8s: the prompt -->
  <div class="scene center" style="--out:2.6s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>tell me you're a freelancer</span></div>
    <div class="cap hl pop" style="--in:.8s; margin-top: 18px" data-sfx="pop"><span>without telling me you're a freelancer</span></div>
  </div>

  <!-- 2.8–10.4s: the answers, one at a time -->
  <div class="scene center" style="--out:10.2s">
    <div class="stack">
      <div class="swap" style="--in:2.85s; --out:4.65s" data-sfx="swish">
        <div class="emoji" style="--in:2.85s; margin: 0 auto 20px">📂</div><div class="cap"><span>a folder called "taxes (real)"</span></div></div>
      <div class="swap" style="--in:4.75s; --out:6.55s" data-sfx="swish">
        <div class="emoji" style="--in:4.75s; margin: 0 auto 20px">☕</div><div class="cap"><span>four coffees, zero lunch breaks</span></div></div>
      <div class="swap" style="--in:6.65s; --out:8.45s" data-sfx="swish">
        <div class="emoji" style="--in:6.65s; margin: 0 auto 20px">🗓️</div><div class="cap"><span>"circling back" on a Saturday</span></div></div>
      <div class="swap" style="--in:8.55s; --out:10.1s" data-sfx="swish">
        <div class="emoji" style="--in:8.55s; margin: 0 auto 20px">🛋️</div><div class="cap"><span>my commute: couch to desk</span></div></div>
    </div>
  </div>

  <!-- 10.4–12s: your turn -->
  <div class="scene center">
    <div class="cap pop" style="--in:10.45s" data-sfx="pop"><span>your turn 👇</span></div>
  </div>
""")

FYP_TEMPLATES["makes-sense.html"] = dict(
    bgs=[(0, 12), (12, 14)],
    g1="#32818f", g2="#65328f",
    doc="""  Template: "things that just make sense" (references/fyp-formats.md, meme
  captions). 14 seconds: the title stays up while five small, satisfying
  truths swap in, then "add one".

  Each item should get a nod, not a laugh: small, true, and a little
  smug. The product can be one of the five, never all of them.""",
    body_attrs=attrs(14, 1.2, "lofi", 84, "E", "minor", 2, "3 . 1 5, | 1 - . ."),
    css="",
    body="""
  <!-- 0–12s: the title, with five items swapping in under it -->
  <div class="scene top" style="--out:11.8s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>things that just make sense ✨</span></div>
    <div class="stack" style="flex: 1">
      <div class="swap" style="--in:1.2s; --out:3.1s" data-sfx="ding">
        <div class="emoji" style="--in:1.2s; margin: 0 auto 20px">🧾</div><div class="cap dark"><span>invoices that send themselves</span></div></div>
      <div class="swap" style="--in:3.3s; --out:5.2s" data-sfx="ding">
        <div class="emoji" style="--in:3.3s; margin: 0 auto 20px">🗓️</div><div class="cap dark"><span>no meetings before 10am</span></div></div>
      <div class="swap" style="--in:5.4s; --out:7.3s" data-sfx="ding">
        <div class="emoji" style="--in:5.4s; margin: 0 auto 20px">🗂️</div><div class="cap dark"><span>one tab open. just one.</span></div></div>
      <div class="swap" style="--in:7.5s; --out:9.4s" data-sfx="ding">
        <div class="emoji" style="--in:7.5s; margin: 0 auto 20px">✅</div><div class="cap dark"><span>"done" instead of "will do"</span></div></div>
      <div class="swap" style="--in:9.6s; --out:11.6s" data-sfx="ding">
        <div class="emoji" style="--in:9.6s; margin: 0 auto 20px">💸</div><div class="cap dark"><span>getting paid on day one</span></div></div>
    </div>
  </div>

  <!-- 12–14s: add one -->
  <div class="scene center">
    <div class="cap pop" style="--in:12.05s" data-sfx="pop"><span>add one to the list 👇</span></div>
  </div>
""")

FYP_TEMPLATES["starter-pack.html"] = dict(
    bgs=[(0, 9.5), (9.5, 12)],
    g1="#8f7032", g2="#32498f",
    doc="""  Template: starter pack (references/fyp-formats.md, meme captions). 12
  seconds: the title, six items popping into a grid, then "what's
  missing?".

  Six items, two to four words each; the funniest goes last. For real
  products, put an <img class="bg-media" src="..."> in a .cell in place of
  its emoji.""",
    body_attrs=attrs(12, 1.0, "funk", 130, "C", "minor", 4, "1 3 1 . | 5, 1 3 ."),
    css="",
    body="""
  <!-- 0–9.5s: the pack -->
  <div class="scene top" style="--out:9.3s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>the freelancer starter pack</span></div>
    <div class="grid" style="margin-top: 40px">
      <div class="cell pop" style="--in:1.0s" data-sfx="pop"><div class="e">☕</div>the third coffee</div>
      <div class="cell pop" style="--in:1.6s" data-sfx="pop"><div class="e">🎧</div>noise-cancelling everything</div>
      <div class="cell pop" style="--in:2.2s" data-sfx="pop"><div class="e">🗂️</div>47 open tabs</div>
      <div class="cell pop" style="--in:2.8s" data-sfx="pop"><div class="e">📈</div>a spreadsheet for everything</div>
      <div class="cell pop" style="--in:3.4s" data-sfx="pop"><div class="e">🛋️</div>the "office" (the couch)</div>
      <div class="cell pop" style="--in:4.0s" data-sfx="pop"><div class="e">📞</div>a "quick call" that takes an hour</div>
    </div>
  </div>

  <!-- 9.5–12s: what's missing -->
  <div class="scene center">
    <div class="stamp" style="--in:9.55s" data-sfx="boom">accurate?</div>
    <div class="cap pop" style="--in:10.2s; margin-top: 50px" data-sfx="pop"><span>what's missing? 👇</span></div>
  </div>
""")

# =================================================================== comment bait

FYP_TEMPLATES["tier-list.html"] = dict(
    bgs=[(0, 14), (14, 16)],
    g1="#65328f", g2="#32818f",
    doc="""  Template: tier list (references/fyp-formats.md, comment bait). 16
  seconds: six items, each shown big, then dropped into its tier, then
  "rank it different?".

  A tier list works because people disagree with it, so rank honestly and
  leave one placement that's a little spicy. Each item is a "now ranking"
  card (.swap) and a chip (.item) in its row, 1.2s later.""",
    body_attrs=attrs(16, 1.0, "jersey", 140, "A", "minor", 4, "1 . 1 3 | 5 . 4 3"),
    css="""
  .now { height: 210px; }
  .now .cap { font-size: 72px; }
""",
    body="""
  <!-- 0–14s: the list -->
  <div class="scene top" style="--out:13.8s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>ranking ways to get paid faster</span></div>
    <div class="stack now">
      <div class="cap dark swap" style="--in:1.0s; --out:2.6s" data-sfx="swish"><span>🔔 auto reminders</span></div>
      <div class="cap dark swap" style="--in:3.0s; --out:4.6s" data-sfx="swish"><span>💰 a deposit up front</span></div>
      <div class="cap dark swap" style="--in:5.0s; --out:6.6s" data-sfx="swish"><span>📨 a polite nudge</span></div>
      <div class="cap dark swap" style="--in:7.0s; --out:8.6s" data-sfx="swish"><span>⏳ net 30</span></div>
      <div class="cap dark swap" style="--in:9.0s; --out:10.6s" data-sfx="swish"><span>🐌 net 90</span></div>
      <div class="cap dark swap" style="--in:11.0s; --out:12.6s" data-sfx="swish"><span>📬 "it's in the mail"</span></div>
    </div>
    <div class="tiers">
      <div class="tier s"><b>S</b><div class="items">
        <span class="item pop" style="--in:2.2s" data-sfx="ding">🔔 reminders</span>
        <span class="item pop" style="--in:4.2s" data-sfx="ding">💰 deposits</span></div></div>
      <div class="tier a"><b>A</b><div class="items">
        <span class="item pop" style="--in:6.2s" data-sfx="pop">📨 nudge</span></div></div>
      <div class="tier b"><b>B</b><div class="items">
        <span class="item pop" style="--in:8.2s" data-sfx="pop">⏳ net 30</span></div></div>
      <div class="tier c"><b>C</b><div class="items"></div></div>
      <div class="tier d"><b>D</b><div class="items">
        <span class="item pop" style="--in:10.2s" data-sfx="buzzer">🐌 net 90</span>
        <span class="item pop" style="--in:12.2s" data-sfx="buzzer">📬 the mail</span></div></div>
    </div>
  </div>

  <!-- 14–16s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:14.05s" data-sfx="pop"><span>rank it different? 👇</span></div>
  </div>
""")

FYP_TEMPLATES["this-or-that.html"] = dict(
    bgs=[(0, 11.8), (11.8, 14)],
    g1="#8f3832", g2="#32658f",
    doc="""  Template: this or that (references/fyp-formats.md, comment bait). 14
  seconds: three rounds of two choices with a draining timer each, then
  "comment your picks".

  Pairs should be evenly split, with no right answer and nothing that
  makes either side look bad. The brand's own picks at the end give it a
  personality.""",
    body_attrs=attrs(14, 1.0, "funk", 130, "D", "minor", 4, "1 3 1 . | 5, 1 3 ."),
    css="""
  .round { width: 100%; display: flex; flex-direction: column; gap: 34px; }
  .vs { display: flex; align-items: center; gap: 16px; }
  .round .label { font-size: 40px; }
  .pick { flex: 1; background: #fff; color: #121212; border-radius: 34px; padding: 44px 16px 48px; text-align: center;
          font-size: 50px; font-weight: 800; line-height: 1.15; box-shadow: 0 24px 60px rgba(0,0,0,.35); }
  .pick .e { font-size: 150px; line-height: 1.25; }
  .or { flex: none; width: 104px; height: 104px; border-radius: 50%; background: var(--accent); display: grid; place-items: center;
        font-size: 40px; font-weight: 900; }
""",
    body="""
  <!-- 0–11.8s: three rounds -->
  <div class="scene top" style="--out:11.6s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>this or that: freelancer edition</span></div>
    <div class="stack" style="flex: 1">
      <div class="round swap" style="--in:1.0s; --out:4.4s; --end:4.2s" data-sfx="swish tick:end">
        <div class="label accent">round 1 of 3</div>
        <div class="vs"><div class="pick"><div class="e">🌅</div>early bird</div><div class="or">or</div><div class="pick"><div class="e">🌙</div>night owl</div></div>
        <div class="timerbar" style="--in:1.4s; --for:2.8s"></div>
      </div>
      <div class="round swap" style="--in:4.6s; --out:8.0s; --end:7.8s" data-sfx="swish tick:end">
        <div class="label accent">round 2 of 3</div>
        <div class="vs"><div class="pick"><div class="e">📞</div>a call</div><div class="or">or</div><div class="pick"><div class="e">💬</div>an email</div></div>
        <div class="timerbar" style="--in:5.0s; --for:2.8s"></div>
      </div>
      <div class="round swap" style="--in:8.2s; --out:11.6s; --end:11.4s" data-sfx="swish tick:end">
        <div class="label accent">round 3 of 3</div>
        <div class="vs"><div class="pick"><div class="e">🎶</div>music on</div><div class="or">or</div><div class="pick"><div class="e">🤫</div>total silence</div></div>
        <div class="timerbar" style="--in:8.6s; --for:2.8s"></div>
      </div>
    </div>
  </div>

  <!-- 11.8–14s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:11.85s" data-sfx="pop"><span>comment your 3 picks 👇</span></div>
    <div class="small fade" style="--in:12.4s; margin-top: 24px">ours: night owl, email, music on</div>
  </div>
""")

FYP_TEMPLATES["hot-take.html"] = dict(
    bgs=[(0, 4.8), (4.8, 10), (10, 12)],
    g1="#8f3832", g2="#8f7032",
    doc="""  Template: hot take / unpopular opinion (references/fyp-formats.md,
  comment bait). 12 seconds: the take, a poll that swings back and forth
  and lands on a tie, and "break the tie".

  The take should be about the work, defensible, and something the brand
  actually believes; never about people or groups. The poll is a visual,
  not data: only show percentages from a real poll you ran.""",
    body_attrs=attrs(12, 4.8, "phonk", 140, "E", "minor", 4, "1 1 3 1 | 4 3 1 5,"),
    css="""
  .tug .opt::before { animation: tugA 3s ease-in-out var(--in) both; }
  .tug .opt.alt::before { animation-name: tugB; }
  @keyframes tugA { 0% { width: 0; } 30% { width: 72%; } 55% { width: 38%; } 80% { width: 58%; } 100% { width: 50%; } }
  @keyframes tugB { 0% { width: 0; } 30% { width: 30%; } 55% { width: 64%; } 80% { width: 44%; } 100% { width: 50%; } }
""",
    body="""
  <!-- 0–4.8s: the take -->
  <div class="scene center" style="--out:4.6s">
    <div class="sticker yellow now" style="--in:.1s" data-sfx="horn">unpopular opinion</div>
    <div class="cap now" style="--in:.7s; margin-top: 34px" data-sfx="swish"><span>invoices should go out the day the work ends.</span></div>
    <div class="cap dark pop" style="--in:2.3s; margin-top: 18px" data-sfx="pop"><span>not "at the end of the month."</span></div>
  </div>

  <!-- 4.8–10s: the poll swings, then ties -->
  <div class="scene" style="--out:9.8s">
    <div class="cap pop" style="--in:4.85s" data-sfx="pop"><span>so: agree or disagree?</span></div>
    <div class="poll tug" style="margin-top: 50px; --in:5.4s; --t1:6.3s; --t2:7.05s; --t3:7.8s" data-sfx="tick:t1 tick:t2 tick:t3">
      <div class="opt"><span>👍 agree</span></div>
      <div class="opt alt"><span>👎 disagree</span></div>
    </div>
    <div class="stamp" style="--in:8.5s; margin: 60px auto 0" data-sfx="boom">it's a tie</div>
  </div>

  <!-- 10–12s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:10.05s" data-sfx="pop"><span>break the tie 👇</span></div>
  </div>
""")

FYP_TEMPLATES["flags.html"] = dict(
    bgs=[(0, 5.8), (5.8, 11.6), (11.6, 14)],
    g1="#328f54", g2="#8f3232",
    doc="""  Template: green flags / red flags (references/fyp-formats.md, comment
  bait). 14 seconds: three green flags, three red flags, then "add one".

  Flags are behaviors, never kinds of people. Keep the red flags
  light and widely shared, so the comments fill with "this one" rather
  than with an argument.""",
    body_attrs=attrs(14, 1.0, "pop", 118, "G", "major", 3, "1 3 5 3 | 6 5 3 -"),
    css="""
  .flag { display: flex; gap: 22px; align-items: center; margin-top: 24px; padding: 26px 32px; border-radius: 28px;
          background: rgba(255,255,255,.95); color: #121212; font-size: 44px; font-weight: 700; line-height: 1.2; text-wrap: balance; }
  .flag::before { content: '🟢'; font-size: 50px; flex: none; }
  .flag.red::before { content: '🚩'; }
  .cap.red > span { background: var(--bad); color: #fff; }
""",
    body="""
  <!-- 0–5.8s: green flags -->
  <div class="scene top" style="--out:5.6s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>green flags in a client</span></div>
    <div class="flag slide" style="--in:1.0s" data-sfx="ding">pays the deposit without asking</div>
    <div class="flag slide" style="--in:2.1s" data-sfx="ding">sends all the feedback in one email</div>
    <div class="flag slide" style="--in:3.2s" data-sfx="ding">says "take your time" and means it</div>
  </div>

  <!-- 5.8–11.6s: red flags -->
  <div class="scene top" style="--out:11.4s">
    <div class="cap red pop" style="--in:5.85s" data-sfx="buzzer"><span>red flags</span></div>
    <div class="flag red slide" style="--in:6.8s" data-sfx="pop">"it's just a quick change"</div>
    <div class="flag red slide" style="--in:7.9s" data-sfx="pop">"we can pay you in exposure"</div>
    <div class="flag red slide" style="--in:9.0s" data-sfx="pop">"can you hop on a call? now?"</div>
  </div>

  <!-- 11.6–14s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:11.65s" data-sfx="pop"><span>add one: 🟢 or 🚩? 👇</span></div>
  </div>
""")

FYP_TEMPLATES["quiz.html"] = dict(
    bgs=[(0, 6.8), (6.8, 13.2), (13.2, 15)],
    g1="#32498f", g2="#70328f",
    doc="""  Template: guess it in 3 seconds (references/fyp-formats.md, comment
  bait). 15 seconds: two emoji puzzles, each with a 3-2-1 ring and a ding
  on the answer, then "how many did you get?".

  Puzzles beat trivia: no facts to get wrong. Answers should be phrases
  your audience says every day. Any real trivia must be checked before
  it's posted.""",
    body_attrs=attrs(15, 1.0, "house", 124, "B", "minor", 3, "1 . 3 5 | 4 3 1 -"),
    css="""
  .puzzle { font-size: 150px; line-height: 1.25; letter-spacing: 12px; margin-top: 40px; }
  .answer { height: 290px; margin-top: 40px; }
""",
    body="""
  <!-- 0–6.8s: puzzle 1 -->
  <div class="scene center" style="--out:6.6s">
    <div class="sticker yellow now" style="--in:.1s" data-sfx="pop">guess it in 3 seconds</div>
    <div class="puzzle now" style="--in:.6s" data-sfx="swish">📧 ☝️ 📧</div>
    <div class="cap dark fade" style="--in:1.0s"><span>a phrase every inbox knows</span></div>
    <div class="stack answer">
      <div class="gone" style="--in:1.6s; --out:4.6s">
        <div class="ring" style="--in:1.6s; --t1:2.6s; --t2:3.6s" data-sfx="tick tick:t1 tick:t2"><b></b></div></div>
      <div class="cap hl swap" style="--in:4.7s" data-sfx="ding"><span>"per my last email"</span></div>
    </div>
  </div>

  <!-- 6.8–13.2s: puzzle 2 -->
  <div class="scene center" style="--out:13.0s">
    <div class="sticker yellow pop" style="--in:6.85s" data-sfx="pop">round 2</div>
    <div class="puzzle pop" style="--in:7.3s" data-sfx="swish">⏰ ➡️ 💸</div>
    <div class="cap dark fade" style="--in:7.7s"><span>it gets you paid</span></div>
    <div class="stack answer">
      <div class="gone" style="--in:8.3s; --out:11.3s">
        <div class="ring" style="--in:8.3s; --t1:9.3s; --t2:10.3s" data-sfx="tick tick:t1 tick:t2"><b></b></div></div>
      <div class="cap hl swap" style="--in:11.4s" data-sfx="ding"><span>a payment reminder</span></div>
    </div>
  </div>

  <!-- 13.2–15s: score -->
  <div class="scene center">
    <div class="cap pop" style="--in:13.25s" data-sfx="pop"><span>how many did you get? 👇</span></div>
  </div>
""")

FYP_TEMPLATES["rating.html"] = dict(
    bgs=[(0, 11), (11, 13)],
    g1="#8f5432", g2="#32658f",
    doc="""  Template: rating things (references/fyp-formats.md, comment bait). 13
  seconds: four things, each rated with a stamp, then "what's yours?".

  Rate things, never people or other brands' products. The scores are
  opinions, so make them fun, with one surprise (a low score that lands
  with a buzzer, a top score with a boom).""",
    body_attrs=attrs(13, 1.0, "hiphop", 140, "F", "minor", 3, "5 . 3 1 | 2 . 1 -"),
    css="""
  .mail { width: 100%; background: #fff; color: #121212; border-radius: 34px; padding: 44px 40px; text-align: center;
          font-size: 74px; font-weight: 800; line-height: 1.1; box-shadow: 0 30px 80px rgba(0,0,0,.4); }
  .rate { width: 100%; display: flex; flex-direction: column; align-items: center; gap: 56px; }
""",
    body="""
  <!-- 0–11s: four sign-offs, rated -->
  <div class="scene top" style="--out:10.8s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>rating email sign-offs ✍️</span></div>
    <div class="stack" style="flex: 1">
      <div class="rate swap" style="--in:1.0s; --out:3.3s" data-sfx="swish">
        <div class="mail">Best,</div><div class="stamp" style="--in:1.9s" data-sfx="pop">6/10</div></div>
      <div class="rate swap" style="--in:3.4s; --out:5.7s" data-sfx="swish">
        <div class="mail">Cheers!</div><div class="stamp ok" style="--in:4.3s" data-sfx="ding">8/10</div></div>
      <div class="rate swap" style="--in:5.8s; --out:8.1s" data-sfx="swish">
        <div class="mail">Per my last email,</div><div class="stamp bad" style="--in:6.7s" data-sfx="buzzer">2/10</div></div>
      <div class="rate swap" style="--in:8.2s; --out:10.6s" data-sfx="swish">
        <div class="mail">Sent from my phone</div><div class="stamp ok" style="--in:9.1s" data-sfx="boom">10/10</div></div>
    </div>
  </div>

  <!-- 11–13s: comment prompt -->
  <div class="scene center">
    <div class="cap pop" style="--in:11.05s" data-sfx="pop"><span>what's yours? 👇</span></div>
  </div>
""")

# =================================================================== UI skits

FYP_TEMPLATES["text-chat.html"] = dict(
    bgs=[(0, 12.6), (12.6, 15)],
    g1="#32658f", g2="#65328f",
    doc="""  Template: text-message skit (references/fyp-formats.md, UI skits). 15
  seconds: a fictional chat plays out with typing dots and a punchline,
  then a one-line payoff.""" + FICTION + """
  The chat is a generic design in the brand's accent, not any real app's.
  Keep bubbles to one or two short lines; the lint flags any that spill.""",
    body_attrs=attrs(15, 1.0, "lofi", 84, "C", "minor", 2, "3 . 1 5, | 1 - . ."),
    css="",
    body="""
  <!-- 0–12.6s: the chat -->
  <div class="scene top" style="--out:12.4s">
    <div class="chat now" style="--in:.1s">
      <div class="chat-head"><i class="av">🙂</i><div><b>client</b><small>online</small></div></div>
      <div class="chat-body">
        <div class="msg them"><div class="bub" style="--in:.8s" data-sfx="ping">hey! quick change on the logo</div></div>
        <div class="msg me"><div class="bub" style="--in:2.2s" data-sfx="pop">sure, what's up?</div></div>
        <div class="msg them"><div class="typing" style="--in:2.9s; --out:4.1s"><i></i><i></i><i></i></div>
          <div class="bub" style="--in:4.1s" data-sfx="ping">can you make it bigger</div></div>
        <div class="msg them"><div class="bub" style="--in:5.2s" data-sfx="ping">but also smaller</div></div>
        <div class="msg me"><div class="bub" style="--in:6.8s" data-sfx="pop">bigger… but smaller?</div></div>
        <div class="msg them" style="--rim:9.3s" data-sfx="rimshot:rim"><div class="typing" style="--in:7.5s; --out:8.7s"><i></i><i></i><i></i></div>
          <div class="bub" style="--in:8.7s" data-sfx="ping">exactly 🙏</div></div>
        <div class="msg me"><div class="bub" style="--in:10.4s" data-sfx="pop">on it 🙂</div></div>
      </div>
    </div>
  </div>

  <!-- 12.6–15s: the payoff -->
  <div class="scene center">
    <div class="cap dark pop" style="--in:12.65s" data-sfx="swish"><span>nine rounds later, the logo:</span></div>
    <div class="stamp" style="--in:13.4s; margin-top: 50px" data-sfx="boom">same size</div>
  </div>
""")

FYP_TEMPLATES["notifications.html"] = dict(
    bgs=[(0, 9), (9, 12)],
    g1="#32498f", g2="#8f3832",
    doc="""  Template: lock-screen notifications (references/fyp-formats.md, UI
  skits). 12 seconds: a lock screen fills with escalating notifications,
  then the one notification that makes it all fine.""" + FICTION + """
  App names stay generic (Calendar, Mail, a contact's role); the last
  notification can be the brand's own. Up to four fit on the lock screen.""",
    body_attrs=attrs(12, 2.6, "phonk", 140, "F#", "minor", 3, "1 1 3 1 | 4 3 1 5,"),
    css="",
    body="""
  <!-- 0–9s: the lock screen fills up -->
  <div class="scene top" style="--out:8.8s">
    <div class="lock">
      <div class="clock now" style="--in:.1s">7:02</div>
      <div class="date rise" style="--in:.25s">Monday</div>
      <div class="notifs">
        <div class="notif" style="--in:1.0s" data-sfx="ping"><i class="app">🗓️</i>
          <div><div class="n-head"><span>Calendar</span><time>now</time></div><p>Standup moved to 7:30</p></div></div>
        <div class="notif" style="--in:2.6s" data-sfx="ping"><i class="app">💬</i>
          <div><div class="n-head"><span>Client</span><time>now</time></div><p>quick call?</p></div></div>
        <div class="notif" style="--in:3.9s" data-sfx="ping"><i class="app">💬</i>
          <div><div class="n-head"><span>Client</span><time>now</time></div><p>actually, can it be now?</p></div></div>
        <div class="notif" style="--in:5.2s" data-sfx="ping"><i class="app">📧</i>
          <div><div class="n-head"><span>Mail</span><time>now</time></div><p>Re: Re: Fwd: final_FINAL</p></div></div>
      </div>
    </div>
  </div>

  <!-- 9–12s: the good one -->
  <div class="scene center">
    <div class="cap dark pop" style="--in:9.05s" data-sfx="swish"><span>the only notification I want:</span></div>
    <div class="notif" style="--in:9.8s; align-self: stretch" data-sfx="cash"><i class="app">🧾</i>
      <div><div class="n-head"><span>Invoices</span><time>now</time></div><p>Invoice #1042 was paid ✅</p></div></div>
  </div>
""")

FYP_TEMPLATES["post-card.html"] = dict(
    bgs=[(0, 3), (3, 11), (11, 13)],
    g1="#8f3865", g2="#32658f",
    doc="""  Template: social post skit (references/fyp-formats.md, UI skits). 13
  seconds: "POV" setup, a post whose likes count up while replies roll in,
  and a payoff line.""" + FICTION + """
  The post card is generic, not any real app's design. Likes and replies
  are part of the skit, so keep the POV framing, and never show replies
  praising the product (that reads as a fake review).""",
    body_attrs=attrs(13, 3.0, "pop", 118, "D", "major", 3, "1 3 5 3 | 6 5 3 -"),
    css="",
    body="""
  <!-- 0–3s: the setup -->
  <div class="scene center" style="--out:2.8s">
    <div class="sticker now" style="--in:.1s" data-sfx="pop">POV</div>
    <div class="cap now" style="--in:.5s; margin-top: 30px" data-sfx="swish"><span>you finally raised your rates</span></div>
  </div>

  <!-- 3–11s: the post -->
  <div class="scene top" style="--out:10.8s">
    <div class="post rise" style="--in:3.05s" data-sfx="whoosh">
      <div class="post-head"><i class="av">🦊</i><div><b>you</b><small>just now</small></div></div>
      <div class="post-text">new rates start today. that's the post.</div>
      <div class="post-bar">
        <span style="--like:4.4s" data-sfx="pop:like"><svg class="heart" viewBox="0 0 24 24"><path d="M12 20.3s-7.4-4.5-9.2-9.1C1.5 7.9 3.5 4.6 6.9 4.6c2.1 0 3.6 1.1 5.1 2.9 1.5-1.8 3-2.9 5.1-2.9 3.4 0 5.4 3.3 4.1 6.6-1.8 4.6-9.2 9.1-9.2 9.1z"/></svg><b class="count" style="--in:4.4s; --to:1204; --for:2.4s"></b></span>
        <span><svg viewBox="0 0 24 24"><path d="M4 5.5h16v10H9.5L5.5 19v-3.5H4z" fill="none" stroke="#6a6a74" stroke-width="2.2" stroke-linejoin="round"/></svg><b class="count" style="--in:5.6s; --to:86; --for:2s"></b></span>
      </div>
    </div>
    <div class="reply pop" style="--in:5.8s" data-sfx="ping"><i class="av">🐼</i><div><b>a friend</b><p>proud of you 👏</p></div></div>
    <div class="reply pop" style="--in:7.0s" data-sfx="ping"><i class="av">🐸</i><div><b>another freelancer</b><p>doing this tomorrow</p></div></div>
    <div class="reply pop" style="--in:8.4s; --rim:9.1s" data-sfx="ping rimshot:rim"><i class="av">🙂</i><div><b>a client</b><p>can I still get the old price?</p></div></div>
  </div>

  <!-- 11–13s: the payoff -->
  <div class="scene center">
    <div class="cap hl pop" style="--in:11.05s" data-sfx="chime"><span>your rates. your rules. 💸</span></div>
    <div class="small fade" style="--in:11.5s; margin-top: 24px">follow for more freelancer life</div>
  </div>
""")

FYP_TEMPLATES["loading.html"] = dict(
    bgs=[(0, 7.9), (7.9, 12)],
    g1="#32818f", g2="#8f3832",
    doc="""  Template: loading bar skit (references/fyp-formats.md, UI skits). 12
  seconds: "loading motivation" crawls to 99% and stalls, an error dialog
  pops on a glitch while the beat drops out, then the fix loads it.

  Swap what's loading and the fix for your audience's version. The dialog
  is a generic design, not any real operating system's.""",
    body_attrs=attrs(12, 0.9, "tech", 112, "D", "major", 3, "1 5 3 5 | 6 5 3 2", ' data-break="4.8-6.6"'),
    css="""
  .pctline { margin-top: 18px; font-size: 54px; font-weight: 900; text-align: right; }
  .press { animation: press .3s ease-in-out var(--press) both; }
  @keyframes press { 40% { transform: scale(.92); } }
""",
    body="""
  <!-- 0–7.9s: loading, stalling, error -->
  <div class="scene top" style="--out:7.7s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>monday morning, loading motivation…</span></div>
    <div class="progress" style="--in:.9s; --pct:99; --for:3.6s; margin-top: 60px"></div>
    <div class="pctline fade" style="--in:.9s"><b class="count pct" style="--in:.9s; --to:99; --for:3.6s; --ease:cubic-bezier(.15,.85,.25,1)"></b></div>
    <div class="popup pop" style="--in:4.8s; margin-top: 46px" data-sfx="glitch">
      <div class="e">⚠️</div>
      <b>motivation.exe has stopped responding</b>
      <div class="btns"><span>close</span><span class="press" style="--press:6.9s" data-sfx="click:press">try coffee ☕</span></div>
    </div>
  </div>

  <!-- 7.9–12s: the fix -->
  <div class="scene top">
    <div class="cap pop" style="--in:7.95s" data-sfx="pop"><span>trying coffee ☕</span></div>
    <div class="progress" style="--in:8.5s; --pct:100; --for:1.4s; --ease:cubic-bezier(.5,0,.3,1); margin-top: 60px"></div>
    <div class="pctline fade" style="--in:8.5s"><b class="count pct" style="--in:8.5s; --to:100; --for:1.4s; --ease:cubic-bezier(.5,0,.3,1)"></b></div>
    <div class="stamp ok" style="--in:10.0s; margin: 70px auto 0" data-sfx="ding">loaded ✅</div>
  </div>
""")

# =================================================================== story & everyday

FYP_TEMPLATES["storytime.html"] = dict(
    bgs=[(0, 15.4), (15.4, 18)],
    g1="#65328f", g2="#32818f",
    doc="""  Template: storytime (references/fyp-formats.md, story & everyday). 18
  seconds: a short true story told in word-by-word captions, a "part 1"
  sticker, and a "part 2?" ending that earns the follow.

  Tell a real story (the brand's, or a customer's with permission), in
  short chunks of four to nine words. Each word is an <i> with its own
  --in; build.py's words() spaces them 0.22s apart. A clip of the teller
  or the place in the background slot fits this format best.""",
    body_attrs=attrs(18, 1.0, "lofi", 84, "A", "minor", 2, "3 . 1 5, | 1 - . ."),
    css="""
  .tags { display: flex; gap: 18px; }
""",
    body=f"""
  <!-- 0–15.4s: the story, chunk by chunk -->
  <div class="scene top" style="--out:15.2s">
    <div class="tags"><div class="sticker now" style="--in:.1s" data-sfx="pop">storytime</div>
      <div class="sticker yellow now" style="--in:.3s; rotate: 3deg">part 1</div></div>
    <div class="stack" style="flex: 1">
      <div class="say gone" style="--in:.5s; --out:2.5s">{words("so I once sent an invoice", .5)}</div>
      <div class="say gone" style="--in:2.6s; --out:4.5s">{words("to the wrong client.", 2.6)}</div>
      <div class="say gone" style="--in:4.6s; --out:6.5s">{words("for the wrong amount.", 4.6)}</div>
      <div class="say gone" style="--in:6.6s; --out:9.2s; --ka:7.8s" data-sfx="cash:ka">{words("they paid it in an hour. 😳", 6.6)}</div>
      <div class="say gone" style="--in:9.3s; --out:12.3s">{words("so I sent it back, with the right one.", 9.3)}</div>
      <div class="say gone" style="--in:12.4s; --out:15.0s">{words("they've hired me four times since.", 12.4)}</div>
    </div>
  </div>

  <!-- 15.4–18s: part 2? -->
  <div class="scene center">
    <div class="sticker yellow pop" style="--in:15.45s" data-sfx="pop">part 2?</div>
    <div class="cap pop" style="--in:15.8s; margin-top: 30px" data-sfx="swish"><span>how I never mix them up now</span></div>
    <div class="small fade" style="--in:16.4s; margin-top: 24px">follow so you don't miss it</div>
  </div>
""")

FYP_TEMPLATES["countdown.html"] = dict(
    bgs=[(0, 2), (2, 14.2), (14.2, 16)],
    g1="#8f7032", g2="#32498f",
    doc="""  Template: top-5 countdown (references/fyp-formats.md, story &
  everyday). 16 seconds: the promise, five tips counting down from 5, a
  drumroll into number 1, and "which one first?".

  Every tip must be correct and specific; number 1 is the strongest. A
  "save this" sticker up front is what makes this format get saved.""",
    body_attrs=attrs(16, 2.0, "house", 124, "E", "minor", 3, "1 . 3 5 | 4 3 1 -"),
    css="""
  .tip { width: 100%; display: flex; flex-direction: column; align-items: center; gap: 46px; }
""",
    body="""
  <!-- 0–2s: the promise -->
  <div class="scene center" style="--out:1.9s">
    <div class="sticker yellow now" style="--in:.1s" data-sfx="pop">save this 📌</div>
    <div class="cap now" style="--in:.45s; margin-top: 30px" data-sfx="swish"><span>5 ways to get paid faster</span></div>
  </div>

  <!-- 2–14.2s: 5 to 1 -->
  <div class="scene center" style="--out:14.0s">
    <div class="stack">
      <div class="tip swap" style="--in:2.05s; --out:4.1s"><div class="stamp" style="--in:2.05s" data-sfx="pop">#5</div>
        <div class="cap"><span>send it the day you finish</span></div></div>
      <div class="tip swap" style="--in:4.2s; --out:6.3s"><div class="stamp" style="--in:4.2s" data-sfx="pop">#4</div>
        <div class="cap"><span>ask for a deposit up front</span></div></div>
      <div class="tip swap" style="--in:6.4s; --out:8.5s"><div class="stamp" style="--in:6.4s" data-sfx="pop">#3</div>
        <div class="cap"><span>put the due date in the subject line</span></div></div>
      <div class="tip swap" style="--in:8.6s; --out:11.1s; --roll:10.0s" data-sfx="drumroll:roll"><div class="stamp" style="--in:8.6s" data-sfx="pop">#2</div>
        <div class="cap"><span>make paying one click</span></div></div>
      <div class="tip swap" style="--in:11.55s"><div class="stamp ok" style="--in:11.55s" data-sfx="boom">#1</div>
        <div class="cap hl"><span>turn on automatic reminders</span></div></div>
    </div>
  </div>
  <div class="flash" style="--in:11.55s"></div>

  <!-- 14.2–16s: which first -->
  <div class="scene center">
    <div class="cap pop" style="--in:14.25s" data-sfx="pop"><span>which one are you trying first? 👇</span></div>
  </div>
""")

FYP_TEMPLATES["day-in-life.html"] = dict(
    bgs=[(0, 2.2), (2.2, 4.4), (4.4, 6.6), (6.6, 8.8), (8.8, 11), (11, 13.2), (13.2, 16)],
    g1="#8f7032", g2="#328165",
    doc="""  Template: day in the life (references/fyp-formats.md, story &
  everyday). 16 seconds: a title, five timestamped moments with a camera
  shutter on each, and a question back to the viewer.

  This format needs real footage: put the person's own photo or clip of
  each moment in its background slot (Film, in video-types.md terms).
  Without them it's only text, so offer a shot list instead. Times and
  moments must be true to the person's day.""",
    body_attrs=attrs(16, 2.2, "acoustic", 100, "G", "major", 2, "1 2 3 5 | 3 2 1 -"),
    css="",
    body="""
  <!-- 0–2.2s: title -->
  <div class="scene center" style="--out:2.0s">
    <div class="sticker now" style="--in:.1s" data-sfx="pop">day in my life</div>
    <div class="cap now" style="--in:.45s; margin-top: 30px" data-sfx="swish"><span>freelance designer edition</span></div>
  </div>

  <!-- 2.2–13.2s: five moments -->
  <div class="scene bottom" style="--out:4.2s">
    <div class="sticker light pop" style="--in:2.25s" data-sfx="shutter">7:30am</div>
    <div class="cap left pop" style="--in:2.55s; margin-top: 24px"><span>coffee first, emails second ☕</span></div>
  </div>
  <div class="scene bottom" style="--out:6.4s">
    <div class="sticker light pop" style="--in:4.45s" data-sfx="shutter">9:00am</div>
    <div class="cap left pop" style="--in:4.75s; margin-top: 24px"><span>deep work. phone in the other room.</span></div>
  </div>
  <div class="scene bottom" style="--out:8.6s">
    <div class="sticker light pop" style="--in:6.65s" data-sfx="shutter">12:30pm</div>
    <div class="cap left pop" style="--in:6.95s; margin-top: 24px"><span>lunch away from the desk 🥗</span></div>
  </div>
  <div class="scene bottom" style="--out:10.8s">
    <div class="sticker light pop" style="--in:8.85s" data-sfx="shutter">3:00pm</div>
    <div class="cap left pop" style="--in:9.15s; margin-top: 24px"><span>client call, camera on 🎥</span></div>
  </div>
  <div class="scene bottom" style="--out:13.0s">
    <div class="sticker light pop" style="--in:11.05s" data-sfx="shutter">5:45pm</div>
    <div class="cap left pop" style="--in:11.35s; margin-top: 24px"><span>invoices out. laptop closed. ✅</span></div>
  </div>

  <!-- 13.2–16s: question -->
  <div class="scene center">
    <div class="cap pop" style="--in:13.25s" data-sfx="pop"><span>what does your day look like? 👇</span></div>
  </div>
""")

FYP_TEMPLATES["reveal.html"] = dict(
    bgs=[(0, 3), (3, 4.6), (4.6, 9.2), (9.2, 12)],
    g1="#8f3832", g2="#65328f",
    doc="""  Template: wait-for-it reveal (references/fyp-formats.md, story &
  everyday). 12 seconds: a tease, "wait for it" over a drumroll and a
  filling bar, then a flash, a boom, and the beat dropping on the reveal.

  For a launch, a new feature, a product photo, or news. The reveal has to
  be worth the wait; put a real product shot in its background slot.""",
    body_attrs=attrs(12, 4.6, "cinematic", 90, "D", "minor", 4, "1 - 5 4 | 3 - 2 -"),
    css="""
  .name { font-size: 170px; font-weight: 900; letter-spacing: -6px; line-height: 1.05; }
""",
    body="""
  <!-- 0–3s: the tease -->
  <div class="scene center" style="--out:2.9s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>we've been working on something 👀</span></div>
  </div>

  <!-- 3–4.6s: wait for it -->
  <div class="scene center" style="--out:4.55s">
    <div class="cap out pop" style="--in:3.05s">wait for it…</div>
    <div class="progress" style="--in:3.1s; --for:1.5s; --ease:cubic-bezier(.6,0,.9,.6); width: 640px; margin-top: 60px" data-sfx="drumroll"></div>
  </div>
  <div class="flash" style="--in:4.6s"></div>

  <!-- 4.6–9.2s: the reveal -->
  <div class="scene center" style="--out:9.0s">
    <div class="hit" style="--hit:4.6s">
      <div class="small fade" style="--in:4.6s; text-align: center">introducing</div>
      <div class="name accent pop" style="--in:4.6s" data-sfx="boom">Autopilot</div>
    </div>
    <div class="cap pop" style="--in:5.6s; margin-top: 40px" data-sfx="swish"><span>invoices that send themselves.</span></div>
  </div>

  <!-- 9.2–12s: CTA -->
  <div class="scene center">
    <div class="cap hl pop" style="--in:9.25s" data-sfx="chime"><span>out now 🔗 link in bio</span></div>
  </div>
""")

FYP_TEMPLATES["before-after.html"] = dict(
    bgs=[(0, 9.8), (9.8, 12)],
    g1="#32818f", g2="#8f7032",
    doc="""  Template: before / after (references/fyp-formats.md, story &
  everyday). 12 seconds: the "before" side, a wipe to the "after" side on
  a whoosh, and a question.

  Real images only: for a product, a space, or a customer's result, put
  the actual before and after photos in each .side as
  <img class="bg-media" src="...">. Never use stock, AI, or a mock-up for
  a result. The text-only default works for things anyone can relate to.""",
    body_attrs=attrs(12, 1.0, "house", 124, "C", "minor", 3, "1 . 3 5 | 4 3 1 -", ' data-slides="3.6,9.4,11.8"'),
    css="",
    body="""
  <!-- 0–9.8s: before, wipe, after -->
  <div class="scene top" style="--out:9.6s">
    <div class="cap now" style="--in:.1s" data-sfx="pop"><span>my inbox: monday vs friday</span></div>
    <div class="wipe rise" style="--in:.5s; --at:4.0s; margin-top: 34px" data-sfx="whoosh:at">
      <div class="side"><div class="sticker light">monday</div>
        <div class="emoji" style="--in:.9s">📥</div><div class="big">412 unread</div></div>
      <div class="side"><div class="sticker">friday</div>
        <div class="emoji" style="--in:4.6s">📭</div><div class="big">0 unread</div>
        <div class="small">answer it or archive it.</div></div>
    </div>
  </div>

  <!-- 9.8–12s: question -->
  <div class="scene center">
    <div class="cap pop" style="--in:9.85s" data-sfx="pop"><span>how close are you to zero? 👇</span></div>
  </div>
""")

slide = lambda n, total, t0, t1, text, last=False: f"""
  <!-- {t0}–{t1}s: slide {n} -->
  <div class="scene bottom" style="{'' if last else f'--out:{t1 - 0.15:.2f}s'}">
    <div class="sticker pop" style="--in:{t0 + 0.05:.2f}s" data-sfx="swish">{n}/{total}</div>
    <div class="cap left pop" style="--in:{t0 + 0.3:.2f}s; margin-top: 24px"><span>{text}</span></div>
  </div>"""

FYP_TEMPLATES["slideshow.html"] = dict(
    bgs=[(0, 2.5), (2.5, 5), (5, 7.5), (7.5, 10), (10, 12.5), (12.5, 15), (15, 17.5)],
    g1="#656532", g2="#32658f",
    doc="""  Template: slideshow / photo carousel (references/fyp-formats.md, story
  & everyday). 17.5 seconds: a title slide, five tips one per photo, and
  a question. It doubles as a carousel: `node render.js slideshow.html
  --slides` writes each slide as a 1080x1920 PNG for TikTok photo mode or
  an Instagram carousel.

  One photo per slide in its background slot; the text sits low, over the
  scrim. Keep each tip to one line you could read in a second.""",
    body_attrs=attrs(17.5, 2.5, "acoustic", 100, "D", "major", 2, "1 2 3 5 | 3 2 1 -"),
    css="",
    body=f"""
  <!-- 0–2.5s: title slide -->
  <div class="scene bottom" style="--out:2.35s">
    <div class="sticker yellow now" style="--in:.1s" data-sfx="pop">save this 📌</div>
    <div class="cap left now" style="--in:.4s; margin-top: 24px" data-sfx="swish"><span>5 small habits that make freelancing easier</span></div>
  </div>
{slide(1, 5, 2.5, 5, "send the invoice the day you finish")}
{slide(2, 5, 5, 7.5, "keep one day a week free of meetings")}
{slide(3, 5, 7.5, 10, "keep a folder of your wins")}
{slide(4, 5, 10, 12.5, "price the project, not the hour")}
{slide(5, 5, 12.5, 15, "close the laptop at the same time every day")}

  <!-- 15–17.5s: question -->
  <div class="scene bottom">
    <div class="cap left pop" style="--in:15.05s" data-sfx="pop"><span>which one do you need most? 👇</span></div>
  </div>
""")
