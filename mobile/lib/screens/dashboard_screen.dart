import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_config.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Dashboard — the studio's operational overview.
///
/// Every section is driven by the real `/api/dashboard` aggregate: projects,
/// recent generations, recent documents, recent slides, runtime-confirmed models,
/// provider health, the runtime matrix and quick actions. Nothing is invented;
/// unavailable capabilities are shown as unavailable.
class DashboardScreen extends StatefulWidget {
  const DashboardScreen({super.key, this.onNavigate});

  /// Optional navigation hook (index into the shell) used by the quick actions
  /// and "see all" links. Provided by [HomeShell].
  final void Function(int index)? onNavigate;

  @override
  State<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends State<DashboardScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => context.read<StudioStore>().loadDashboard());
  }

  Future<void> _refresh(StudioStore store) async {
    await store.refreshAll();
    await store.loadDashboard();
    await store.loadHistory();
  }

  void _go(int index) => widget.onNavigate?.call(index);

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    final h = store.health;

    if (store.loading && h == null && store.dashboard.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }
    if (h == null && store.dashboard.isEmpty) {
      return EmptyState(
        icon: Icons.cloud_off,
        title: 'Cannot reach the backend',
        message: store.error ?? 'No data available from ${AppConfig.baseUrl}.',
        onRetry: () => _refresh(store),
      );
    }

    final usable = store.models.where((m) => m.usable).length;
    final availableProviders = store.providers.where((p) => p.status == 'AVAILABLE').length;
    final selectedTasks = store.router.values.where((r) => r.selected).length;

    return RefreshIndicator(
      color: AsafColors.primary,
      onRefresh: () => _refresh(store),
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (store.error != null) ...[
            InfoBanner(message: store.error!, color: AsafColors.statusError, icon: Icons.warning_amber),
            const SizedBox(height: 16),
          ],
          _hero(h?.status ?? 'UNAVAILABLE'),
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
              _metric('Projects', '${store.dashboard['projects_total'] ?? store.projects.length}', '${store.recentGenerations.length} recent task(s)', AsafColors.statusAvailable, Icons.folder_copy),
            ],
          ),
          const SizedBox(height: 16),
          _quickActions(store),
          const SizedBox(height: 16),
          _recentGenerations(store),
          const SizedBox(height: 16),
          _recentArtifacts(
            title: 'Recent documents',
            icon: Icons.description_outlined,
            items: store.recentDocuments,
            emptyLabel: 'No documents generated yet.',
          ),
          const SizedBox(height: 16),
          _recentArtifacts(
            title: 'Recent slides',
            icon: Icons.slideshow_outlined,
            items: store.recentSlides,
            emptyLabel: 'No slide decks generated yet.',
          ),
          const SizedBox(height: 16),
          _runtimeHealth(h),
          const SizedBox(height: 16),
          _taskRouting(store),
        ],
      ),
    );
  }

  // ------------------------------------------------------------- sections
  Widget _quickActions(StudioStore store) {
    final actions = store.quickActions;
    return SectionCard(
      title: 'Quick actions',
      icon: Icons.bolt,
      child: actions.isEmpty
          ? const Text('Quick actions unavailable — backend did not report any.', style: AsafText.body)
          : Wrap(
              spacing: 10,
              runSpacing: 10,
              children: actions.map((a) {
                final label = a['label']?.toString() ?? a['id']?.toString() ?? '';
                final enabled = a['enabled'] == true;
                final id = a['id']?.toString() ?? '';
                return Opacity(
                  opacity: enabled ? 1 : 0.5,
                  child: OutlinedButton.icon(
                    onPressed: enabled ? () => _runQuickAction(id) : null,
                    icon: Icon(_quickIcon(id), size: 16),
                    label: Text(label),
                  ),
                );
              }).toList(),
            ),
    );
  }

  void _runQuickAction(String id) {
    switch (id) {
      case 'chat':
        _go(1);
        break;
      case 'image':
        _go(2);
        break;
      case 'video':
        _go(3);
        break;
      case 'documents':
      case 'slides':
      case 'project':
        _go(4); // Project workspace
        break;
    }
  }

  IconData _quickIcon(String id) {
    switch (id) {
      case 'chat':
        return Icons.forum;
      case 'image':
        return Icons.image;
      case 'video':
        return Icons.movie;
      case 'documents':
        return Icons.description;
      case 'slides':
        return Icons.slideshow;
      case 'project':
        return Icons.folder_copy;
      default:
        return Icons.bolt;
    }
  }

  Widget _recentGenerations(StudioStore store) {
    final gens = store.recentGenerations;
    return SectionCard(
      title: 'Recent generations',
      icon: Icons.history,
      action: TextButton(onPressed: () => _go(7), child: const Text('History')),
      child: gens.isEmpty
          ? const Text('No tasks yet. Chat and generations will appear here.', style: AsafText.body)
          : Column(
              children: gens.take(6).map((g) {
                final t = HistoryTask.fromJson(g);
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      CircleAvatar(
                        radius: 14,
                        backgroundColor: AsafColors.forStatus(t.status).withValues(alpha: 0.18),
                        child: Icon(_kindIcon(t.kind), size: 15, color: AsafColors.forStatus(t.status)),
                      ),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              t.title.isEmpty ? t.kind : t.title,
                              style: AsafText.body.copyWith(color: AsafColors.textPrimary),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                            Text(
                              '${t.kind} · ${t.modelLabel} · ${t.when}',
                              style: AsafText.small,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ],
                        ),
                      ),
                      StatusBadge(t.status, dense: true),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }

  Widget _recentArtifacts({
    required String title,
    required IconData icon,
    required List<Map<String, dynamic>> items,
    required String emptyLabel,
  }) {
    return SectionCard(
      title: title,
      icon: icon,
      child: items.isEmpty
          ? Text(emptyLabel, style: AsafText.body)
          : Column(
              children: items.take(5).map((a) {
                final ref = ArtifactRef.fromJson(a);
                return Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(
                    children: [
                      Icon(icon, size: 17, color: AsafColors.primaryLight),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(ref.name, style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis),
                            Text('${ref.type} · ${ref.sizeLabel}', style: AsafText.small),
                          ],
                        ),
                      ),
                      StatusBadge('AVAILABLE', dense: true),
                    ],
                  ),
                );
              }).toList(),
            ),
    );
  }

  Widget _runtimeHealth(HealthInfo? h) {
    if (h == null) {
      return const SectionCard(title: 'Runtime health', icon: Icons.monitor_heart, child: Text('Health unavailable.', style: AsafText.body));
    }
    return SectionCard(
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
    );
  }

  Widget _taskRouting(StudioStore store) {
    return SectionCard(
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
    );
  }

  Widget _hero(String status) {
    final ok = status.toLowerCase() == 'ok';
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [AsafColors.primary.withValues(alpha: 0.25), AsafColors.surface],
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

  IconData _kindIcon(String kind) {
    switch (kind) {
      case 'chat':
        return Icons.forum;
      case 'image':
        return Icons.image;
      case 'video':
      case 'i2v':
        return Icons.movie;
      case 'docs':
      case 'document':
        return Icons.description;
      case 'slides':
      case 'presentation':
        return Icons.slideshow;
      case 'agent':
        return Icons.auto_awesome;
      case 'research':
        return Icons.travel_explore;
      default:
        return Icons.bolt;
    }
  }
}
