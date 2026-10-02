import 'package:flutter/material.dart';

/// ASAF AI — dark "AI Studio" design language.
///
/// A single source of truth for colours, spacing and typography so every screen
/// stays visually consistent (dark modern interface, clean typography,
/// model/runtime status accents).
class AsafColors {
  AsafColors._();

  // Core surfaces
  static const Color background = Color(0xFF0A0E17);
  static const Color surface = Color(0xFF111725);
  static const Color surfaceAlt = Color(0xFF161D2E);
  static const Color surfaceHigh = Color(0xFF1C2438);
  static const Color border = Color(0xFF232B40);

  // Brand
  static const Color primary = Color(0xFF6C5CE7);
  static const Color primaryLight = Color(0xFF8B7CF6);
  static const Color accent = Color(0xFF00D1B2);
  static const Color accentAlt = Color(0xFF3D9BFF);

  // Text
  static const Color textPrimary = Color(0xFFF3F5FA);
  static const Color textSecondary = Color(0xFFA4ADC4);
  static const Color textMuted = Color(0xFF6B7591);

  // Status vocabulary — mirrors the backend model/provider states exactly.
  static const Color statusAvailable = Color(0xFF22C55E);
  static const Color statusLoading = Color(0xFF3D9BFF);
  static const Color statusNotConfigured = Color(0xFF8A94AB);
  static const Color statusMisconfigured = Color(0xFFF59E0B);
  static const Color statusUnavailable = Color(0xFFEF4444);
  static const Color statusDisabled = Color(0xFF6B7591);
  static const Color statusError = Color(0xFFEF4444);

  /// Map a backend status string to its accent colour.
  static Color forStatus(String status) {
    switch (status.toUpperCase()) {
      case 'AVAILABLE':
      case 'ACTIVE':
      case 'COMPLETED':
      case 'SUCCESS':
      case 'OK':
        return statusAvailable;
      case 'LOADING':
      case 'RUNNING':
      case 'INSTALLED':
        return statusLoading;
      case 'NOT_CONFIGURED':
      case 'NOT_INSTALLED':
      case 'CATALOG':
        return statusNotConfigured;
      case 'MISCONFIGURED':
        return statusMisconfigured;
      case 'UNAVAILABLE':
        return statusUnavailable;
      case 'DISABLED':
        return statusDisabled;
      case 'ERROR':
      case 'FAILED':
        return statusError;
      default:
        return statusNotConfigured;
    }
  }
}

class AsafTheme {
  AsafTheme._();

  static ThemeData dark() {
    final base = ThemeData.dark(useMaterial3: true);
    return base.copyWith(
      scaffoldBackgroundColor: AsafColors.background,
      colorScheme: const ColorScheme.dark(
        primary: AsafColors.primary,
        secondary: AsafColors.accent,
        surface: AsafColors.surface,
        onPrimary: Colors.white,
        onSurface: AsafColors.textPrimary,
        error: AsafColors.statusError,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AsafColors.background,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: AsafColors.textPrimary,
          fontSize: 18,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.2,
        ),
      ),
      cardTheme: CardThemeData(
        color: AsafColors.surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: AsafColors.border),
        ),
      ),
      dividerTheme: const DividerThemeData(color: AsafColors.border, thickness: 1),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: AsafColors.surfaceAlt,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        hintStyle: const TextStyle(color: AsafColors.textMuted),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AsafColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AsafColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: AsafColors.primary, width: 1.4),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AsafColors.primary,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: AsafColors.primaryLight),
      ),
      chipTheme: base.chipTheme.copyWith(
        backgroundColor: AsafColors.surfaceHigh,
        side: const BorderSide(color: AsafColors.border),
        labelStyle: const TextStyle(color: AsafColors.textSecondary, fontSize: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      ),
      snackBarTheme: const SnackBarThemeData(
        backgroundColor: AsafColors.surfaceHigh,
        contentTextStyle: TextStyle(color: AsafColors.textPrimary),
        behavior: SnackBarBehavior.floating,
      ),
      textTheme: base.textTheme.apply(
        bodyColor: AsafColors.textPrimary,
        displayColor: AsafColors.textPrimary,
      ),
    );
  }

  static const Radius radius = Radius.circular(16);
  static const double gap = 16;
}

/// Convenience text styles reused across the studio.
class AsafText {
  AsafText._();

  static const TextStyle h1 = TextStyle(fontSize: 26, fontWeight: FontWeight.w700, color: AsafColors.textPrimary, letterSpacing: -0.4);
  static const TextStyle h2 = TextStyle(fontSize: 20, fontWeight: FontWeight.w700, color: AsafColors.textPrimary, letterSpacing: -0.2);
  static const TextStyle h3 = TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: AsafColors.textPrimary);
  static const TextStyle body = TextStyle(fontSize: 14, color: AsafColors.textSecondary, height: 1.45);
  static const TextStyle small = TextStyle(fontSize: 12, color: AsafColors.textMuted);
  static const TextStyle mono = TextStyle(fontFamily: 'monospace', fontSize: 13, color: AsafColors.textPrimary);
}
