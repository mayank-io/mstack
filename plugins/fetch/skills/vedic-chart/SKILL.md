---
name: vedic-chart
description: This skill should be used when the user shares a Vedic/Jyotish horoscope chart image and asks to "convert this chart", "extract this kundli", "digitize this horoscope", "chart to ascii", "read this birth chart", "what planets are in this chart", or to parse a rasi/navamsa/divisional (D-1, D-9, D-7, D-30, etc.) chart printout. Converts a chart image into structured JSON plus ASCII North-Indian and South-Indian diagrams. Also invoked by the fetch:blog-post skill when astrology charts are found in an article.
---

# Vedic Chart Extractor

Convert a Vedic astrology chart image (a Jagannatha Hora / Parashara's Light style
printout) into a structured JSON chart and ASCII North-Indian + South-Indian
diagrams. A bundled script does the work end to end.

## What the source images look like

The script targets the standard software printout: a North-Indian chart (left), a
South-Indian chart (right), a birth-data header, and — crucially — a **longitude
table across the bottom** listing each body as `sign deg' min` with retrograde and
Jaimini karaka markers (e.g. `Su: 4 Sc 08-DK`). That bottom table is the ground
truth; houses are computed from it deterministically, so the chart diagrams are
never parsed glyph-by-glyph.

A chart-only image with no bottom table still works, but bodies the table would
have carried fall back to sign-only placement (no degrees).

## How it works

```
image --(claude vision reads the longitude table)--> chart JSON --(pure renderers)--> ASCII
```

House placement is `house = (sign_index - lagna_index) mod 12 + 1`. North-Indian is
house-fixed (Lagna always top-center, signs rotate); South-Indian is sign-fixed
(Pisces/Aries/… in fixed cells, houses rotate). Both render from the same JSON.

## Usage

Extraction calls the `claude` CLI (must be on PATH, recent enough to accept
`--effort` and `--allowedTools`). Run the bundled script:

```bash
# extract + render both ASCII styles; JSON then charts to stdout
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/chart_to_ascii.py path/to/chart.png

# write sidecars (<stem>.json + <stem>.txt) next to the image(s)
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/chart_to_ascii.py images/*.png -o images/

# render only, no vision call, from a previously extracted JSON
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/chart_to_ascii.py chart.json --emit ascii
```

Options: `--emit {json,ascii,both}` (default both), `--style {north,south,both}`
(default both), `-o/--outdir DIR`, `--model MODEL` (default `claude-opus-4-8`),
`--overwrite` (re-extract even if a sibling `.json` exists; otherwise a cached
sidecar is reused). Data goes to stdout, progress/errors to stderr, non-zero exit
on any failure.

The script is standalone (plain `python3`, no virtualenv or extra packages).

## Procedure

1. Confirm the input is a Vedic chart image (or a chart `.json` for render-only).
2. Run the script with `-o <dir>` to write `.json` + `.txt` sidecars next to the
   image, or without `-o` to print to stdout for a quick look.
3. For batches, pass a glob; the script processes each file and reuses cached
   `.json` sidecars unless `--overwrite` is given.
4. Surface the ASCII chart and note the sidecar paths. Do not hand-transcribe the
   chart — the script's JSON is the structured source of truth.

## JSON shape

```json
{
  "chart_type": "Rasi",
  "native": "Indira Gandhi",
  "date": "1917-11-19", "time": "23:11:00", "tz": "5:30 east",
  "place": "81 E 51, 25 N 27",
  "lagna": "Cn",
  "bodies": [
    {"code": "As", "sign": "Cn", "deg": 27, "minute": 23},
    {"code": "Su", "sign": "Sc", "deg": 4, "minute": 8, "karaka": "DK"},
    {"code": "Ju", "sign": "Ta", "deg": 14, "minute": 6, "retro": true, "karaka": "MK"}
  ]
}
```

`code` uses two-letter abbreviations: planets/points `As Su Mo Ma Me Ju Ve Sa Ra Ke`
and upagrahas `AL HL GL SL Md Gk`. `sign` is `Ar Ta Ge Cn Le Vi Li Sc Sg Cp Aq Pi`.
`retro` and `karaka` (Jaimini chara karaka: `AK AmK BK MK PiK PK GK DK`) appear only
when present.
