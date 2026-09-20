"""Render the published shared-100 benchmark figures from archived reports."""

import json
from pathlib import Path
from statistics import median
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent / "docs" / "assets"
PUBLISHED = ROOT / "published"
ROUTING = [
    json.loads((PUBLISHED / f"routing-shared-100-3000ms-run{i}-2026-09-20.json").read_text())
    for i in (1, 2, 3)
]
AGENT = [
    json.loads((PUBLISHED / f"agent-bench-shared-100-3000ms-run{i}-2026-09-20.json").read_text())
    for i in (1, 2, 3)
]

if len({report["dataset_sha256"] for report in ROUTING + AGENT}) != 1:
    raise ValueError("Figures require reports from the same dataset")
if any(report["settings"]["jev_routing_timeout_ms"] != 3000 for report in ROUTING + AGENT):
    raise ValueError("Figures require the 3000 ms protocol")

INK = "#1a1a1a"
MUTED = "#625f5a"
BASE = "#a8a5a0"
LINE = "#dedbd6"
BG = "#fbfaf8"
SANS = "Geist, system-ui, sans-serif"
MONO = "Geist Mono, ui-monospace, monospace"


def text(x, y, value, *, size=13, fill=INK, weight=None, anchor=None, mono=False):
    attrs = [
        f'x="{x}"',
        f'y="{y}"',
        f'fill="{fill}"',
        f'font-family="{MONO if mono else SANS}"',
        f'font-size="{size}"',
    ]
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    return f"<text {' '.join(attrs)}>{escape(value)}</text>"


def line(y, width):
    inset = 18 if width == 312 else 28
    return f'<line x1="{inset}" y1="{y}" x2="{width - inset}" y2="{y}" stroke="{LINE}"/>'


def rect(x, y, width, height, fill):
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}"/>'


def row(label, value, width, y, *, dark, bar=None):
    color = INK if dark else MUTED
    parts = [
        text(28, y, label, size=14, fill=color),
        text(width - 28, y, value, mono=True, anchor="end"),
    ]
    if bar is not None:
        parts.append(
            f'<rect x="126" y="{y - 11}" width="{bar}" height="10" fill="{INK if dark else BASE}"/>'
        )
    return "\n  ".join(parts)


