import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../core/errors.dart';
import '../services/api_client.dart';

/// Holds the authenticated session (bearer token + user).
///
/// The JWT and the user's identity are stored in **secure storage**
/// (`flutter_secure_storage`: Android Keystore-backed EncryptedSharedPreferences,
/// Keychain on Apple, libsecret on Linux, WebCrypto on web) — never in plaintext
/// `SharedPreferences`. Only the non-secret server URL lives in
/// `SharedPreferences` (see `AppConfig`).
///
/// Authentication mirrors the backend contract exactly: a JWT bearer token from
/// `/api/auth/login` or `/api/auth/register`, injected into every request. When
/// the backend ever answers a request with `401` (expired or invalidated token),
/// [AsafApi.onUnauthorized] fires and the session is cleared so the UI returns
/// to the sign-in screen — no mock, no bypass.
class AuthStore extends ChangeNotifier {
  AuthStore(this._api) {
    _api.onUnauthorized = _onUnauthorized;
  }

  final AsafApi _api;

  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(),
  );
  static const String _kToken = 'asaf.token';
  static const String _kUser = 'asaf.user.email';
  static const String _kName = 'asaf.user.name';

  String? _token;
  String _email = '';
  String _displayName = '';
  bool _restoring = true;
  String? _sessionNotice;

  bool get isAuthenticated => _token != null && _token!.isNotEmpty;
  bool get restoring => _restoring;
  String get email => _email;
  String get displayName => _displayName.isEmpty ? _email : _displayName;

  /// Set when the session was ended by an expired/invalid token, so the sign-in
  /// screen can explain why the user was returned to it.
  String? get sessionNotice => _sessionNotice;
  void clearSessionNotice() {
    _sessionNotice = null;
  }

  /// Restores a persisted session (if any) and validates it against the backend.
  ///
  /// A `401` clears the stored session (expired token); a transport error keeps
  /// it (the server may simply be temporarily unreachable — logging the user out
  /// would be wrong).
  Future<void> restore() async {
    try {
      _token = await _storage.read(key: _kToken);
      _email = await _storage.read(key: _kUser) ?? '';
      _displayName = await _storage.read(key: _kName) ?? '';
    } catch (_) {
      _token = null;
    }

    if (_token != null && _token!.isNotEmpty) {
      _api.setToken(_token);
      try {
        final user = await _api.me();
        _email = user['email']?.toString() ?? _email;
        _displayName = user['display_name']?.toString() ?? _displayName;
        await _persistIdentity();
      } on ApiException catch (e) {
        if (e.code == ApiErrorCode.authenticationRequired || e.statusCode == 401) {
          await _clearSession(notice: 'Your session expired. Please sign in again.');
        }
        // Network/timeout: keep the token; the UI surfaces a connectivity banner.
      }
    }

    _restoring = false;
    notifyListeners();
  }

  Future<void> login(String email, String password) async {
    _sessionNotice = null;
    final res = await _api.login(email.trim(), password);
    await _persist(res);
  }

  Future<void> register(String email, String password, String displayName) async {
    _sessionNotice = null;
    final res = await _api.register(email.trim(), password, displayName);
    await _persist(res);
  }

  Future<void> _persist(Map<String, dynamic> res) async {
    _token = res['access_token']?.toString();
    final user = (res['user'] as Map?)?.cast<String, dynamic>() ?? {};
    _email = user['email']?.toString() ?? '';
    _displayName = user['display_name']?.toString() ?? '';
    if (_token == null || _token!.isEmpty) {
      throw ApiException(ApiErrorCode.authenticationRequired, 'The server did not return a valid session token.');
    }
    _api.setToken(_token);
    await _storage.write(key: _kToken, value: _token!);
    await _persistIdentity();
    notifyListeners();
  }

  Future<void> _persistIdentity() async {
    await _storage.write(key: _kUser, value: _email);
    await _storage.write(key: _kName, value: _displayName);
  }

  /// Signs the user out locally (the backend issues stateless JWTs; discarding
  /// the token on the client ends the session).
  Future<void> logout() async {
    await _clearSession();
    notifyListeners();
  }

  void _onUnauthorized() {
    // Called from AsafApi when the backend rejects the bearer token.
    if (isAuthenticated) {
      _clearSession(notice: 'Your session expired. Please sign in again.');
    }
  }

  Future<void> _clearSession({String? notice}) async {
    _token = null;
    _email = '';
    _displayName = '';
    if (notice != null) _sessionNotice = notice;
    _api.setToken(null);
    try {
      await _storage.delete(key: _kToken);
      await _storage.delete(key: _kUser);
      await _storage.delete(key: _kName);
    } catch (_) {
      // Secure storage can be unavailable in some test environments.
    }
    notifyListeners();
  }
}
