import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/test/test_flutter_secure_storage_platform.dart';
import 'package:flutter_secure_storage_platform_interface/flutter_secure_storage_platform_interface.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:asaf_ai/core/app_config.dart';
import 'package:asaf_ai/core/errors.dart';
import 'package:asaf_ai/services/api_client.dart';
import 'package:asaf_ai/state/auth_store.dart';

/// A real HTTP client backed by a deterministic in-memory FastAPI double — no
/// mocking of the app's own logic, only of the transport.
MockClient _backend({required String base}) {
  final users = <String, String>{}; // email -> password
  return MockClient((request) async {
    final path = request.url.path;
    if (path == '/api/health') {
      return http.Response(jsonEncode({'status': 'ok', 'app': 'ASAF AI', 'version': '1.0.0'}), 200,
          headers: {'content-type': 'application/json'});
    }
    if (path == '/api/auth/register') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final email = body['email'] as String;
      if (users.containsKey(email)) {
        return http.Response(jsonEncode({'detail': 'Email already registered'}), 409);
      }
      users[email] = body['password'] as String;
      return http.Response(
          jsonEncode({
            'access_token': 'jwt|$email',
            'token_type': 'bearer',
            'user': {'id': 'usr_1', 'email': email, 'display_name': body['display_name'] ?? 'User', 'role': 'user'},
          }),
          200);
    }
    if (path == '/api/auth/login') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      final email = body['email'] as String;
      if (users[email] != body['password']) {
        return http.Response(jsonEncode({'detail': 'Invalid credentials'}), 401);
      }
      return http.Response(
          jsonEncode({
            'access_token': 'jwt|$email',
            'token_type': 'bearer',
            'user': {'id': 'usr_1', 'email': email, 'display_name': 'User', 'role': 'user'},
          }),
          200);
    }
    if (path == '/api/auth/me') {
      final auth = request.headers['Authorization'] ?? request.headers['authorization'];
      if (auth == null || !auth.startsWith('Bearer jwt|')) {
        return http.Response(jsonEncode({'detail': 'Invalid token'}), 401);
      }
      final email = auth.substring('Bearer jwt|'.length);
      return http.Response(jsonEncode({'id': 'usr_1', 'email': email, 'display_name': 'User', 'role': 'user'}), 200);
    }
    return http.Response(jsonEncode({'detail': 'not found'}), 404);
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Map<String, String> secureData;
  late MockClient client;
  late AsafApi api;

  setUp(() async {
    secureData = <String, String>{};
    FlutterSecureStoragePlatform.instance = TestFlutterSecureStoragePlatform(secureData);
    // In-memory SharedPreferences (used only for the non-secret server URL).
    SharedPreferences.setMockInitialValues({});
    await AppConfig.setBaseUrl('https://demo.trycloudflare.com');
    client = _backend(base: AppConfig.baseUrl);
    api = AsafApi(client: client);
  });

  test('register stores the JWT in secure storage (not plaintext prefs)', () async {
    final auth = AuthStore(api);
    await auth.register('new@user.io', 'password123', 'New User');

    expect(auth.isAuthenticated, isTrue);
    expect(auth.email, 'new@user.io');
    expect(secureData['asaf.token'], 'jwt|new@user.io');
    expect(secureData.containsKey('asaf.user.email'), isTrue);
  });

  test('login success stores the token; wrong password surfaces 401', () async {
    final auth = AuthStore(api);
    await auth.register('a@b.io', 'password123', 'A');
    await auth.logout();
    expect(auth.isAuthenticated, isFalse);
    expect(secureData.containsKey('asaf.token'), isFalse);

    await auth.login('a@b.io', 'password123');
    expect(auth.isAuthenticated, isTrue);

    await auth.logout();
    await expectLater(
      () => auth.login('a@b.io', 'WRONG'),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', ApiErrorCode.authenticationRequired)),
    );
    expect(auth.isAuthenticated, isFalse);
  });

  test('logout clears secure storage and in-memory session', () async {
    final auth = AuthStore(api);
    await auth.register('x@y.io', 'password123', 'X');
    expect(auth.isAuthenticated, isTrue);

    await auth.logout();
    expect(auth.isAuthenticated, isFalse);
    expect(auth.email, isEmpty);
    expect(secureData.containsKey('asaf.token'), isFalse);
  });

  test('restore() keeps a valid session and validates it with /auth/me', () async {
    final auth1 = AuthStore(api);
    await auth1.register('persist@user.io', 'password123', 'Persist');
    // Simulate a fresh app launch: same secure storage, new store + api.
    final api2 = AsafApi(client: client);
    final auth2 = AuthStore(api2);
    await auth2.restore();

    expect(auth2.isAuthenticated, isTrue);
    expect(auth2.email, 'persist@user.io');
    expect(api2.token, isNotNull);
  });

  test('restore() clears an expired/invalid token (401 from /auth/me)', () async {
    // A stored token the backend will reject.
    secureData['asaf.token'] = 'expired-token';
    secureData['asaf.user.email'] = 'gone@user.io';
    final api2 = AsafApi(client: client);
    final auth2 = AuthStore(api2);
    await auth2.restore();

    expect(auth2.isAuthenticated, isFalse);
    expect(auth2.sessionNotice, isNotNull);
    expect(secureData.containsKey('asaf.token'), isFalse);
  });

  test('a 401 during an authenticated call signs the session out', () async {
    final auth = AuthStore(api);
    await auth.register('kick@user.io', 'password123', 'Kick');
    expect(auth.isAuthenticated, isTrue);

    // Simulate the token becoming invalid server-side.
    api.setToken('garbage');
    await expectLater(api.me(), throwsA(isA<ApiException>()));
    // onUnauthorized fired -> session cleared.
    expect(auth.isAuthenticated, isFalse);
    expect(auth.sessionNotice, isNotNull);
  });

  test('unreachable backend produces a structured "unreachable" error', () async {
    final dead = AsafApi(
      client: MockClient((_) async => throw http.ClientException('Connection refused')),
    );
    await expectLater(
      dead.health(),
      throwsA(isA<ApiException>().having((e) => e.code, 'code', ApiErrorCode.unreachable)),
    );
    expect(await dead.ping(), isFalse);
  });
}
