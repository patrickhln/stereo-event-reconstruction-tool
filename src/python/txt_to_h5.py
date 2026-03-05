#!/usr/bin/env python3

import argparse
from pathlib import Path
from typing import Tuple

import numpy as np
import h5py


def to_binary_polarity(value: str) -> int:
    token = value.strip().lower()
    if token in {"1", "true", "t"}:
        return 1
    if token in {"0", "false", "f"}:
        return 0
    return 1 if float(value) > 0 else 0


def parse_txt_header(file, txt_path: Path) -> Tuple[int, int]:
    header = file.readline().split()
    if len(header) != 2:
        raise ValueError(f"first line must be '<width> <height>' in {txt_path}")

    width, height = map(int, header)
    if width <= 0 or height <= 0:
        raise ValueError(f"width and height must be positive in {txt_path}")
    return width, height


def write_h5_streaming(txt_path: Path, h5_path: Path, chunk_size: int = 1_000_000) -> int:
    h5_path.parent.mkdir(parents=True, exist_ok=True)

    with h5py.File(h5_path, "w") as h5f:
        # this layout matches event_cnn_minimal dynamic h5 loader
        events_group = h5f.create_group("events")
        xs_ds = events_group.create_dataset("xs", shape=(0,), maxshape=(None,), dtype=np.int16, chunks=True)
        ys_ds = events_group.create_dataset("ys", shape=(0,), maxshape=(None,), dtype=np.int16, chunks=True)
        ts_ds = events_group.create_dataset("ts", shape=(0,), maxshape=(None,), dtype=np.float64, chunks=True)
        ps_ds = events_group.create_dataset("ps", shape=(0,), maxshape=(None,), dtype=np.int8, chunks=True)

        h5f.create_group("images")

        with txt_path.open("r") as file:
            width, height = parse_txt_header(file, txt_path)

            xs_buf = np.empty(chunk_size, dtype=np.int16)
            ys_buf = np.empty(chunk_size, dtype=np.int16)
            ts_buf = np.empty(chunk_size, dtype=np.float64)
            ps_buf = np.empty(chunk_size, dtype=np.int8)

            used = 0
            total = 0

            def flush_buffer() -> None:
                nonlocal used, total
                if used == 0:
                    return

                new_total = total + used
                xs_ds.resize((new_total,))
                ys_ds.resize((new_total,))
                ts_ds.resize((new_total,))
                ps_ds.resize((new_total,))

                xs_ds[total:new_total] = xs_buf[:used]
                ys_ds[total:new_total] = ys_buf[:used]
                ts_ds[total:new_total] = ts_buf[:used]
                ps_ds[total:new_total] = ps_buf[:used]

                total = new_total
                used = 0

            for line_number, line in enumerate(file, start=2):
                if not line.strip():
                    continue

                parts = line.split()
                if len(parts) != 4:
                    raise ValueError(f"invalid event format at line {line_number} in {txt_path}")

                t, x, y, p = parts
                x_val = int(x)
                y_val = int(y)

                if x_val < 0 or x_val >= width:
                    raise ValueError(f"x value {x_val} outside [0, {width - 1}] at line {line_number} in {txt_path}")
                if y_val < 0 or y_val >= height:
                    raise ValueError(f"y value {y_val} outside [0, {height - 1}] at line {line_number} in {txt_path}")

                xs_buf[used] = x_val
                ys_buf[used] = y_val
                ts_buf[used] = float(t)
                ps_buf[used] = to_binary_polarity(p)
                used += 1

                if used == chunk_size:
                    flush_buffer()
                    if total and total % 10_000_000 == 0:
                        print(f"written {total:,} events from {txt_path}")

            flush_buffer()

            if total == 0:
                raise ValueError(f"no events found in {txt_path}")

        h5f.attrs["sensor_resolution"] = np.asarray([height, width], dtype=np.int32)
        h5f.attrs["num_events"] = int(total)
        h5f.attrs["num_imgs"] = 0
        h5f.attrs["source"] = "sert_txt"

        return total


def resolve_txt_inputs(path_arg: Path):
    if path_arg.is_file():
        if path_arg.suffix.lower() != ".txt":
            raise ValueError(f"expected a .txt file, got: {path_arg}")
        return [path_arg]

    if not path_arg.exists():
        raise FileNotFoundError(f"path does not exist: {path_arg}")

    # scene/calibration paths store files inside intermediate/
    intermediate_dir = path_arg if path_arg.name == "intermediate" else path_arg / "intermediate"
    if not intermediate_dir.is_dir():
        raise FileNotFoundError(f"could not find intermediate folder at: {intermediate_dir}")

    txt_paths = [
        intermediate_dir / "leftEvents.txt",
        intermediate_dir / "rightEvents.txt",
    ]
    txt_paths = [txt_path for txt_path in txt_paths if txt_path.exists()]
    if txt_paths:
        return txt_paths

    if list(intermediate_dir.glob("*.aedat4")):
        raise FileNotFoundError(f"found .aedat4 files but no leftEvents.txt/rightEvents.txt in: {intermediate_dir}")

    raise FileNotFoundError(f"no leftEvents.txt/rightEvents.txt found in: {intermediate_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="convert sert txt events to h5 for event_cnn_minimal")
    parser.add_argument("path", type=Path, help="scene/calibration path, intermediate path, or one events .txt file")
    parser.add_argument("output_h5", nargs="?", type=Path, help="optional output .h5 path (only for one .txt input)")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing .h5 files")
    parser.add_argument("--chunk-size", type=int, default=1_000_000, help="number of events buffered per write chunk")
    args = parser.parse_args()

    if args.chunk_size <= 0:
        parser.error("--chunk-size must be > 0")

    txt_paths = resolve_txt_inputs(args.path)
    if args.output_h5 is not None and len(txt_paths) != 1:
        parser.error("output_h5 is only allowed when input points to a single .txt file")

    for txt_path in txt_paths:
        h5_path = args.output_h5 if args.output_h5 is not None else txt_path.with_suffix(".h5")

        if h5_path.exists() and not args.overwrite:
            print(f"skip existing: {h5_path}")
            continue

        total = write_h5_streaming(txt_path, h5_path, chunk_size=args.chunk_size)
        print(f"wrote {total} events: {txt_path} -> {h5_path}")


if __name__ == "__main__":
    main()
