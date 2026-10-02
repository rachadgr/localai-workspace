import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../l10n/generated/app_localizations.dart';

/// Persisted application locale (Arabic first, with English + system default).
///
/// The app defaults to Arabic (with full RTL) while still allowing the user to
/// switch to English or follow the device locale from the Settings screen.
class LocaleStore extends ChangeNotifier {
  static const _key = 'asaf.locale';

  /// `null` means "follow the system locale".
  Locale? _locale = const Locale('ar');
  bool _loaded = false;

  Locale? get locale => _locale;
  bool get loaded => _loaded;

  List<Locale> get supported => AsafLocalizations.supportedLocales;

  Future<void> load() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final code = prefs.getString(_key);
      if (code != null && code.isNotEmpty) {
        _locale = Locale(code);
      }
    } catch (_) {
      // Persistence is best-effort; fall back to the Arabic default.
    }
    _loaded = true;
    notifyListeners();
  }

  Future<void> setLocale(Locale? locale) async {
    _locale = locale;
    notifyListeners();
    try {
      final prefs = await SharedPreferences.getInstance();
      if (locale == null) {
        await prefs.remove(_key);
      } else {
        await prefs.setString(_key, locale.languageCode);
      }
    } catch (_) {
      // Best-effort persistence.
    }
  }
}

/// Convenience aliases for the generated localizations, so widgets can use a
/// short, consistent type name across the codebase.
typedef AsafLocalizations = AppLocalizations;

/// Localization delegates + supported locales for [MaterialApp.localizationsDelegates].
const List<LocalizationsDelegate<dynamic>> asafLocalizationsDelegates = <LocalizationsDelegate<dynamic>>[
  AsafLocalizations.delegate,
  GlobalMaterialLocalizations.delegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

/// Terse accessor: `context.l10n.navChat`.
extension AsafLocalizationX on BuildContext {
  AsafLocalizations get l10n => AsafLocalizations.of(this);
}
