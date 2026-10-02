import 'package:shared_preferences/shared_preferences.dart';

/// Centralised, user-editable runtime configuration.
///
/// The ASAF AI Android client talks to a real ASAF AI backend the user hosts.
/// The base URL is persisted locally so the app remembers it between launches.
/// No secret is stored here beyond the session bearer token (in [AuthStore]).
class AppConfig {
  AppConfig._();

  static const String _kBaseUrl = 'asaf.base_url';
  static const String _kDefaultBaseUrl = 'http://10.0.2.2:5060';

  /// Default backend base URL. `10.0.2.2` maps to the host machine from the
  /// Android emulator. The user can change it from Settings.
  static String _baseUrl = _kDefaultBaseUrl;

  static String get baseUrl => _baseUrl;

  /// Full API URL for a path such as `/api/health`.
  static String api(String path) {
    final root = _baseUrl.endsWith('/') ? _baseUrl.substring(0, _baseUrl.length - 1) : _baseUrl;
    final clean = path.startsWith('/') ? path : '/$path';
    return '$root$clean';
  }

  static Future<void> load() async {
    final prefs = await SharedPreferences.getInstance();
    _baseUrl = prefs.getString(_kBaseUrl) ?? _kDefaultBaseUrl;
  }

  static Future<void> setBaseUrl(String url) async {
    var trimmed = url.trim();
    if (trimmed.isEmpty) return;
    if (trimmed.endsWith('/')) trimmed = trimmed.substring(0, trimmed.length - 1);
    _baseUrl = trimmed;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBaseUrl, trimmed);
  }

  static Future<void> resetBaseUrl() async {
    _baseUrl = _kDefaultBaseUrl;
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kBaseUrl);
  }
}
