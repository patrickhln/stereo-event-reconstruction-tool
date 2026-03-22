# python blinking_pattern.py --screen-width-px 3840 --screen-height-px 2160 --screen-width-cm 154.8 --screen-height-cm 84.6 --target-cols 8 --target-rows 6
# python blinking_pattern.py --screen-width-px 3840 --screen-height-px 2160 --screen-width-cm 154.8 --screen-height-cm 84.6 --target-cols 8 --target-rows 6 --repeats 60 --refresh-rate-hz 60 --background-level 0 --flush-levels 255,0 --flush-frames-per-level 10
import argparse
import json
import math
import time
from dataclasses import dataclass

import pygame

@dataclass
class Config:
    screen_width_px: int
    screen_height_px: int
    screen_width_cm: float
    screen_height_cm: float
    target_cols: int
    target_rows: int
    margin_px: int
    display: int = 0
    scale: float = 1.0
    background_level: int = 0
    hold_seconds: float = 5.0
    blink_period: float = 0.5
    repeats: int = 1
    blink_mode: str = "invert"
    flush_levels: tuple[int, ...] = (255, 0)
    flush_frames_per_level: int = 1
    refresh_rate_hz: float | None = None
    sync_to_refresh: bool = True
    manifest_path: str = "checkerboard_manifest.json"

class UserQuitException(Exception):
    pass


QUIT_KEYS = (pygame.K_ESCAPE, pygame.K_q)

