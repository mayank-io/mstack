"""Convert Vedic horoscope chart images (JHora / Parashara's Light printouts) to
a structured JSON chart + ASCII North-Indian and South-Indian diagrams.

The source images embed a machine-readable longitude table at the bottom
(planet -> sign deg' min, retrograde, Jaimini karaka). We OCR *that table* (the
ground truth) plus the birth header via the `claude` vision CLI, then compute
every house deterministically from the planet signs and the Lagna sign. The
chart diagrams in the image are never parsed glyph-by-glyph.

Pipeline:  image --(claude vision)--> chart JSON --(pure renderers)--> ASCII

Usage:
  # extract + render both ASCII styles, JSON + charts to stdout
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/chart_to_ascii.py path/to/chart.png

  # render only (no vision call) from a previously extracted JSON
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/chart_to_ascii.py chart.json --emit ascii

  # batch a folder, writing <stem>.json and <stem>.txt next to each image
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/chart_to_ascii.py images/*.png -o images/

Options:
  --emit {json,ascii,both}   what to write (default: both)
  --style {north,south,both} ASCII style(s) to render (default: both)
  -o, --outdir DIR           write files instead of stdout
  --model MODEL              claude model for extraction (default: claude-opus-4-8)
  --overwrite                re-extract even if a sibling .json already exists

Unix-y: chart data (JSON / ASCII) goes to stdout; progress and errors to stderr.
Exit code is non-zero if any input fails.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "claude-opus-4-8"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

# Zodiac order — index 0..11 used for house arithmetic.
SIGNS = ["Ar", "Ta", "Ge", "Cn", "Le", "Vi", "Li", "Sc", "Sg", "Cp", "Aq", "Pi"]
SIGN_INDEX = {s: i for i, s in enumerate(SIGNS)}
SIGN_FULL = {
    "Ar": "Aries", "Ta": "Taurus", "Ge": "Gemini", "Cn": "Cancer",
    "Le": "Leo", "Vi": "Virgo", "Li": "Libra", "Sc": "Scorpio",
    "Sg": "Sagittarius", "Cp": "Capricorn", "Aq": "Aquarius", "Pi": "Pisces",
}
# Body abbreviations as printed by JHora / Parashara's Light.
BODY_FULL = {
    "As": "Ascendant (Lagna)", "Su": "Sun", "Mo": "Moon", "Ma": "Mars",
    "Me": "Mercury", "Ju": "Jupiter", "Ve": "Venus", "Sa": "Saturn",
    "Ra": "Rahu", "Ke": "Ketu",
    "AL": "Arudha Lagna", "HL": "Hora Lagna", "GL": "Ghati Lagna",
    "SL": "Sree Lagna", "Md": "Maandi", "Gk": "Gulika",
}
KARAKA_FULL = {
    "AK": "Atmakaraka", "AmK": "Amatyakaraka", "BK": "Bhratrikaraka",
    "MK": "Matrikaraka", "PiK": "Pitrikaraka", "PK": "Putrakaraka",
    "GK": "Gnatikaraka", "DK": "Darakaraka",
}


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Body:
    """One row of the chart's longitude table (or a diagram-only upagraha)."""

    code: str            # e.g. "Su", "As", "Md"
    sign: str            # two-letter sign, e.g. "Sc"
    deg: int | None = None     # whole degrees within the sign (0..29)
    minute: int | None = None  # arc-minutes (0..59)
    retro: bool = False
    karaka: str | None = None  # Jaimini chara karaka code, e.g. "AK"

    @property
    def sign_index(self) -> int:
        return SIGN_INDEX[self.sign]

    def label(self) -> str:
        """Compact chart-cell label, e.g. 'Ju(R)'."""
        return f"{self.code}(R)" if self.retro else self.code

    def longitude_str(self) -> str:
        if self.deg is None:
            return self.sign
        mm = f"{self.minute:02d}" if self.minute is not None else "00"
        s = f"{self.deg:2d} {self.sign} {mm}"
        if self.retro:
            s += " (R)"
        if self.karaka:
            s += f"-{self.karaka}"
        return s


