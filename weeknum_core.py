from dataclasses import dataclass
from enum import Enum
import re


# Keep the application version in one place. The release workflow reads this
# value and verifies that it matches the release tag.
APP_VERSION = "2.0.0"


class CalendarSizeMode(str, Enum):
    AUTO = "auto"
    COMPACT = "compact"
    NORMAL = "normal"


@dataclass(frozen=True)
class CalendarDimensions:
    width: int
    height: int
    effective_mode: CalendarSizeMode


NORMAL_DIMENSIONS = {
    1: (380, 372),
    3: (1060, 372),
}

COMPACT_DIMENSIONS = {
    1: (340, 330),
    3: (900, 330),
}

AUTO_MAX_WIDTH_RATIO = 0.75
AUTO_MAX_HEIGHT_RATIO = 0.35
SCREEN_SAFETY_RATIO = 0.92


def parse_semver(value: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def normalize_size_mode(value) -> CalendarSizeMode:
    if isinstance(value, CalendarSizeMode):
        return value
    try:
        return CalendarSizeMode(str(value).strip().lower())
    except (TypeError, ValueError):
        return CalendarSizeMode.AUTO


def resolve_calendar_dimensions(
    mode,
    months_count: int,
    available_width: int,
    available_height: int,
) -> CalendarDimensions:
    """Resolve a predictable calendar size for the current screen.

    Auto chooses between curated Normal and Compact profiles. Every mode is
    additionally capped so the window cannot be larger than the work area.
    """
    try:
        months = 3 if int(months_count) == 3 else 1
    except (TypeError, ValueError):
        months = 1
    selected_mode = normalize_size_mode(mode)
    available_width = max(1, int(available_width))
    available_height = max(1, int(available_height))

    effective_mode = selected_mode
    if selected_mode == CalendarSizeMode.AUTO:
        normal_width, normal_height = NORMAL_DIMENSIONS[months]
        normal_fits_comfortably = (
            normal_width <= available_width * AUTO_MAX_WIDTH_RATIO
            and normal_height <= available_height * AUTO_MAX_HEIGHT_RATIO
        )
        effective_mode = (
            CalendarSizeMode.NORMAL
            if normal_fits_comfortably
            else CalendarSizeMode.COMPACT
        )

    dimensions = (
        NORMAL_DIMENSIONS
        if effective_mode == CalendarSizeMode.NORMAL
        else COMPACT_DIMENSIONS
    )
    desired_width, desired_height = dimensions[months]

    max_width = max(1, int(available_width * SCREEN_SAFETY_RATIO))
    max_height = max(1, int(available_height * SCREEN_SAFETY_RATIO))
    return CalendarDimensions(
        width=min(desired_width, max_width),
        height=min(desired_height, max_height),
        effective_mode=effective_mode,
    )
