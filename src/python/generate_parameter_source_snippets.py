"""Generate parameter snippets from YAML presets.

examples:
    python src/python/generate_yaml_comment_snippets.py
    python src/python/generate_yaml_comment_snippets.py --group esvo_mapping
    python src/python/generate_yaml_comment_snippets.py --parameter residual_vis_threshold
"""


import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import urlopen


ESVO_RAW_BASE = "https://raw.githubusercontent.com/HKUST-Aerial-Robotics/ESVO/master"
ESVO2_RAW_BASE = "https://raw.githubusercontent.com/NAIL-HNU/ESVO2/main"


@dataclass(frozen=True)
class SourceSpec:
    label: str
    display_path: str
    location: str


@dataclass(frozen=True)
class ParameterRecord:
    key: str
    value: str
    line: int


SOURCE_GROUPS = {
    "esvo_mapping": [
        SourceSpec(
            "ESVO RPG mapping",
            "ESVO/esvo_core/cfg/mapping/mapping_rpg.yaml",
            f"{ESVO_RAW_BASE}/esvo_core/cfg/mapping/mapping_rpg.yaml",
        ),
        SourceSpec(
            "ESVO UPenn mapping",
            "ESVO/esvo_core/cfg/mapping/mapping_upenn.yaml",
            f"{ESVO_RAW_BASE}/esvo_core/cfg/mapping/mapping_upenn.yaml",
        ),
        SourceSpec(
            "ESVO HKUST mapping",
            "ESVO/esvo_core/cfg/mapping/mapping_hkust.yaml",
            f"{ESVO_RAW_BASE}/esvo_core/cfg/mapping/mapping_hkust.yaml",
        ),
    ],
    "esvo_tracking": [
        SourceSpec(
            "ESVO RPG tracking",
            "ESVO/esvo_core/cfg/tracking/tracking_rpg.yaml",
            f"{ESVO_RAW_BASE}/esvo_core/cfg/tracking/tracking_rpg.yaml",
        ),
        SourceSpec(
            "ESVO UPenn tracking",
            "ESVO/esvo_core/cfg/tracking/tracking_upenn.yaml",
            f"{ESVO_RAW_BASE}/esvo_core/cfg/tracking/tracking_upenn.yaml",
        ),
        SourceSpec(
            "ESVO HKUST tracking",
            "ESVO/esvo_core/cfg/tracking/tracking_hkust.yaml",
            f"{ESVO_RAW_BASE}/esvo_core/cfg/tracking/tracking_hkust.yaml",
        ),
    ],
    "esvo2_mapping": [
        SourceSpec(
            "ESVO2 RPG AA mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_rpg_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_rpg_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 UPenn AA mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_upenn_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_upenn_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 DSEC AA mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_dsec_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_dsec_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 TUM-VIE AA mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_tum_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_tum_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 VECtor AA mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_vector_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_vector_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 DVX AA mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_dvx_AA_mapping.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_dvx_AA_mapping.yaml",
        ),
        SourceSpec(
            "ESVO2 DVX AA tracking-mapping",
            "ESVO2/esvo2_core/cfg/mapping/mapping_dvx_AA_tracking.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/mapping/mapping_dvx_AA_tracking.yaml",
        ),
    ],
    "esvo2_tracking": [
        SourceSpec(
            "ESVO2 RPG AA tracking",
            "ESVO2/esvo2_core/cfg/tracking/tracking_rpg_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_rpg_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 UPenn AA tracking",
            "ESVO2/esvo2_core/cfg/tracking/tracking_upenn_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_upenn_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 DSEC AA tracking",
            "ESVO2/esvo2_core/cfg/tracking/tracking_dsec_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_dsec_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 TUM-VIE AA tracking",
            "ESVO2/esvo2_core/cfg/tracking/tracking_tum_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_tum_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 VECtor AA tracking",
            "ESVO2/esvo2_core/cfg/tracking/tracking_vector_AA.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_vector_AA.yaml",
        ),
        SourceSpec(
            "ESVO2 DVX AA tracking",
            "ESVO2/esvo2_core/cfg/tracking/tracking_dvx_AA_mapping.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_dvx_AA_mapping.yaml",
        ),
        SourceSpec(
            "ESVO2 DVX AA tracking-only",
            "ESVO2/esvo2_core/cfg/tracking/tracking_dvx_AA_tracking.yaml",
            f"{ESVO2_RAW_BASE}/esvo2_core/cfg/tracking/tracking_dvx_AA_tracking.yaml",
        ),
    ],
    "esvo2_image_representation": [
        SourceSpec(
            "ESVO2 image representation left",
            "ESVO2/image_representation/cfg/image_representation_fast.yaml",
            f"{ESVO2_RAW_BASE}/image_representation/cfg/image_representation_fast.yaml",
        ),
        SourceSpec(
            "ESVO2 image representation right",
            "ESVO2/image_representation/cfg/image_representation_fast_r.yaml",
            f"{ESVO2_RAW_BASE}/image_representation/cfg/image_representation_fast_r.yaml",
        ),
    ],
}


DEFAULT_GROUP_ORDER = [
    "esvo_mapping",
    "esvo_tracking",
    "esvo2_mapping",
    "esvo2_tracking",
    "esvo2_image_representation",
]


def fetch_text(location: str) -> str:
    if location.startswith(("http://", "https://")):
        with urlopen(location, timeout=30) as response:
            return response.read().decode("utf-8")
    return Path(location).read_text(encoding="utf-8")


def parse_top_level_parameters(text: str) -> list[ParameterRecord]:
    records: list[ParameterRecord] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw_line[:1].isspace():
            continue
        content = raw_line.split("#", 1)[0].rstrip()
        if ":" not in content:
            continue
        key, value = content.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        records.append(ParameterRecord(key=key, value=value, line=line_no))
    return records


def selected_sources(group_names: Iterable[str]) -> list[SourceSpec]:
    sources: list[SourceSpec] = []
    for group_name in group_names:
        sources.extend(SOURCE_GROUPS[group_name])
    return sources


def build_snippets(sources: Iterable[SourceSpec], parameter_filter: str | None) -> dict[str, list[str]]:
    snippets: dict[str, list[str]] = {}
    for source in sources:
        text = fetch_text(source.location)
        for record in parse_top_level_parameters(text):
            if parameter_filter and record.key != parameter_filter:
                continue
            entry = (
                f"#   - {source.label}: {record.value} "
                f"({source.display_path}:{record.line})"
            )
            snippets.setdefault(record.key, []).append(entry)
    return snippets


def format_output(snippets: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for key, entries in snippets.items():
        lines.append(f"# {key}:")
        lines.extend(entries)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="generate YAML parameter comment snippets."
    )
    parser.add_argument(
        "--group",
        action="append",
        choices=DEFAULT_GROUP_ORDER,
        help="source group to include, repeat to select multiple groups.",
    )
    parser.add_argument(
        "--parameter",
        help="Only print snippets for a single top level parameter.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    group_names = args.group or DEFAULT_GROUP_ORDER
    try:
        snippets = build_snippets(selected_sources(group_names), args.parameter)
    except (OSError, URLError) as exc:
        print(f"Failed to read YAML sources: {exc}", file=sys.stderr)
        return 1

    if not snippets:
        if args.parameter:
            print(f"No parameter named '{args.parameter}' was found.", file=sys.stderr)
        else:
            print("No parameters found in the selected sources.", file=sys.stderr)
        return 1

    sys.stdout.write(format_output(snippets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
