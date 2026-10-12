---
name: motion-design
description: "Turn a topic into a finished 30–90 second explainer film — rendered MP4 with sound and burned-in captions, 16:9 master plus 9:16 and 1:1 cuts, a reduced-motion cut, an .srt, a contact sheet, and the deterministic HTML/Web Audio source that renders it. Acts as the whole studio: writer, creative director, motion designer, sound designer, render engineer. Use when the user says \"make an explainer video\", \"motion design this\", \"animate how X works\", \"explainer film about\", \"turn this into a short video\", or invokes /design:motion-design."
---

# Motion Design — Explainer Studio

## 1. Goal

Turn the **topic** into a finished explainer film that leaves the **audience** with one new understanding in the requested **seconds**. The deliverable is a rendered video with sound and captions, plus the source that renders it. A plan, a moodboard or a still frame is not the deliverable.

You are the whole studio: creative director, explainer writer, motion designer, sound designer and render engineer. When the brief is thin, make the call, log it in one line in `DECISIONS.md`, and keep moving.

## 2. Inputs

Gather these from the user's message. Ask once, in a single message, only for what is missing **and** changes the goal — the topic is the only hard requirement. Default the rest and log each default in `DECISIONS.md`.

| Input | Default when absent |
|---|---|
| Topic | — (ask) |
| Audience, and what they already believe | Smart generalist new to the topic; infer the common misconception |
| After watching they can… | One sentence derived from the topic |
| Length | 60 s (allowed 30–90) |
| Brand and references | `./brand`, `./refs`, `./screens` if present; otherwise derive tokens from the product/repo being explained and log that |

Work in a project folder `explainers/<slug>/` under the current directory (or the folder the user names). Layout:

```
explainers/<slug>/
├── brand/ refs/ screens/      # inputs (copied or symlinked if they live elsewhere)
├── DECISIONS.md  SOURCES.md  README.md
├── tokens.json                # palette, type, spacing, easing, grid
├── directions.html            # 3–4 directions side by side + decision log
├── storyboard/contact.png     # contact sheet, one still per beat
├── src/index.html             # the film: TIMELINE + window.seek(t)
├── src/audio.js               # procedural bed + cues, OfflineAudioContext
├── scripts/render.mjs         # headless Chrome → ffmpeg
├── captions.srt
└── out/
```

**Preflight.** Before any creative work, confirm the toolchain: `ffmpeg -version`, and a headless Chrome reachable from Node (`npx playwright --version` or Puppeteer). If either is missing, say exactly what to install and stop — do not plan a film you cannot render.

## 3. Principles

These follow the working process Meaghan Choi (Head of Design, Claude Code at Anthropic) describes in public talks — Behind the Craft (Sep 2025), Product School (Jun 2026), Dive Club (Jul 2026). The original prompt is by @0xCarnage; neither is an endorsement.

- **Shape before polish.** Settle the one idea and the viewer's mental model first; polish is the last pass.
- **Ask the review questions before designing:** who is this for, what are we communicating, does it need a name or can it stay invisible?
- **Never start from nothing.** Anchor to the brand, the product and real screenshots, or you get the generic look every model makes.
- **Go wide, then decide.** 3–4 directions side by side in one HTML page that doubles as a decision log.
- **Restraint is taste.** You can build anything, so cut whatever does not serve the idea.

## 4. Discovery

- Write the one question the film answers, in the viewer's own words.
- Split facts into **must-know** and a **cut list**; the cut list stays out.
- Find the hook: the belief most viewers hold that turns out to be wrong.
- Use a metaphor only if it makes the idea more accurate. Otherwise show the real thing.
- Every fact and number goes in `SOURCES.md` with its source as you find it.

## 5. Story arc

| Beat | Share | Job |
|---|---|---|
| Question | 0–10% | Open on the thing people get wrong, as an image, not a title card |
| Model | 10–35% | Build the smallest correct picture of how it works, one element per beat |
| Proof | 35–75% | Run the model on a real case; let cause and effect play out on screen |
| Turn | 75–90% | Change one variable and show what follows. Understanding clicks here |
| Payoff | 90–100% | The opening image again, now read correctly, plus one next step |

## 6. Visual system

- Pull palette, type and spacing from `./brand` into `tokens.json` before drawing anything.
- Warm neutral ground, one accent, two typefaces, one grid.
- Prefer real UI, real data and clean diagrams over illustration.
- **Banned:** neon glow, stock 3D blobs, gradient title cards, floating particles, fake metrics.

## 7. Motion language

