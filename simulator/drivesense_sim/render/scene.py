"""A deliberately minimal driving scene.

Lane markings scroll by actual integrated distance and the road shifts with
actual heading, so what you see is driven by the same state the telemetry
reports. There are no assets, sprites, textures, traffic or weather: the
simulator exists to produce telemetry, not to be a game.
"""

from __future__ import annotations

import math

import pygame

from drivesense_sim.core.state import VehicleState
from drivesense_sim.render import theme

LANE_SPACING_M = 12.0
LANE_LENGTH_M = 5.0
ROAD_HALF_WIDTH_M = 4.5
CAMERA_HEIGHT = 1.4
FOCAL = 420.0
NEAR_M = 4.0
FAR_M = 140.0


def _project(distance_ahead: float, lateral_m: float, horizon_y: float) -> tuple[float, float]:
    """Pinhole projection of a ground point ahead of the camera."""
    depth = max(distance_ahead, 0.5)
    scale = FOCAL / depth
    return lateral_m * scale, horizon_y + CAMERA_HEIGHT * scale


def draw(surface: pygame.Surface, state: VehicleState, scene_rect: pygame.Rect) -> None:
    horizon_y = scene_rect.top + scene_rect.height * 0.34
    centre_x = scene_rect.centerx

    surface.fill(theme.SKY, scene_rect)
    pygame.draw.rect(
        surface,
        theme.GROUND,
        pygame.Rect(scene_rect.left, horizon_y, scene_rect.width, scene_rect.bottom - horizon_y),
    )

    # Curvature cue: steering displaces the road laterally with distance.
    curve = math.tan(math.radians(state.steering_deg)) * 0.5

    left_edge: list[tuple[float, float]] = []
    right_edge: list[tuple[float, float]] = []
    steps = 40
    for i in range(steps + 1):
        depth = NEAR_M + (FAR_M - NEAR_M) * (i / steps) ** 2
        offset = curve * depth * depth * 0.012
        lx, ly = _project(depth, -ROAD_HALF_WIDTH_M - offset, horizon_y)
        rx, ry = _project(depth, ROAD_HALF_WIDTH_M - offset, horizon_y)
        left_edge.append((centre_x + lx, ly))
        right_edge.append((centre_x + rx, ry))

    polygon = [*left_edge, *reversed(right_edge)]
    pygame.draw.polygon(surface, theme.ROAD, polygon)
    pygame.draw.lines(surface, theme.ROAD_EDGE, False, left_edge, 2)
    pygame.draw.lines(surface, theme.ROAD_EDGE, False, right_edge, 2)

    # Dashes advance with real distance travelled, so visual speed and
    # reported speed can never disagree.
    phase = state.distance_m % LANE_SPACING_M
    marker = -phase
    while marker < FAR_M:
        near = marker
        far = marker + LANE_LENGTH_M
        marker += LANE_SPACING_M
        if far < NEAR_M:
            continue

        near = max(near, NEAR_M)
        quad: list[tuple[float, float]] = []
        for depth, side in ((near, -1), (near, 1), (far, 1), (far, -1)):
            offset = curve * depth * depth * 0.012
            x, y = _project(depth, side * 0.14 - offset, horizon_y)
            quad.append((centre_x + x, y))
        if quad[0][1] > horizon_y + 1:
            pygame.draw.polygon(surface, theme.LANE_MARK, quad)

    pygame.draw.line(
        surface, theme.BORDER_SUBTLE, (scene_rect.left, horizon_y), (scene_rect.right, horizon_y)
    )