def save_manifest(manifest: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def check_events_and_quit() -> None:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            raise UserQuitException()
        if event.type == pygame.WINDOWCLOSE:
            raise UserQuitException()
        if event.type == pygame.KEYDOWN and event.key in QUIT_KEYS:
            raise UserQuitException()
        if event.type == pygame.MOUSEBUTTONDOWN:
            raise UserQuitException()


def detect_refresh_rate_hz(display_index: int) -> float | None:
    getter = getattr(pygame.display, "get_current_refresh_rate", None)
    if callable(getter):
        for args in ((), (display_index,)):
            try:
                refresh_rate_hz = getter(*args)
            except TypeError:
                continue
            except pygame.error:
                break
            if isinstance(refresh_rate_hz, (int, float)) and refresh_rate_hz > 0:
                return float(refresh_rate_hz)

    getter = getattr(pygame.display, "get_desktop_display_mode", None)
    if callable(getter):
        try:
            mode = getter(display_index)
        except (TypeError, pygame.error):
            mode = None
        refresh_rate_hz = getattr(mode, "refresh_rate", 0) if mode is not None else 0
        if isinstance(refresh_rate_hz, (int, float)) and refresh_rate_hz > 0:
            return float(refresh_rate_hz)

    return None


def parse_flush_levels(value: str) -> tuple[int, ...]:
    levels = []
    for part in value.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        level = int(stripped)
        if not 0 <= level <= 255:
            raise argparse.ArgumentTypeError("Flush levels must be in the range 0-255.")
        levels.append(level)
    if not levels:
        raise argparse.ArgumentTypeError("Provide at least one flush level, e.g. 255,0.")
    return tuple(levels)

def render_checkerboard(board_w_px: int, board_h_px: int, square_px: int, inverted: bool = False) -> pygame.Surface:
    surface = pygame.Surface((board_w_px, board_h_px))
    rows = board_h_px // square_px
    cols = board_w_px // square_px

    for row in range(rows):
        for col in range(cols):
            is_white = (row + col) % 2 == 0
            if inverted:
                is_white = not is_white
            color = (255, 255, 255) if is_white else (0, 0, 0)
            rect = pygame.Rect(
                col * square_px,
                row * square_px,
                square_px,
                square_px,
            )
            pygame.draw.rect(surface, color, rect)
    return surface

def build_positions(margin_px: int, cell_w_px: float, cell_h_px: float) -> list[tuple[str, float, float]]:
    xs = [margin_px + (i + 0.5) * cell_w_px for i in range(3)]
    ys = [margin_px + (i + 0.5) * cell_h_px for i in range(3)]
    labels = [
        "top-left", "top-center", "top-right",
        "center-left", "center", "center-right",
        "bottom-left", "bottom-center", "bottom-right",
    ]
    return [
        (label, x, y)
        for label, (x, y) in zip(
            labels,
            [
                (xs[0], ys[0]), (xs[1], ys[0]), (xs[2], ys[0]),
                (xs[0], ys[1]), (xs[1], ys[1]), (xs[2], ys[1]),
                (xs[0], ys[2]), (xs[1], ys[2]), (xs[2], ys[2]),
            ],
        )
    ]

def show_fullscreen_centered(
    screen: pygame.Surface,
    pattern: pygame.Surface | None,
    center_pos: tuple[float, float],
    background_color: tuple[int, int, int],
) -> None:
    check_events_and_quit()
    screen.fill(background_color)
    if pattern is not None:
        rect = pattern.get_rect(center=(int(center_pos[0]), int(center_pos[1])))
        screen.blit(pattern, rect)
    pygame.display.flip()
    check_events_and_quit()

def wait_with_events(seconds: float) -> None:
    end_time = time.perf_counter() + seconds
    while time.perf_counter() < end_time:
        check_events_and_quit()
        remaining_ms = max(1, math.ceil((end_time - time.perf_counter()) * 1000))
        event = pygame.event.wait(min(remaining_ms, 20))
        
        if event.type == pygame.NOEVENT:
            continue
        if event.type == pygame.QUIT:
            raise UserQuitException()
        if event.type == pygame.WINDOWCLOSE:
            raise UserQuitException()
        if event.type == pygame.KEYDOWN and event.key in QUIT_KEYS:
            raise UserQuitException()
        if event.type == pygame.MOUSEBUTTONDOWN:
            raise UserQuitException()


def wait_until(deadline: float) -> None:
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        check_events_and_quit()
        pygame.time.wait(min(10, max(1, math.ceil(remaining * 1000))))


def present_solid_frame(
    screen: pygame.Surface,
    color: tuple[int, int, int],
) -> None:
    check_events_and_quit()
    screen.fill(color)
    pygame.display.flip()
    check_events_and_quit()


def show_blinking_checkerboard_synced(
    screen: pygame.Surface,
    pattern_a: pygame.Surface,
    pattern_b: pygame.Surface | None,
    center_pos: tuple[float, float],
    background_color: tuple[int, int, int],
    hold_seconds: float,
    blink_period: float,
    refresh_rate_hz: float,
) -> None:
    total_frames = max(1, round(hold_seconds * refresh_rate_hz))
    half_period_frames = max(1, round((blink_period * refresh_rate_hz) / 2.0))
    next_frame_deadline = time.perf_counter()

    for frame_index in range(total_frames):
        phase_index = (frame_index // half_period_frames) % 2
        pattern = pattern_a if phase_index == 0 else pattern_b
        show_fullscreen_centered(screen, pattern, center_pos, background_color)
        next_frame_deadline += 1.0 / refresh_rate_hz
        wait_until(next_frame_deadline)


def clear_screen(
    screen: pygame.Surface,
    background_color: tuple[int, int, int],
    duration_seconds: float,
) -> None:
    show_fullscreen_centered(screen, None, (0.0, 0.0), background_color)
    if duration_seconds > 0:
        wait_with_events(duration_seconds)


def flush_display(
    screen: pygame.Surface,
    refresh_rate_hz: float,
    flush_levels: tuple[int, ...],
    flush_frames_per_level: int,
) -> None:
    frame_count = max(1, flush_frames_per_level)
    next_frame_deadline = time.perf_counter()
    for level in flush_levels:
        color = (level, level, level)
        for _ in range(frame_count):
            present_solid_frame(screen, color)
            next_frame_deadline += 1.0 / refresh_rate_hz
            wait_until(next_frame_deadline)


def build_blink_patterns(
    board_w_px: int,
    board_h_px: int,
    square_px: int,
    blink_mode: str,
) -> tuple[pygame.Surface, pygame.Surface | None]:
    pattern_primary = render_checkerboard(board_w_px, board_h_px, square_px)
    if blink_mode == "invert":
        return pattern_primary, render_checkerboard(board_w_px, board_h_px, square_px, inverted=True)
    if blink_mode == "on_off":
        return pattern_primary, None
    raise ValueError(f"Unsupported blink mode: {blink_mode}")


def shutdown_pygame() -> None:
    pygame.event.pump()
    pygame.display.quit()
    pygame.quit()

def run_blinking_checkerboard(config: Config) -> None:
    pygame.init()
    requested_size = (config.screen_width_px, config.screen_height_px)
    # Use a borderless window sized to the target display instead of exclusive
    # fullscreen so the pattern stays visible when another monitor is clicked.
    screen = pygame.display.set_mode(requested_size, pygame.NOFRAME, display=config.display)
    pygame.display.set_caption("Blinking Checkerboard")
    try:
        W_px, H_px = screen.get_size()
        W_cm = config.screen_width_cm
        H_cm = config.screen_height_cm

        target_cols = config.target_cols
        target_rows = config.target_rows

        squares_x = target_cols + 1
        squares_y = target_rows + 1

        margin_px = config.margin_px
        scale = config.scale

        usable_w_px = W_px - 2 * margin_px
        usable_h_px = H_px - 2 * margin_px
        cell_w_px = usable_w_px / 3
        cell_h_px = usable_h_px / 3

        max_square_px = math.floor(
            min(
                cell_w_px / squares_x,
                cell_h_px / squares_y,
            )
        )

        if max_square_px <= 0:
            raise ValueError("Checkerboard does not fit. Reduce margin or target size.")

        square_px = math.floor(scale * max_square_px)

        if square_px <= 0:
            raise ValueError("Scale is too small. Increase --scale.")

        board_w_px = squares_x * square_px
        board_h_px = squares_y * square_px

        if W_cm is not None and H_cm is not None:
            col_spacing_cm = square_px * (W_cm / W_px)
            row_spacing_cm = square_px * (H_cm / H_px)
            board_w_cm = board_w_px * (W_cm / W_px)
            board_h_cm = board_h_px * (H_cm / H_px)
        else:
            col_spacing_cm = None
            row_spacing_cm = None
            board_w_cm = None
            board_h_cm = None

        positions = build_positions(margin_px, cell_w_px, cell_h_px)

        refresh_rate_hz = config.refresh_rate_hz or detect_refresh_rate_hz(config.display) or 60.0
        background_level = max(0, min(255, config.background_level))
        background_color = (background_level, background_level, background_level)

        position_labels = [name for name, _, _ in positions]
        position_centers_px = [[float(x), float(y)] for _, x, y in positions]

        manifest = {
            "screen_width_px": W_px,
            "screen_height_px": H_px,
            "screen_width_cm": W_cm,
            "screen_height_cm": H_cm,
            "target_cols": target_cols,
            "target_rows": target_rows,
            "squares_x": squares_x,
            "squares_y": squares_y,
            "square_px": square_px,
            "usable_w_px": usable_w_px,
            "usable_h_px": usable_h_px,
            "grid_cell_w_px": cell_w_px,
            "grid_cell_h_px": cell_h_px,
            "col_spacing_cm": col_spacing_cm,
            "row_spacing_cm": row_spacing_cm,
            "board_w_px": board_w_px,
            "board_h_px": board_h_px,
            "board_w_cm": board_w_cm,
            "board_h_cm": board_h_cm,
            "background_level": background_level,
            "hold_seconds": config.hold_seconds,
            "blink_period": config.blink_period,
            "blink_mode": config.blink_mode,
            "flush_levels": list(config.flush_levels),
            "flush_frames_per_level": config.flush_frames_per_level,
            "refresh_rate_hz": refresh_rate_hz,
            "sync_to_refresh": config.sync_to_refresh,
            "positions_px": positions,
            "position_labels": position_labels,
            "position_centers_px": position_centers_px,
            "positions_named_px": [
                {"label": name, "x": float(x), "y": float(y)}
                for name, x, y in positions
            ],
        }

        save_manifest(manifest, config.manifest_path)

        if col_spacing_cm is not None and row_spacing_cm is not None:
            print(f"square size: {square_px}px ({col_spacing_cm:.3f} cm) x {square_px}px ({row_spacing_cm:.3f} cm)")
        else:
            print(f"square size: {square_px}px x {square_px}px")

        print(f"background level: {background_level}")

        if config.sync_to_refresh:
            print(f"refresh sync: enabled at {refresh_rate_hz:.3f} Hz")
        else:
            print("refresh sync: disabled")

        pattern_a, pattern_b = build_blink_patterns(
            board_w_px,
            board_h_px,
            square_px,
            config.blink_mode,
        )

        print(f"blink mode: {config.blink_mode}")
        print(f"flush sequence: {list(config.flush_levels)} x {config.flush_frames_per_level} frame(s)")

        clear_screen(screen, background_color, 0.0)

        for repeat in range(config.repeats):
            for pos_name, pos_x, pos_y in positions:
                print(f"Showing {pos_name} (repeat {repeat + 1}/{config.repeats})")

                flush_display(
                    screen,
                    refresh_rate_hz,
                    config.flush_levels,
                    config.flush_frames_per_level,
                )
                clear_screen(screen, background_color, 0.0)

                if config.sync_to_refresh:
                    show_blinking_checkerboard_synced(
                        screen,
                        pattern_a,
                        pattern_b,
                        (pos_x, pos_y),
                        background_color,
                        config.hold_seconds,
                        config.blink_period,
                        refresh_rate_hz,
                    )
                else:
                    t_start = time.perf_counter()

                    while time.perf_counter() - t_start < config.hold_seconds:
                        show_fullscreen_centered(screen, pattern_a, (pos_x, pos_y), background_color)
                        wait_with_events(config.blink_period / 2)

                        show_fullscreen_centered(screen, pattern_b, (pos_x, pos_y), background_color)
                        wait_with_events(config.blink_period / 2)

        flush_display(
            screen,
            refresh_rate_hz,
            config.flush_levels,
            config.flush_frames_per_level,
        )
        clear_screen(screen, background_color, 0.0)

    except (UserQuitException, KeyboardInterrupt): 
        print("\nShutdown requested. Exiting...")
    finally:
        shutdown_pygame()

def parse_args() -> Config:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen-width-px", type=int, required=True)
    parser.add_argument("--screen-height-px", type=int, required=True)
    parser.add_argument("--screen-width-cm", type=float, required=False)
    parser.add_argument("--screen-height-cm", type=float, required=False)
    parser.add_argument("--target-cols", type=int, required=True)
    parser.add_argument("--target-rows", type=int, required=True)
    parser.add_argument("--margin-px", type=int, default=0)
    parser.add_argument("--display", type=int, default=0, help="Display index (0 for primary, 1 for secondary, etc.)")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--background-level", type=int, default=0, help="Static background intensity from 0 to 255; lower reduces panel-wide activity")
    parser.add_argument("--hold-seconds", type=float, default=5.0)
    parser.add_argument("--blink-period", type=float, default=0.5)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--blink-mode", choices=("invert", "on_off"), default="invert", help="Use inverted checkerboards instead of blanking to reduce full-screen flicker")
    parser.add_argument("--flush-levels", type=parse_flush_levels, default=(255, 0), help="Comma-separated grayscale flush levels before moving positions, e.g. 255,127,0")
    parser.add_argument("--flush-frames-per-level", type=int, default=1, help="How many refresh frames to show for each flush level")
    parser.add_argument("--refresh-rate-hz", type=float, default=None, help="Display refresh rate override used for frame-locked blinking")
    parser.add_argument("--no-sync-to-refresh", action="store_true", help="Disable frame-locked blinking and use wall-clock timing instead")
    parser.add_argument("--manifest-path", type=str, default="checkerboard_manifest.json")

    args = parser.parse_args()

    return Config(
        screen_width_px=args.screen_width_px,
        screen_height_px=args.screen_height_px,
        screen_width_cm=args.screen_width_cm,
        screen_height_cm=args.screen_height_cm,
        target_cols=args.target_cols,
        target_rows=args.target_rows,
        margin_px=args.margin_px,
        display=args.display,
        scale=args.scale,
        background_level=args.background_level,
        hold_seconds=args.hold_seconds,
        blink_period=args.blink_period,
        repeats=args.repeats,
        blink_mode=args.blink_mode,
        flush_levels=args.flush_levels,
        flush_frames_per_level=args.flush_frames_per_level,
        refresh_rate_hz=args.refresh_rate_hz,
        sync_to_refresh=not args.no_sync_to_refresh,
        manifest_path=args.manifest_path,
    )


if __name__ == "__main__":
    run_blinking_checkerboard(parse_args())
