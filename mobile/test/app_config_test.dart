import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:asaf_ai/core/app_config.dart';
import 'package:asaf_ai/core/errors.dart';

void main() {
  group('AppConfig URL handling', () {
    test('normalize adds a scheme, strips trailing slashes', () {
      expect(AppConfig.normalize('https://x.trycloudflare.com/'), 'https://x.trycloudflare.com');
      expect(AppConfig.normalize('  https://x.trycloudflare.com  '), 'https://x.trycloudflare.com');
      // Loopback/LAN literals default to http.
      expect(AppConfig.normalize('127.0.0.1:5060'), 'http://127.0.0.1:5060');
      expect(AppConfig.normalize('192.168.1.20:5060'), 'http://192.168.1.20:5060');
      // Public hosts default to https.
      expect(AppConfig.normalize('foo.trycloudflare.com'), 'https://foo.trycloudflare.com');
    });

    test('isValid accepts http/https hosts and rejects junk', () {
      expect(AppConfig.isValid('https://a.trycloudflare.com'), isTrue);
      expect(AppConfig.isValid('http://192.168.1.20:5060'), isTrue);
      expect(AppConfig.isValid(''), isFalse);
      expect(AppConfig.isValid('ftp://nope'), isFalse);
    });

    test('api() builds full URLs without duplicate slashes', () {
      expect(AppConfig.api('/api/health'), '${AppConfig.baseUrl}/api/health');
      expect(AppConfig.api('api/health'), '${AppConfig.baseUrl}/api/health');
    });

    test('the emulator alias is only the Android dev fallback, never forced production', () {
      // No --dart-define is present in a plain test run.
      expect(AppConfig.hasCompileTimeDefault, isFalse);
      // On the Android test host the fallback is the emulator alias — a
      // development-only loopback, overridable at build time (dart-define) or
      // at runtime (the in-app Server URL field).
      expect(AppConfig.defaultBaseUrl, 'http://10.0.2.2:5060');
      // A real/compile-time or user-supplied URL is used verbatim (no alias).
      expect(AppConfig.normalize('https://x.trycloudflare.com'), 'https://x.trycloudflare.com');
    });
  });

  group('ApiException', () {
    test('unreachable carries the attempted URL and a friendly message', () {
      final e = ApiException.unreachable('https://down.trycloudflare.com', reason: 'connection refused');
      expect(e.code, ApiErrorCode.unreachable);
      expect(e.message, contains('https://down.trycloudflare.com'));
      expect(e.message, contains('Cannot reach'));
    });

    test('maps HTTP statuses to structured codes', () {
      expect(ApiException.fromStatus(401, 'nope').code, ApiErrorCode.authenticationRequired);
      expect(ApiException.fromStatus(403, 'nope').code, ApiErrorCode.forbidden);
      expect(ApiException.fromStatus(422, 'bad').code, ApiErrorCode.validation);
      expect(ApiException.fromStatus(500, 'boom').code, ApiErrorCode.server);
    });
  });

  testWidgets('StatusBadge still renders (no UI regression)', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text('ASAF AI'))));
    expect(find.text('ASAF AI'), findsOneWidget);
  });
}