@dataclass
class Chart:
    chart_type: str                         # "Rasi", "Navamsa", "Saptamsa", ...
    native: str | None = None
    date: str | None = None
    time: str | None = None
    tz: str | None = None
    place: str | None = None
    bodies: list[Body] = field(default_factory=list)

    @property
    def lagna_sign(self) -> str:
        for b in self.bodies:
            if b.code == "As":
                return b.sign
        raise ValueError("chart has no Ascendant (As) — cannot place houses")

    def house_of(self, sign: str) -> int:
        """House number (1..12) of a sign, counted from the Lagna sign."""
        return (SIGN_INDEX[sign] - SIGN_INDEX[self.lagna_sign]) % 12 + 1

    def bodies_in_sign(self, sign: str) -> list[Body]:
        return [b for b in self.bodies if b.sign == sign]

    def sign_in_house(self, house: int) -> str:
        """The sign occupying a given house number (North-Indian: houses fixed)."""
        return SIGNS[(SIGN_INDEX[self.lagna_sign] + house - 1) % 12]

    # ---- (de)serialization -------------------------------------------- #
    @classmethod
    def from_dict(cls, d: dict) -> "Chart":
        bodies = [
            Body(
                code=b["code"],
                sign=b["sign"],
                deg=b.get("deg"),
                minute=b.get("minute"),
                retro=bool(b.get("retro", False)),
                karaka=b.get("karaka"),
            )
            for b in d.get("bodies", [])
        ]
        return cls(
            chart_type=d.get("chart_type", "Rasi"),
            native=d.get("native"),
            date=d.get("date"),
            time=d.get("time"),
            tz=d.get("tz"),
            place=d.get("place"),
            bodies=bodies,
        )

    def to_dict(self) -> dict:
        return {
            "chart_type": self.chart_type,
            "native": self.native,
            "date": self.date,
            "time": self.time,
            "tz": self.tz,
            "place": self.place,
            "lagna": self.lagna_sign,
            "bodies": [
                {
                    k: v
                    for k, v in {
                        "code": b.code,
                        "sign": b.sign,
                        "deg": b.deg,
                        "minute": b.minute,
                        "retro": b.retro or None,
                        "karaka": b.karaka,
                    }.items()
                    if v is not None
                }
                for b in self.bodies
            ],
        }


# --------------------------------------------------------------------------- #
# Vision extraction
# --------------------------------------------------------------------------- #
_EXTRACT_PROMPT = """Read the Vedic astrology chart image at {image_path} and output ONE JSON object describing it. Output ONLY raw JSON — no markdown fence, no commentary.

The image is a Jagannatha Hora / Parashara's Light printout: a North-Indian chart (left), a South-Indian chart (right), a birth-data header, and a LONGITUDE TABLE across the bottom. The bottom table is your PRIMARY, authoritative source.

JSON shape:
{{
  "chart_type": "Rasi" | "Navamsa" | "Saptamsa" | "Trimsamsa" | "<as labelled in the chart centre>",
  "native": "<name in chart centre, or null>",
  "date": "<YYYY-MM-DD from header, or null>",
  "time": "<HH:MM:SS from header, or null>",
  "tz": "<e.g. '5:30 east' from header, or null>",
  "place": "<e.g. '81 E 51, 25 N 27' from header, or null>",
  "bodies": [
    {{"code": "As", "sign": "Cn", "deg": 27, "minute": 23, "retro": false, "karaka": null}},
    {{"code": "Su", "sign": "Sc", "deg": 4,  "minute": 8,  "retro": false, "karaka": "DK"}}
  ]
}}

Rules:
- "code": use exactly these two-letter abbreviations — As Su Mo Ma Me Ju Ve Sa Ra Ke (planets/points), and AL HL GL SL Md Gk (upagrahas). One entry per body.
- "sign": two-letter zodiac code — Ar Ta Ge Cn Le Vi Li Sc Sg Cp Aq Pi.
- "deg"/"minute": integers from the bottom table (e.g. "4 Sc 08" -> deg 4, minute 8). If a body appears only in the chart diagram (not the table), set deg and minute to null but still give its sign.
- "retro": true only if the table marks the body "(R)".
- "karaka": the Jaimini suffix after the longitude if present (AK AmK BK MK PiK PK GK DK), else null.
- Always include "As" (the Ascendant). Include every distinct body you can read.
Output the JSON now."""


