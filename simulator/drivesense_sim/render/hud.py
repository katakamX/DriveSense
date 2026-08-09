"""Instrument HUD.

Everything on screen is read from `VehicleState`. The HUD is the point of the
window — it is what makes the telemetry legible while driving — so it gets the
detail budget that the scene does not.
"""

from __future__ import annotations

import math

import pygame

from drivesense_contracts import gear_label
from drivesense_sim.config import VehicleSpec
from drivesense_sim.core.state import VehicleState
from drivesense_sim.core.vehicle import COUPLING_THRESHOLD
from drivesense_sim.render import theme

GAUGE_START_DEG = 140.0
GAUGE_SWEEP_DEG = 260.0
SPEEDO_MAX_KPH = 200.0


class Fonts:
    def __init__(self) -> None:
        self.tiny = self._mono(13)
        self.small = self._mono(15)
        self.medium = self._mono(20)
        self.large = self._mono(34, bold=True)
        self.huge = self._mono(58, bold=True)

    @staticmethod
    def _mono(size: int, *, bold: bool = False) -> pygame.font.Font:
        return pygame.font.SysFont("consolas,dejavusansmono,couriernew,monospace", size, bold=bold)


def _text(
    surface: pygame.Surface,
    font: pygame.font.Font,
    value: str,
    pos: tuple[int, int],
    colour: theme.RGB,
    *,
    center: bool = False,
    right: bool = False,
) -> None:
    rendered = font.render(value, True, colour)
    rect = rendered.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.midright = pos
    else:
        rect.midleft = pos
    surface.blit(rendered, rect)


def _panel(surface: pygame.Surface, rect: pygame.Rect) -> None:
    pygame.draw.rect(surface, theme.SURFACE_RAISED, rect, border_radius=8)
    pygame.draw.rect(surface, theme.BORDER_SUBTLE, rect, width=1, border_radius=8)


def _arc_points(
    centre: tuple[int, int], radius: float, start_frac: float, end_frac: float, segments: int = 48
) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for i in range(segments + 1):
        frac = start_frac + (end_frac - start_frac) * i / segments
        angle = math.radians(GAUGE_START_DEG + GAUGE_SWEEP_DEG * frac)
        points.append((centre[0] + math.cos(angle) * radius, centre[1] + math.sin(angle) * radius))
    return points


def _gauge(
    surface: pygame.Surface,
    fonts: Fonts,
    centre: tuple[int, int],
    radius: int,
    fraction: float,
    *,
    title: str,
    value_text: str,
    unit: str,
    danger_from: float | None = None,
    danger_active: bool = False,
) -> None:
    fraction = max(0.0, min(1.0, fraction))

    pygame.draw.circle(surface, theme.SURFACE_OVERLAY, centre, radius + 12)
    pygame.draw.circle(surface, theme.BORDER_SUBTLE, centre, radius + 12, width=1)

    pygame.draw.lines(surface, theme.BORDER_STRONG, False, _arc_points(centre, radius, 0.0, 1.0), 3)

    if danger_from is not None:
        colour = theme.RISK_CRITICAL if danger_active else theme.RISK_HIGH
        pygame.draw.lines(surface, colour, False, _arc_points(centre, radius, danger_from, 1.0), 4)

    if fraction > 0.001:
        pygame.draw.lines(
            surface, theme.ACCENT, False, _arc_points(centre, radius - 8, 0.0, fraction), 5
        )

    for i in range(11):
        frac = i / 10
        angle = math.radians(GAUGE_START_DEG + GAUGE_SWEEP_DEG * frac)
        inner = radius - 16
        pygame.draw.line(
            surface,
            theme.CONTENT_MUTED,
            (centre[0] + math.cos(angle) * inner, centre[1] + math.sin(angle) * inner),
            (
                centre[0] + math.cos(angle) * (radius - 6),
                centre[1] + math.sin(angle) * (radius - 6),
            ),
            1,
        )

    angle = math.radians(GAUGE_START_DEG + GAUGE_SWEEP_DEG * fraction)
    pygame.draw.line(
        surface,
        theme.CONTENT_PRIMARY,
        centre,
        (centre[0] + math.cos(angle) * (radius - 20), centre[1] + math.sin(angle) * (radius - 20)),
        3,
    )
    pygame.draw.circle(surface, theme.ACCENT, centre, 5)

    _text(
        surface,
        fonts.tiny,
        title,
        (centre[0], centre[1] - radius + 26),
        theme.CONTENT_MUTED,
        center=True,
    )
    _text(
        surface,
        fonts.large,
        value_text,
        (centre[0], centre[1] + 34),
        theme.CONTENT_PRIMARY,
        center=True,
    )
    _text(
        surface, fonts.tiny, unit, (centre[0], centre[1] + 60), theme.CONTENT_SECONDARY, center=True
    )


