import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Providers / Runtime screen — real provider status, connection testing and the
/// runtime capability matrix. Secrets are never returned by the backend and are
/// never displayed here.
class ProvidersScreen extends StatelessWidget {
  const ProvidersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    return RefreshIndicator(
      color: AsafColors.primary,
      onRefresh: store.refreshAll,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SectionCard(
            title: 'Providers',
            icon: Icons.hub,
            action: Text('${store.providers.length}', style: AsafText.small),
            child: store.providers.isEmpty
                ? const Text('No provider reported by the backend.', style: AsafText.body)
                : Column(children: store.providers.map((p) => _providerTile(context, p)).toList()),
          ),
          const SizedBox(height: 16),
          SectionCard(
            title: 'Runtime capability matrix',
            icon: Icons.dns,
            child: store.runtimes.isEmpty
                ? const Text('No runtime matrix available.', style: AsafText.body)
                : Column(children: store.runtimes.map((r) => _runtimeTile(r)).toList()),
          ),
        ],
      ),
    );
  }

  Widget _providerTile(BuildContext context, ProviderEntry p) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AsafColors.surfaceAlt,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AsafColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(p.local ? Icons.computer : Icons.cloud_outlined, size: 18, color: AsafColors.primaryLight),
              const SizedBox(width: 8),
              Expanded(child: Text(p.name, style: AsafText.h3)),
              StatusBadge(p.status, dense: true),
            ],
          ),
          const SizedBox(height: 8),
          KeyValue('Configured', p.configured ? 'yes' : 'no', valueColor: p.configured ? AsafColors.statusAvailable : AsafColors.statusMisconfigured),
          KeyValue('Type', p.local ? 'local' : 'remote'),
          if (p.endpoint.isNotEmpty) KeyValue('Endpoint', p.endpoint),
          if (p.error.isNotEmpty) KeyValue('Last error', p.error, valueColor: AsafColors.statusUnavailable),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: () => _test(context, p),
              icon: const Icon(Icons.network_check, size: 16),
              label: const Text('Test connection'),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _test(BuildContext context, ProviderEntry p) async {
    final store = context.read<StudioStore>();
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => const Center(child: CircularProgressIndicator()),
    );
    try {
      final res = await store.testProvider(p.name);
      if (!context.mounted) return;
      Navigator.of(context).pop();
      final results = (res['results'] as List?) ?? [];
      showDialog<void>(
        context: context,
        builder: (_) => AlertDialog(
          backgroundColor: AsafColors.surface,
          title: Text('Connection test · ${p.name}'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: results.isEmpty
                  ? [const Text('No results returned.', style: AsafText.body)]
                  : results.map((r) {
                      final m = (r as Map).cast<String, dynamic>();
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(child: Text(m['provider']?.toString() ?? '', style: AsafText.h3)),
                                StatusBadge(m['status']?.toString() ?? 'UNKNOWN', dense: true),
                              ],
                            ),
                            KeyValue('Model', m['model']?.toString() ?? ''),
                            KeyValue('Latency', '${m['latency_ms'] ?? 0} ms'),
                            if ((m['error']?.toString() ?? '').isNotEmpty)
                              KeyValue('Error', m['error'].toString(), valueColor: AsafColors.statusUnavailable),
                          ],
                        ),
                      );
                    }).toList(),
            ),
          ),
          actions: [TextButton(onPressed: () => Navigator.of(context).pop(), child: const Text('Close'))],
        ),
      );
    } on ApiException catch (e) {
      if (!context.mounted) return;
      Navigator.of(context).pop();
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: AsafColors.statusError));
    }
  }

  Widget _runtimeTile(Map<String, dynamic> r) {
    final label = r['label']?.toString() ?? r['id']?.toString() ?? r['runtime']?.toString() ?? 'runtime';
    final supported = r['supported'] != false;
    final adapter = r['adapter']?.toString() ?? '';
    final caps = (r['capabilities'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[];
    final reason = r['reason']?.toString() ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AsafColors.surfaceAlt,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AsafColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(label, style: AsafText.h3)),
              StatusBadge(supported ? 'AVAILABLE' : 'NOT_CONFIGURED', dense: true),
            ],
          ),
          const SizedBox(height: 8),
          KeyValue('Adapter', adapter.isEmpty ? 'none wired' : adapter),
          KeyValue('Local', r['local'] == true ? 'yes' : 'no'),
          if (caps.isNotEmpty) KeyValue('Capabilities', caps.join(', ')),
          if (reason.isNotEmpty) KeyValue('Reason', reason, valueColor: AsafColors.statusMisconfigured),
        ],
      ),
    );
  }
}