def _run_subprocess(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    """Run a subprocess with a timeout and a sanitized environment.

    Strips CLAUDECODE / CLAUDE_CODE_* so a nested `claude` CLI runs cleanly even
    when this script is launched from inside Claude Code. Self-contained so the
    script has no dependency on any host package.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")
    }
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, env=env
    )


def extract_chart(image_path: Path, model: str = DEFAULT_MODEL) -> Chart:
    """OCR a chart image into a Chart via the `claude` vision CLI."""
    prompt = _EXTRACT_PROMPT.format(image_path=image_path)
    result = _run_subprocess(
        [
            "claude", "-p",
            "--model", model,
            "--effort", "high",
            "--allowedTools", "Read",
            "--no-session-persistence",
            prompt,
        ],
        timeout=1200,
    )
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()[:200]
        raise RuntimeError(f"claude exit {result.returncode}: {err}")
    data = _parse_json(result.stdout)
    return Chart.from_dict(data)


def _parse_json(text: str) -> dict:
    """Pull the JSON object out of model output, tolerating stray fences/prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON object found in model output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


# --------------------------------------------------------------------------- #
# ASCII rendering — shared helpers
# --------------------------------------------------------------------------- #
def _cell_lines(sign: str | None, bodies: list[Body], width: int, max_lines: int) -> list[str]:
    """Wrap a sign tag + body labels into <= max_lines lines of <= width chars."""
    tokens: list[str] = []
    if sign is not None:
        tokens.append(sign)
    tokens.extend(b.label() for b in bodies)
    lines: list[str] = []
    cur = ""
    for tok in tokens:
        cand = tok if not cur else f"{cur} {tok}"
        if len(cand) <= width:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = tok
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:  # overflow: keep first lines, mark truncation
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: width - 1] + "+"
    return lines


# --------------------------------------------------------------------------- #
# North-Indian chart (house-fixed diamond)
# --------------------------------------------------------------------------- #
_NORTH_W, _NORTH_H = 41, 21  # height ~ width/2 => diagonals render ~45 degrees

# centroid (row_frac, col_frac) for each house's text anchor. Corner/edge houses
# are pulled inward so multi-body labels stay clear of the border.
_HOUSE_ANCHORS: dict[int, tuple[float, float]] = {
    1: (0.27, 0.50), 4: (0.50, 0.27), 7: (0.73, 0.50), 10: (0.50, 0.73),
    2: (0.18, 0.31), 12: (0.18, 0.69), 3: (0.35, 0.15), 11: (0.35, 0.85),
    5: (0.65, 0.15), 9: (0.65, 0.85), 6: (0.82, 0.31), 8: (0.82, 0.69),
}


def _draw_line(grid: list[list[str]], r0: int, c0: int, r1: int, c1: int) -> None:
    """Stamp a thin '/' or '\\' diagonal between two points (one mark per row).

    All chart lines have |slope| ~ 0.5, so stepping once per row keeps the line a
    single clean character wide instead of a clustered 2-per-row staircase.
    """
    ch = "\\" if (r1 - r0) * (c1 - c0) > 0 else "/"
    steps = abs(r1 - r0)
    for i in range(steps + 1):
        r = r0 + (r1 - r0) * i // steps
        c = round(c0 + (c1 - c0) * i / steps)
        if 0 <= r < len(grid) and 0 <= c < len(grid[0]):
            grid[r][c] = ch