def figure(name, title, subtitle, metrics, footer, *, mobile=False, height=None):
    width = 312 if mobile else 624
    height = height or (94 + len(metrics) * 103 + 65 if mobile else 120 + len(metrics) * 107 + 65)
    desc = ". ".join(
        [title, subtitle] + [f"{m[0]}: {m[1][1]} versus {m[2][1]}" for m in metrics] + [footer]
    )
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        f'  <title id="title">{escape(title)}</title>',
        f'  <desc id="description">{escape(desc)}</desc>',
        f'  <rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" '
        f'rx="4" fill="{BG}" stroke="{LINE}"/>',
    ]
    if mobile:
        parts += [
            "  " + text(18, 30, name.upper(), size=10, fill=MUTED, mono=True),
            "  " + text(18, 57, title, size=17, weight="600"),
            "  " + text(18, 78, subtitle, size=11, fill=MUTED),
            "  " + line(94.5, width),
        ]
        for i, (heading, left, right, bars) in enumerate(metrics):
            top = 94 + i * 103
            parts += [
                "  " + text(18, top + 23, heading.upper(), size=10, fill=MUTED, mono=True),
                "  " + text(18, top + 48, left[0], size=12, fill=INK),
                "  " + text(165, top + 48, right[0], size=12, fill=MUTED),
                "  " + text(18, top + 67, left[1], size=12, mono=True),
                "  " + text(165, top + 67, right[1], size=12, mono=True),
            ]
            if bars:
                scale = 125 / max(left[2], right[2])
                parts += [
                    "  " + rect(18, top + 80, max(2, round(left[2] * scale)), 7, INK),
                    "  " + rect(165, top + 80, max(2, round(right[2] * scale)), 7, BASE),
                ]
            parts.append("  " + line(top + 103.5, width))
        for j, note in enumerate(footer.split(" | ")):
            parts.append(
                "  " + text(18, 94 + len(metrics) * 103 + 23 + j * 16, note, size=10, fill=MUTED)
            )
    else:
        parts += [
            "  " + text(28, 39, name.upper(), size=11, fill=MUTED, mono=True),
            "  " + text(28, 73, title, size=20, weight="600"),
            "  " + text(28, 98, subtitle, size=13, fill=MUTED),
            "  " + line(119.5, width),
        ]
        for i, (heading, left, right, bars) in enumerate(metrics):
            top = 120 + i * 107
            parts.append("  " + text(28, top + 29, heading.upper(), size=11, fill=MUTED, mono=True))
            if bars:
                scale = 300 / max(left[2], right[2])
                left_bar, right_bar = (
                    max(2, round(left[2] * scale)),
                    max(2, round(right[2] * scale)),
                )
            else:
                left_bar = right_bar = None
            parts += [
                "  " + row(left[0], left[1], width, top + 57, dark=True, bar=left_bar),
                "  " + row(right[0], right[1], width, top + 86, dark=False, bar=right_bar),
                "  " + line(top + 106.5, width),
            ]
        for j, note in enumerate(footer.split(" | ")):
            parts.append(
                "  " + text(28, 120 + len(metrics) * 107 + 25 + j * 16, note, size=11, fill=MUTED)
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def save(stem, *args, **kwargs):
    for mobile in (False, True):
        suffix = "-mobile" if mobile else ""
        output = ASSETS / f"{stem}{suffix}.svg"
        output.write_text(figure(*args, mobile=mobile, **kwargs))
        print(output.relative_to(ROOT.parent))


def routing_values(arm, metric):
    return [report["routers"][arm]["metrics"][metric] for report in ROUTING]


def agent_values(arm, metric, *, category=None):
    section = "by_expectation" if category else "summaries"
    return [
        report[section][arm][category][metric] if category else report[section][arm][metric]
        for report in AGENT
    ]


fit_count = ROUTING[0]["routers"]["jev"]["metrics"]["tool_fit_case_count"]
if any(
    report["routers"][arm]["metrics"]["tool_fit_case_count"] != fit_count
    for report in ROUTING
    for arm in ("jev", "baseline")
):
    raise ValueError("Tool-fit denominators must match")
fit_jev = round(median(routing_values("jev", "tool_fit_accuracy")) * fit_count)
fit_luna = round(median(routing_values("baseline", "tool_fit_accuracy")) * fit_count)
routing_jev_latency = median(routing_values("jev", "latency_mean_ms"))
routing_luna_latency = median(routing_values("baseline", "latency_mean_ms"))
routing_jev_cost = median(routing_values("jev", "estimated_cost_usd"))
routing_luna_cost = median(routing_values("baseline", "estimated_cost_usd"))
save(
    "routing-benchmark-100",
    "EXPERIMENT 01 / ROUTER ONLY",
    "Jev and Luna choose the tool",
    "100 shared prompts · median of 3 runs",
    [
        (
            "Tool fit · 81 labeled cases",
            ("Jev", f"{fit_jev}/{fit_count} · {fit_jev / fit_count:.1%}", fit_jev),
            ("Luna", f"{fit_luna}/{fit_count} · {fit_luna / fit_count:.1%}", fit_luna),
            True,
        ),
        (
            "Mean routing latency",
            (
                "Jev",
                f"{routing_jev_latency / 1000:.3f} s",
                routing_jev_latency,
            ),
            (
                "Luna",
                f"{routing_luna_latency / 1000:.3f} s",
                routing_luna_latency,
            ),
            True,
        ),
        (
            "Estimated API cost · 100 prompts",
            ("Jev", f"${routing_jev_cost:.5f}", routing_jev_cost),
            (
                "Luna",
                f"${routing_luna_cost:.5f}",
                routing_luna_cost,
            ),
            True,
        ),
    ],
    "Medians of 3 runs · configured prices | Tool fit is not task completion",
)

if any(
    report["summaries"][arm]["missing_routing_usage_calls"]
    or report["summaries"][arm]["estimated_cost_usd"] is None
    for report in AGENT
    for arm in ("jev", "flat")
):
    raise ValueError("Figures require complete agent cost data")
jev_read_success = median(agent_values("jev", "success_count", category="complete"))
flat_read_success = median(agent_values("flat", "success_count", category="complete"))
jev_read_latency = median(agent_values("jev", "mean_latency_ms", category="complete"))
flat_read_latency = median(agent_values("flat", "mean_latency_ms", category="complete"))
jev_latency = median(agent_values("jev", "mean_latency_ms"))
flat_latency = median(agent_values("flat", "mean_latency_ms"))
jev_cost = median(agent_values("jev", "estimated_cost_usd"))
flat_cost = median(agent_values("flat", "estimated_cost_usd"))
save(
    "agent-benchmark-100",
    "EXPERIMENT 02 / AGENT LOOP",
    "Jev filters before Luna",
    "100 shared prompts · median of 3 runs",
    [
        (
            "Read-task success · 47 cases",
            ("Jev filter", f"{jev_read_success:.0f}/47", jev_read_success),
            ("All tools", f"{flat_read_success:.0f}/47", flat_read_success),
            True,
        ),
        (
            "Mean read-task latency · 47 cases",
            (
                "Jev filter",
                f"{jev_read_latency / 1000:.3f} s",
                jev_read_latency,
            ),
            (
                "All tools",
                f"{flat_read_latency / 1000:.3f} s",
                flat_read_latency,
            ),
            True,
        ),
        (
            "Mean latency · all 100 prompts",
            ("Jev filter", f"{jev_latency / 1000:.3f} s", jev_latency),
            ("All tools", f"{flat_latency / 1000:.3f} s", flat_latency),
            True,
        ),
        (
            "Estimated cost · all 100 prompts",
            ("Jev filter", f"${jev_cost:.5f}", jev_cost),
            ("All tools", f"${flat_cost:.5f}", flat_cost),
            True,
        ),
    ],
    "Medians of 3 runs · complete usage | Costs use configured prices",
)
