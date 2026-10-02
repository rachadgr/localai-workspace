import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/errors.dart';
import '../services/api_client.dart';

/// Holds the authenticated session (bearer token + user), persisted locally.
///
/// Authentication mirrors the backend contract exactly: a JWT bearer token from
/// `/api/auth/login` or `/api/auth/register`, injected into every request.
class AuthStore extends ChangeNotifier {
  AuthStore(this._api);

  final AsafApi _api;
  static const String _kToken = 'asaf.token';
  static const String _kUser = 'asaf.user.email';
  static const String _kName = 'asaf.user.name';

  String? _token;
  String _email = '';
  String _displayName = '';
  bool _restoring = true;

  bool get isAuthenticated => _token != null && _token!.isNotEmpty;
  bool get restoring => _restoring;
  String get email => _email;
  String get displayName => _displayName.isEmpty ? _email : _displayName;

  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    _token = prefs.getString(_kToken);
    _email = prefs.getString(_kUser) ?? '';
    _displayName = prefs.getString(_kName) ?? '';
    if (_token != null && _token!.isNotEmpty) {
      _api.setToken(_token);
    }
    _restoring = false;
    notifyListeners();
  }

  Future<void> login(String email, String password) async {
    final res = await _api.login(email.trim(), password);
    await _persist(res);
  }

  Future<void> register(String email, String password, String displayName) async {
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
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kToken, _token!);
    await prefs.setString(_kUser, _email);
    await prefs.setString(_kName, _displayName);
    notifyListeners();
  }

  Future<void> logout() async {
    _token = null;
    _email = '';
    _displayName = '';
    _api.setToken(null);
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kUser);
    await prefs.remove(_kName);
    notifyListeners();
  }
}
