import 'package:flutter/foundation.dart' show kIsWeb, defaultTargetPlatform, TargetPlatform;
import 'package:shared_preferences/shared_preferences.dart';

/// Centralised, user-editable runtime configuration.
///
/// The ASAF AI Android client talks to a real ASAF AI backend the user hosts
/// (e.g. a Kaggle/Colab notebook, a LAN machine, or a container). The backend
/// base URL is resolved in this order:
///
///   1. an explicit value saved by the user (Settings / sign-in screen), or
///   2. the compile-time default injected at build time with
///      `--dart-define=ASAF_API_BASE_URL=https://<tunnel>.trycloudflare.com`, or
///   3. a **development-only** loopback fallback (the Android emulator's
///      `10.0.2.2` alias, or `localhost` elsewhere).
///
/// The production address is therefore never hardcoded: a new tunnel URL can be
/// supplied without touching the source, either at build time (dart-define) or
/// at runtime (the in-app field). Only the non-secret base URL is stored in
/// [SharedPreferences]; the session bearer token lives in secure storage
/// (see `AuthStore`).
class AppConfig {
  AppConfig._();

  static const String _kBaseUrl = 'asaf.base_url';

  /// Compile-time default injected via
  /// `--dart-define=ASAF_API_BASE_URL=<url>`. Empty when not provided.
  static const String _compileTimeBaseUrl =
      String.fromEnvironment('ASAF_API_BASE_URL', defaultValue: '');

  /// Development-only loopback fallback.
  ///
  /// `10.0.2.2` is the Android **emulator's** alias for the host machine; it is
  /// never a production address. On a physical device the user must supply the
  /// real server URL (tunnel / LAN IP) in the app, or it must be baked in with
  /// `--dart-define`.
  static String get _devFallback {
    if (kIsWeb) return 'http://localhost:5060';
    if (defaultTargetPlatform == TargetPlatform.android) return 'http://10.0.2.2:5060';
    return 'http://localhost:5060';
  }

  /// The default URL used when neither the user nor the build supplied one.
  static String get defaultBaseUrl =>
      _compileTimeBaseUrl.isNotEmpty ? normalize(_compileTimeBaseUrl) : _devFallback;

  /// True when a compile-time URL was baked in at build time.
  static bool get hasCompileTimeDefault => _compileTimeBaseUrl.isNotEmpty;

  static String _baseUrl = defaultBaseUrl;

  static String get baseUrl => _baseUrl;

  /// Full API URL for a path such as `/api/health`.
  static String api(String path) {
    final root = _baseUrl.endsWith('/') ? _baseUrl.substring(0, _baseUrl.length - 1) : _baseUrl;
    final clean = path.startsWith('/') ? path : '/$path';
    return '$root$clean';
  }

  /// Normalises a user-entered URL: trims, adds a scheme when missing, and
  /// strips trailing slashes. Only `http`/`https` are accepted.
  static String normalize(String url) {
    var trimmed = url.trim();
    if (trimmed.isEmpty) return trimmed;
    if (!trimmed.contains('://')) {
      // Default to https for public hosts; http for loopback/LAN literals.
      final isLoopback = trimmed.startsWith('localhost') ||
          trimmed.startsWith('127.') ||
          trimmed.startsWith('10.') ||
          trimmed.startsWith('192.168.') ||
          RegExp(r'^172\.(1[6-9]|2\d|3[01])\.').hasMatch(trimmed);
      trimmed = '${isLoopback ? 'http' : 'https'}://$trimmed';
    }
    while (trimmed.endsWith('/')) {
      trimmed = trimmed.substring(0, trimmed.length - 1);
    }
    return trimmed;
  }

  /// Lightweight validity check used by the UI before saving.
  static bool isValid(String url) {
    final n = normalize(url);
    final uri = Uri.tryParse(n);
    if (uri == null || uri.host.isEmpty) return false;
    return uri.scheme == 'http' || uri.scheme == 'https';
  }

  static Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString(_kBaseUrl);
    _baseUrl = (stored != null && stored.isNotEmpty) ? normalize(stored) : defaultBaseUrl;
  }

  static Future<void> setBaseUrl(String url) async {
    final normalized = normalize(url);
    if (normalized.isEmpty) return;
    _baseUrl = normalized;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBaseUrl, normalized);
  }

  static Future<void> resetBaseUrl() async {
    _baseUrl = defaultBaseUrl;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kBaseUrl);
  }
}
