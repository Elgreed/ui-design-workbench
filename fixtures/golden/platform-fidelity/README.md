# Platform fidelity fixtures

These source fixtures expose nested argument leakage, asymmetric padding, alpha colors, grid placement, CSS cascade priority and SwiftUI modifier order. `scripts/test_platform_fidelity.py` verifies source translation and provenance without requiring a platform runtime.

- Flutter: `lib/calibration_page.dart` can be mounted at 400 × 360 in a Flutter widget test. Load Arial in the test harness to compare typography with the Web/WPF fixtures; engine-default test fonts are not representative.
- Windows: load `Calibration.xaml` through WPF XamlReader, measure and arrange at 400 × 360 DIPs, then render through RenderTargetBitmap at 96 DPI. The XAML uses WPF, not WinUI.
- Web: render `index.html` in a browser at 400 × 360 CSS pixels and compare with its source projection.
- Apple: translate `CalibrationView.swift` for both SwiftUI targets. Frame/padding/background order and arguments are checked from source; no Apple-native screenshot is bundled. The unsupported star symbol remains an explicit gap.

Keep machine-specific font files, generated screenshots and capture outputs outside version control. Record runtime versions, viewport, font configuration and remaining gaps beside any comparison. These fixtures establish bounded regressions, not application-wide visual parity.