def _stamp(grid: list[list[str]], row: int, col: int, text: str) -> None:
    """Write text centered on (row, col), clamped to stay inside the border."""
    if not 0 <= row < len(grid):
        return
    w = len(grid[0])
    start = max(1, min(col - len(text) // 2, w - 1 - len(text)))
    for i, chr_ in enumerate(text):
        c = start + i
        if 1 <= c <= w - 2:
            grid[row][c] = chr_


def render_north(chart: Chart) -> str:
    w, h = _NORTH_W, _NORTH_H
    grid = [[" "] * w for _ in range(h)]
    # border
    for c in range(w):
        grid[0][c] = grid[h - 1][c] = "-"
    for r in range(h):
        grid[r][0] = grid[r][w - 1] = "|"
    for r, c in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)):
        grid[r][c] = "+"
    mid_r, mid_c = h // 2, w // 2
    # square diagonals
    _draw_line(grid, 0, 0, h - 1, w - 1)
    _draw_line(grid, 0, w - 1, h - 1, 0)
    # inscribed diamond (edge midpoints)
    _draw_line(grid, 0, mid_c, mid_r, w - 1)
    _draw_line(grid, mid_r, w - 1, h - 1, mid_c)
    _draw_line(grid, h - 1, mid_c, mid_r, 0)
    _draw_line(grid, mid_r, 0, 0, mid_c)
    # house labels at centroids
    for house, (rf, cf) in _HOUSE_ANCHORS.items():
        sign = chart.sign_in_house(house)
        bodies = chart.bodies_in_sign(sign)
        lines = _cell_lines(sign, bodies, width=11, max_lines=2)
        base = round(rf * (h - 1))
        top = base - (len(lines) - 1) // 2
        for i, line in enumerate(lines):
            _stamp(grid, top + i, round(cf * (w - 1)), line)
    body = "\n".join("".join(row).rstrip() for row in grid)
    return f"{_north_caption(chart)}\n{body}"


def _north_caption(chart: Chart) -> str:
    who = chart.native or "—"
    return f"North-Indian | {chart.chart_type} | {who} (Lagna {chart.lagna_sign})"


# --------------------------------------------------------------------------- #
# South-Indian chart (sign-fixed 4x4 grid)
# --------------------------------------------------------------------------- #
# Fixed sign -> (grid_row, grid_col) in the 4x4 layout; center 2x2 is the label.
_SOUTH_POS = {
    "Pi": (0, 0), "Ar": (0, 1), "Ta": (0, 2), "Ge": (0, 3),
    "Aq": (1, 0), "Cn": (1, 3),
    "Cp": (2, 0), "Le": (2, 3),
    "Sg": (3, 0), "Sc": (3, 1), "Li": (3, 2), "Vi": (3, 3),
}


def render_south(chart: Chart) -> str:
    cw, ch = 14, 4  # inner cell width / height
    lagna = chart.lagna_sign
    # Build the 3-line content for each of the 16 grid positions.
    content: dict[tuple[int, int], list[str]] = {}
    for sign, pos in _SOUTH_POS.items():
        bodies = chart.bodies_in_sign(sign)
        house = chart.house_of(sign)
        header = f"{sign}{'*' if sign == lagna else ''} H{house}"
        lines = [header] + _cell_lines(None, bodies, width=cw - 2, max_lines=ch - 2)
        content[pos] = lines
    # Center 2x2 label block.
    center = [
        chart.chart_type,
        (chart.native or "")[: cw * 2 - 2],
        chart.date or "",
        f"Lagna {lagna}",
    ]

    def cell_text(pos: tuple[int, int], line: int) -> str:
        lines = content.get(pos, [])
        txt = lines[line] if line < len(lines) else ""
        return txt[: cw - 2].ljust(cw - 2)

    sep = "+" + "+".join(["-" * cw] * 4) + "+"
    out: list[str] = [_south_caption(chart), sep]
    for gr in range(4):
        for ln in range(ch - 1):
            parts = []
            for gc in range(4):
                if 1 <= gr <= 2 and 1 <= gc <= 2:
                    # center block: render once spanning the 2x2 interior
                    if gc == 1:
                        # lay the 4 center strings across the two middle row-pairs
                        ctext = center[(gr - 1) * 2 + (0 if ln == 0 else 1)] if ln < 2 else ""
                        span = (cw * 2 + 1)
                        parts.append(" " + ctext.center(span - 1))
                        continue
                    if gc == 2:
                        continue  # absorbed by the span above
                parts.append(" " + cell_text((gr, gc), ln))
            out.append("|" + "|".join(parts) + "|")
        out.append(sep)
    return "\n".join(out)


