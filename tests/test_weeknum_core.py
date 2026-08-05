import unittest

from weeknum_core import (
    APP_VERSION,
    CalendarSizeMode,
    DISPLAY_VERSION,
    normalize_size_mode,
    parse_semver,
    resolve_build_version,
    resolve_calendar_dimensions,
)


class VersionTests(unittest.TestCase):
    def test_application_version_is_semantic(self):
        self.assertIsNotNone(parse_semver(APP_VERSION))

    def test_parse_semver_accepts_release_tag(self):
        self.assertEqual(parse_semver("v2.3.4"), (2, 3, 4))

    def test_parse_semver_rejects_invalid_value(self):
        self.assertIsNone(parse_semver("development"))

    def test_local_display_version_defaults_to_application_version(self):
        self.assertEqual(DISPLAY_VERSION, APP_VERSION)

    def test_stable_release_tag_matches_application_version(self):
        version = resolve_build_version(f"v{APP_VERSION}")
        self.assertEqual(version.file_version, (*parse_semver(APP_VERSION), 0))
        self.assertEqual(version.product_version, APP_VERSION)
        self.assertFalse(version.is_development)

    def test_development_release_tag_uses_revision_as_windows_build(self):
        version = resolve_build_version("dev0.21")
        self.assertEqual(version.file_version, (*parse_semver(APP_VERSION), 21))
        self.assertEqual(version.product_version, f"{APP_VERSION}-dev0.21")
        self.assertTrue(version.is_development)

    def test_mismatched_stable_release_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            resolve_build_version("3.0.0")

    def test_unknown_release_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            resolve_build_version("nightly")


class CalendarSizeTests(unittest.TestCase):
    def test_invalid_mode_falls_back_to_auto(self):
        self.assertEqual(normalize_size_mode("unexpected"), CalendarSizeMode.AUTO)

    def test_auto_uses_normal_on_large_screen(self):
        size = resolve_calendar_dimensions("auto", 3, 1720, 1440)
        self.assertEqual((size.width, size.height), (1060, 372))
        self.assertEqual(size.effective_mode, CalendarSizeMode.NORMAL)

    def test_auto_uses_compact_on_1280_by_1024_screen(self):
        size = resolve_calendar_dimensions("auto", 3, 1280, 1024)
        self.assertEqual((size.width, size.height), (900, 330))
        self.assertEqual(size.effective_mode, CalendarSizeMode.COMPACT)

    def test_auto_uses_compact_on_1366_by_768_screen(self):
        size = resolve_calendar_dimensions("auto", 3, 1366, 768)
        self.assertEqual((size.width, size.height), (900, 330))
        self.assertEqual(size.effective_mode, CalendarSizeMode.COMPACT)

    def test_explicit_normal_keeps_existing_size_when_it_fits(self):
        size = resolve_calendar_dimensions("normal", 3, 1280, 1024)
        self.assertEqual((size.width, size.height), (1060, 372))

    def test_explicit_compact_has_a_one_month_profile(self):
        size = resolve_calendar_dimensions("compact", 1, 1280, 1024)
        self.assertEqual((size.width, size.height), (340, 330))

    def test_every_profile_is_capped_to_the_work_area(self):
        size = resolve_calendar_dimensions("normal", 3, 800, 600)
        self.assertLessEqual(size.width, int(800 * 0.92))
        self.assertLessEqual(size.height, int(600 * 0.92))

    def test_invalid_month_count_uses_one_month_profile(self):
        size = resolve_calendar_dimensions("compact", None, 1280, 1024)
        self.assertEqual((size.width, size.height), (340, 330))


if __name__ == "__main__":
    unittest.main()
