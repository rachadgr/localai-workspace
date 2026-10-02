import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:asaf_ai/core/theme.dart';
import 'package:asaf_ai/models/models.dart';
import 'package:asaf_ai/widgets/common.dart';

void main() {
  group('status colour vocabulary', () {
    test('maps backend statuses to stable colours', () {
      expect(AsafColors.forStatus('AVAILABLE'), AsafColors.statusAvailable);
      expect(AsafColors.forStatus('NOT_CONFIGURED'), AsafColors.statusNotConfigured);
      expect(AsafColors.forStatus('UNAVAILABLE'), AsafColors.statusUnavailable);
      expect(AsafColors.forStatus('MISCONFIGURED'), AsafColors.statusMisconfigured);
      expect(AsafColors.forStatus('unknown-thing'), AsafColors.statusNotConfigured);
    });
  });

  group('ModelEntry', () {
    test('parses a catalog entry and never treats a catalog model as usable', () {
      final m = ModelEntry.fromJson({
        'id': 'gpt-x',
        'name': 'GPT-X',
        'provider': 'openai_compatible',
        'kind': 'chat',
        'capabilities': ['chat', 'streaming'],
        'category': ['chat'],
        'modality': ['text'],
        'status': 'NOT_CONFIGURED',
        'available': false,
        'local': false,
      });
      expect(m.id, 'gpt-x');
      expect(m.name, 'GPT-X');
      expect(m.usable, isFalse);
      expect(m.subtitle, contains('openai_compatible'));
    });

    test('marks a probe-confirmed model as usable', () {
      final m = ModelEntry.fromJson({'id': 'llama3', 'provider': 'ollama', 'kind': 'chat', 'status': 'AVAILABLE', 'available': true});
      expect(m.usable, isTrue);
    });
  });

  testWidgets('StatusBadge renders the status label', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: StatusBadge('AVAILABLE'))));
    expect(find.text('AVAILABLE'), findsOneWidget);
  });
}