def _bar(
    surface: pygame.Surface,
    fonts: Fonts,
    rect: pygame.Rect,
    fraction: float,
    label: str,
    colour: theme.RGB,
) -> None:
    fraction = max(0.0, min(1.0, fraction))
    _text(surface, fonts.tiny, label, (rect.left, rect.top - 10), theme.CONTENT_MUTED)
    _text(
        surface,
        fonts.tiny,
        f"{fraction * 100:5.1f}%",
        (rect.right, rect.top - 10),
        theme.CONTENT_SECONDARY,
        right=True,
    )
    pygame.draw.rect(surface, theme.SURFACE_OVERLAY, rect, border_radius=4)
    if fraction > 0.0:
        filled = pygame.Rect(rect.left, rect.top, max(2, int(rect.width * fraction)), rect.height)
        pygame.draw.rect(surface, colour, filled, border_radius=4)
    pygame.draw.rect(surface, theme.BORDER_SUBTLE, rect, width=1, border_radius=4)


def _steering(
    surface: pygame.Surface, fonts: Fonts, rect: pygame.Rect, angle_deg: float, max_deg: float
) -> None:
    _text(surface, fonts.tiny, "STEERING", (rect.left, rect.top - 10), theme.CONTENT_MUTED)
    _text(
        surface,
        fonts.tiny,
        f"{angle_deg:+6.1f}°",
        (rect.right, rect.top - 10),
        theme.CONTENT_SECONDARY,
        right=True,
    )
    pygame.draw.rect(surface, theme.SURFACE_OVERLAY, rect, border_radius=4)
    pygame.draw.line(
        surface, theme.BORDER_STRONG, (rect.centerx, rect.top), (rect.centerx, rect.bottom), 1
    )

    fraction = max(-1.0, min(1.0, angle_deg / max_deg))
    marker_x = int(rect.centerx + fraction * (rect.width / 2 - 4))
    if abs(fraction) > 0.001:
        span = pygame.Rect(
            min(rect.centerx, marker_x), rect.top + 4, abs(marker_x - rect.centerx), rect.height - 8
        )
        pygame.draw.rect(surface, theme.ACCENT_MUTED, span)
    pygame.draw.rect(
        surface, theme.ACCENT, pygame.Rect(marker_x - 2, rect.top, 4, rect.height), border_radius=2
    )
    pygame.draw.rect(surface, theme.BORDER_SUBTLE, rect, width=1, border_radius=4)


def _chip(
    surface: pygame.Surface,
    fonts: Fonts,
    rect: pygame.Rect,
    label: str,
    value: str,
    colour: theme.RGB,
    *,
    active: bool,
) -> None:
    pygame.draw.rect(surface, colour if active else theme.SURFACE_OVERLAY, rect, border_radius=6)
    pygame.draw.rect(surface, theme.BORDER_SUBTLE, rect, width=1, border_radius=6)
    text_colour = theme.SURFACE_BASE if active else theme.CONTENT_MUTED
    _text(surface, fonts.tiny, label, (rect.centerx, rect.centery - 8), text_colour, center=True)
    _text(
        surface,
        fonts.small,
        value,
        (rect.centerx, rect.centery + 9),
        theme.SURFACE_BASE if active else theme.CONTENT_PRIMARY,
        center=True,
    )


def clutch_status(state: VehicleState) -> str:
    if state.clutch_engagement <= COUPLING_THRESHOLD:
        return "DISENGAGED"
    if state.clutch_engagement < 0.95:
        return "SLIPPING"
    return "ENGAGED"