def _south_caption(chart: Chart) -> str:
    who = chart.native or "—"
    return f"South-Indian | {chart.chart_type} | {who} (Lagna {chart.lagna_sign})"


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def render_ascii(chart: Chart, style: str) -> str:
    blocks = []
    if style in ("north", "both"):
        blocks.append(render_north(chart))
    if style in ("south", "both"):
        blocks.append(render_south(chart))
    return "\n\n".join(blocks)


def load_chart(input_path: Path, model: str, overwrite: bool) -> Chart:
    """Get a Chart from a .json (render-only) or an image (extract via vision)."""
    if input_path.suffix.lower() == ".json":
        return Chart.from_dict(json.loads(input_path.read_text(encoding="utf-8")))
    sidecar = input_path.with_suffix(".json")
    if sidecar.exists() and not overwrite:
        print(f"  using cached {sidecar.name}", file=sys.stderr)
        return Chart.from_dict(json.loads(sidecar.read_text(encoding="utf-8")))
    print(f"  extracting {input_path.name} via {model} …", file=sys.stderr)
    return extract_chart(input_path, model=model)


def process(input_path: Path, args: argparse.Namespace) -> None:
    chart = load_chart(input_path, args.model, args.overwrite)
    json_text = json.dumps(chart.to_dict(), ensure_ascii=False, indent=2)
    ascii_text = render_ascii(chart, args.style)

    if args.outdir:
        args.outdir.mkdir(parents=True, exist_ok=True)
        stem = input_path.stem
        if args.emit in ("json", "both"):
            (args.outdir / f"{stem}.json").write_text(json_text + "\n", encoding="utf-8")
        if args.emit in ("ascii", "both"):
            (args.outdir / f"{stem}.txt").write_text(ascii_text + "\n", encoding="utf-8")
        print(f"  wrote {stem}.json / {stem}.txt -> {args.outdir}", file=sys.stderr)
        # contract: final stdout line is machine-parseable (only when writing files;
        # without --outdir stdout carries the chart data itself)
        print(f"OUTPUT_DIR:{args.outdir}")
    else:
        if args.emit in ("json", "both"):
            print(json_text)
        if args.emit in ("ascii", "both"):
            if args.emit == "both":
                print()
            print(ascii_text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Convert Vedic chart images to JSON + ASCII North/South charts.",
    )
    p.add_argument("inputs", nargs="+", type=Path, help="chart image(s) or chart .json file(s)")
    p.add_argument("--emit", choices=["json", "ascii", "both"], default="both")
    p.add_argument("--style", choices=["north", "south", "both"], default="both")
    p.add_argument("-o", "--outdir", type=Path, help="write <stem>.json/.txt here instead of stdout")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"claude model (default: {DEFAULT_MODEL})")
    p.add_argument("--overwrite", action="store_true", help="re-extract even if a sibling .json exists")
    args = p.parse_args(argv)

    failures = 0
    for input_path in args.inputs:
        if not input_path.exists():
            print(f"skip (not found): {input_path}", file=sys.stderr)
            failures += 1
            continue
        if input_path.suffix.lower() not in IMAGE_SUFFIXES | {".json"}:
            print(f"skip (unsupported): {input_path}", file=sys.stderr)
            failures += 1
            continue
        print(f"{input_path}", file=sys.stderr)
        try:
            process(input_path, args)
        except Exception as exc:  # noqa: BLE001 - surface any failure per-file, keep going
            print(f"  FAILED: {exc}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
