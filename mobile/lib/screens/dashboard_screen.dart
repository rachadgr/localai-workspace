import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_config.dart';
import '../core/theme.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Dashboard — the studio's operational overview, entirely driven by live
/// backend data (health, models, providers, routing).
class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    final h = store.health;

    if (store.loading && h == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (h == null) {
      return EmptyState(
        icon: Icons.cloud_off,
        title: 'Cannot reach the backend',
        message: store.error ?? 'No health data available from ${AppConfig.baseUrl}.',
        onRetry: store.refreshAll,
      );
    }

    final usable = store.models.where((m) => m.usable).length;
    final availableProviders = store.providers.where((p) => p.status == 'AVAILABLE').length;
    final selectedTasks = store.router.values.where((r) => r.selected).length;

    return RefreshIndicator(
      color: AsafColors.primary,
      onRefresh: () async {
        await store.refreshAll();
        await store.loadHistory();
      },
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (store.error != null) ...[
            InfoBanner(message: store.error!, color: AsafColors.statusError, icon: Icons.warning_amber),
            const SizedBox(height: 16),
          ],
          _hero(h.status),
          const SizedBox(height: 16),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 12,
            crossAxisSpacing: 12,
            childAspectRatio: 1.35,
            children: [
              _metric('Models usable', '$usable', 'of ${store.models.length} in catalog', AsafColors.accent, Icons.memory),
              _metric('Providers online', '$availableProviders', 'of ${store.providers.length} configured', AsafColors.accentAlt, Icons.hub),
              _metric('Tasks routeable', '$selectedTasks', 'of ${store.router.length} task classes', AsafColors.primaryLight, Icons.alt_route),
              _metric('Chat available', '${h.chatAvailable}', 'live chat-capable models', AsafColors.statusAvailable, Icons.forum),
            ],
          ),
          const SizedBox(height: 16),
          SectionCard(
            title: 'Runtime health',
            icon: Icons.monitor_heart,
            child: Column(
              children: [
                KeyValue('Backend', h.app.isEmpty ? '—' : '${h.app} v${h.version}'),
                KeyValue('Environment', h.environment),
                KeyValue('Database', h.database),
                KeyValue('Overall status', h.status, valueColor: AsafColors.forStatus(h.status.toUpperCase() == 'OK' ? 'AVAILABLE' : 'UNAVAILABLE')),
                KeyValue('Model layer', h.modelsStatus, valueColor: AsafColors.forStatus(h.modelsStatus)),
                KeyValue('Image provider', h.imageProvider ? 'configured' : 'not configured'),
                KeyValue('Network tools', h.networkTools ? 'enabled' : 'disabled'),
                KeyValue('Code execution', h.codeExecution ? 'enabled' : 'disabled'),
              ],
            ),
          ),
          const SizedBox(height: 16),
          SectionCard(
            title: 'Task routing',
            icon: Icons.alt_route,
            child: store.router.isEmpty
                ? const Text('Routing diagnostics unavailable.', style: AsafText.body)
                : Column(
                    children: store.router.values
                        .map((r) => Padding(
                              padding: const EdgeInsets.symmetric(vertical: 6),
                              child: Row(
                                children: [
                                  SizedBox(width: 96, child: Text(r.task, style: AsafText.body.copyWith(color: AsafColors.textPrimary))),
                                  Expanded(
                                    child: Text(
                                      r.selected ? '${r.model} · ${r.provider}' : (r.reason.isEmpty ? r.outcome : r.reason),
                                      style: AsafText.small,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                  StatusBadge(r.selected ? 'AVAILABLE' : 'UNAVAILABLE', dense: true),
                                ],
                              ),
                            ))
                        .toList(),
                  ),
          ),
        ],
      ),
    );
  }

  Widget _hero(String status) {
    final ok = status.toLowerCase() == 'ok';
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            AsafColors.primary.withValues(alpha: 0.25),
            AsafColors.surface,
          ],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AsafColors.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('ASAF AI Studio', style: AsafText.h1),
                const SizedBox(height: 6),
                Text(
                  ok ? 'All systems report healthy.' : 'Studio is running in a degraded state — see the details below.',
                  style: AsafText.body,
                ),
                const SizedBox(height: 12),
                StatusBadge(ok ? 'AVAILABLE' : 'UNAVAILABLE'),
              ],
            ),
          ),
          const Icon(Icons.auto_awesome, size: 46, color: AsafColors.primaryLight),
        ],
      ),
    );
  }

  Widget _metric(String label, String value, String sub, Color color, IconData icon) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Row(
              children: [
                Icon(icon, size: 18, color: color),
                const Spacer(),
                Text(value, style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: color)),
              ],
            ),
            const SizedBox(height: 8),
            Text(label, style: AsafText.body.copyWith(color: AsafColors.textPrimary, fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text(sub, style: AsafText.small, maxLines: 2, overflow: TextOverflow.ellipsis),
          ],
        ),
      ),
    );
  }
}