- Motion carries meaning: things move to show grouping, order, cause or scale.
- One focal action at a time; everything else holds still.
- Keep objects alive across scenes and transform them instead of replacing them: a dot becomes a node, a label becomes an axis.
- Custom easing that settles without bounce (define the curves in `tokens.json`). The camera reframes between ideas and stays still while text is read.

## 8. Scene spec

Write every scene into `src/index.html`'s TIMELINE as data, with:

- **ID and time range**
- **Teaches:** the one thing this scene adds
- **Frame:** what is on screen, in order of importance
- **Motion:** enter, key action, settle, exit
- **Words:** on-screen text (max 8 words a line) and voice line, if any
- **Sound:** the cue that marks the key action
- **Check:** what the viewer can now say that they could not before

## 9. Copy

- Max two lines on screen at once; plain words before jargon.
- Never put the full voice line on screen; on-screen words are anchors.
- One name per thing, used every time.
- Every number has a source in `SOURCES.md`, or it goes.

## 10. Sound

- A tempo-locked procedural bed (Web Audio) with one motif that returns on the key idea.
- Soft UI cues only on actions that carry meaning; duck the bed under voice.
- Render audio offline with `OfflineAudioContext` from the same TIMELINE, write a WAV, and mux it in ffmpeg — never record real-time playback.
- If voice is used, it comes from a TTS engine the user has access to or a recording they supply; with neither, make the film work without voice and log it.
- Target about −16 LUFS integrated, true peak ≤ −1.5 dBTP.

## 11. Accessibility

- Text contrast at least 4.5:1 against its actual background.
- Captions burned in **and** shipped as `captions.srt`, both generated from the TIMELINE.
- Color is never the only signal. No flashes above 3 per second.
- A reduced-motion cut that keeps the same sequence of ideas (cuts and fades instead of travel and scale).

## 12. Render contract

- `window.seek(t)` paints the frame at time `t`; every frame is a pure function of `t`. No `requestAnimationFrame` clocks, no `Date.now()`, no CSS transitions — CSS animations only if paused and driven by `t`.
- ONE `TIMELINE` object holds every beat, move, caption and cue. Seeded randomness only.
- Fonts are loaded locally and awaited (`document.fonts.ready`) before the first frame.
- `scripts/render.mjs` launches headless Chrome at the target size, steps `t = n/60`, screenshots each frame, and pipes them to ffmpeg: `libx264`, `-crf 16`, `-pix_fmt yuv420p`, 60 fps, then muxes the WAV (AAC 192k).
- The 9:16 and 1:1 cuts are **recompositions** — layout rules per aspect in the same source, selected by a query param — not crops of the master.

## 13. Workflow

1. One-sentence idea and the viewer outcome → `DECISIONS.md`.
2. Tokens → `tokens.json`.
3. `directions.html` with 3–4 directions (a styleframe each, same beat); mark the winner and why.
4. Storyboard as a contact sheet → `storyboard/contact.png`.
5. Animatic and timing pass: grey boxes on the real timeline, read every line aloud at speaking pace.
6. Full build.
7. Sound and captions.
8. Verification (§14).
9. Export (§15).

## 14. Verification

Run these; do not just claim them.

- **Determinism:** render one frame twice and diff it — `cmp a.png b.png` must be silent.
- **Legibility:** a still at every beat; read every line at 390 px wide (the 9:16 cut).
- **Muted and audio-only:** the film must make sense with no sound, and the bed must follow the arc with no picture.
- **Loudness:** `ffmpeg -i out/master_16x9.mp4 -af ebur128=peak=true -f null -` — report integrated LUFS and true peak; fix and re-render if outside target.
- **Flashes:** sample frame luminance (`ffmpeg -i out/master_16x9.mp4 -vf signalstats,metadata=print:key=lavfi.signalstats.YAVG -f null -`) and flag any window with more than 3 large swings per second.
- **Design review:** dispatch a subagent with the stills and the scene spec, asking the three review questions from §3 plus "what would you cut?"; then an accessibility pass (contrast, captions, color-only signals, reduced-motion parity).
- Every fix ships with a before/after frame pair in `review/`.

## 15. Delivery

```
out/master_16x9.mp4
out/cut_9x16.mp4
out/cut_1x1.mp4
out/master_16x9_reduced-motion.mp4
captions.srt
storyboard/contact.png
src/ scripts/ tokens.json directions.html DECISIONS.md SOURCES.md
README.md   # how to re-render, and only what was actually tested
```

Report the output paths, measured loudness, and any check that could not be run.

## 16. Autonomy

Do not stop for approval on creative calls. Stop only for missing rights (brand assets, screenshots or music you are not cleared to use), unsafe content, a missing toolchain, or an ambiguity that changes the goal.