def draw(
    surface: pygame.Surface,
    fonts: Fonts,
    state: VehicleState,
    spec: VehicleSpec,
    panel: pygame.Rect,
    *,
    recording: bool,
    frames_written: int,
    key_hints: tuple[tuple[str, str], ...],
    fps: float,
) -> None:
    pygame.draw.rect(surface, theme.SURFACE_BASE, panel)
    pygame.draw.line(surface, theme.BORDER_STRONG, panel.topleft, panel.topright)

    # --- Gauges -------------------------------------------------------------
    _gauge(
        surface,
        fonts,
        (panel.left + 110, panel.top + 118),
        78,
        abs(state.speed_kph) / SPEEDO_MAX_KPH,
        title="SPEED",
        value_text=f"{abs(state.speed_kph):.0f}",
        unit="km/h",
    )
    _gauge(
        surface,
        fonts,
        (panel.left + 292, panel.top + 118),
        78,
        state.engine_rpm / spec.redline_rpm,
        title="ENGINE",
        value_text=f"{state.engine_rpm:.0f}",
        unit="rpm",
        danger_from=0.92,
        danger_active=state.rev_limiter_active,
    )

    # --- Gear ---------------------------------------------------------------
    gear_rect = pygame.Rect(panel.left + 396, panel.top + 42, 104, 152)
    _panel(surface, gear_rect)
    _text(
        surface,
        fonts.tiny,
        "GEAR",
        (gear_rect.centerx, gear_rect.top + 20),
        theme.CONTENT_MUTED,
        center=True,
    )
    gear_colour = theme.ACCENT if state.gear > 0 else theme.CONTENT_SECONDARY
    _text(
        surface,
        fonts.huge,
        gear_label(state.gear),
        (gear_rect.centerx, gear_rect.centery + 6),
        gear_colour,
        center=True,
    )
    _text(
        surface,
        fonts.tiny,
        f"{spec.max_forward_gear}-SPEED",
        (gear_rect.centerx, gear_rect.bottom - 18),
        theme.CONTENT_MUTED,
        center=True,
    )

    # --- Meters -------------------------------------------------------------
    bar_x = panel.left + 524
    bar_w = 250
    _bar(
        surface,
        fonts,
        pygame.Rect(bar_x, panel.top + 52, bar_w, 16),
        state.throttle,
        "THROTTLE",
        theme.RISK_LOW,
    )
    _bar(
        surface,
        fonts,
        pygame.Rect(bar_x, panel.top + 96, bar_w, 16),
        state.brake,
        "BRAKE",
        theme.RISK_CRITICAL,
    )
    _bar(
        surface,
        fonts,
        pygame.Rect(bar_x, panel.top + 140, bar_w, 16),
        state.engine_load,
        "ENGINE LOAD",
        theme.RISK_MODERATE,
    )
    _steering(
        surface,
        fonts,
        pygame.Rect(bar_x, panel.top + 184, bar_w, 16),
        state.steering_deg,
        spec.max_steering_deg,
    )

    # --- Status chips -------------------------------------------------------
    chip_x = panel.left + 802
    status = clutch_status(state)
    _chip(
        surface,
        fonts,
        pygame.Rect(chip_x, panel.top + 44, 128, 44),
        "CLUTCH",
        status,
        theme.RISK_MODERATE,
        active=status != "ENGAGED",
    )
    _chip(
        surface,
        fonts,
        pygame.Rect(chip_x + 140, panel.top + 44, 128, 44),
        "REDLINE",
        "LIMIT" if state.rev_limiter_active else "OK",
        theme.RISK_CRITICAL,
        active=state.rev_limiter_active,
    )
    _chip(
        surface,
        fonts,
        pygame.Rect(chip_x, panel.top + 100, 128, 44),
        "RECORDING",
        f"{frames_written}" if recording else "OFF",
        theme.RISK_CRITICAL,
        active=recording,
    )
    _chip(
        surface,
        fonts,
        pygame.Rect(chip_x + 140, panel.top + 100, 128, 44),
        "ENGINE",
        "STALLED" if state.stalled else "RUNNING",
        theme.RISK_HIGH,
        active=state.stalled,
    )

    # --- Secondary readouts -------------------------------------------------
    read_y = panel.top + 160
    readouts = (
        ("ACCEL", f"{state.accel_ms2:+5.2f} m/s²"),
        ("LATERAL", f"{state.lateral_accel_ms2:+5.2f} m/s²"),
        ("DISTANCE", f"{state.distance_m / 1000:6.3f} km"),
        ("COOLANT", f"{state.coolant_c:5.1f} °C"),
    )
    for index, (label, value) in enumerate(readouts):
        x = chip_x + (index % 2) * 140
        y = read_y + (index // 2) * 22
        _text(surface, fonts.tiny, label, (x, y), theme.CONTENT_MUTED)
        _text(surface, fonts.tiny, value, (x + 128, y), theme.CONTENT_PRIMARY, right=True)

    # --- Controls -----------------------------------------------------------
    hint_y = panel.bottom - 22
    x = panel.left + 24
    for key, action in key_hints:
        key_surface = fonts.tiny.render(key, True, theme.ACCENT)
        surface.blit(key_surface, (x, hint_y))
        x += key_surface.get_width() + 6
        action_surface = fonts.tiny.render(action, True, theme.CONTENT_MUTED)
        surface.blit(action_surface, (x, hint_y))
        x += action_surface.get_width() + 18

    _text(
        surface,
        fonts.tiny,
        f"{fps:4.0f} fps",
        (panel.right - 24, hint_y + 7),
        theme.CONTENT_MUTED,
        right=True,
    )
