import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Generation history — real task records from `/api/tasks`.
class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => context.read<StudioStore>().loadHistory());
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    return Column(
      children: [
        Container(
          color: AsafColors.surface,
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
          child: Row(
            children: [
              const Icon(Icons.history, size: 18, color: AsafColors.primaryLight),
              const SizedBox(width: 8),
              const Text('History', style: AsafText.h3),
              const Spacer(),
              IconButton(onPressed: store.loadHistory, icon: const Icon(Icons.refresh, size: 20), tooltip: 'Refresh'),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: store.history.isEmpty
              ? const EmptyState(icon: Icons.history, title: 'No generation history yet', message: 'Chat and generation tasks will appear here.')
              : RefreshIndicator(
                  color: AsafColors.primary,
                  onRefresh: store.loadHistory,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(16),
                    itemCount: store.history.length,
                    itemBuilder: (_, i) => _tile(context, store.history[i]),
                  ),
                ),
        ),
      ],
    );
  }

  Widget _tile(BuildContext context, HistoryTask t) {
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      child: ListTile(
        onTap: () => _openDetail(context, t),
        leading: CircleAvatar(
          backgroundColor: AsafColors.forStatus(t.status).withValues(alpha: 0.18),
          child: Icon(_iconFor(t.kind), size: 18, color: AsafColors.forStatus(t.status)),
        ),
        title: Text(t.title.isEmpty ? t.kind : t.title, style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SizedBox(height: 2),
            Text('${t.kind} · ${t.when}', style: AsafText.small, maxLines: 1, overflow: TextOverflow.ellipsis),
            Text(
              t.model.isEmpty ? 'model: —' : '${t.model}${t.provider.isEmpty ? '' : ' · ${t.provider}'}',
              style: AsafText.small,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
        trailing: StatusBadge(t.status, dense: true),
      ),
    );
  }

  IconData _iconFor(String kind) {
    switch (kind) {
      case 'chat':
        return Icons.forum;
      case 'image':
        return Icons.image;
      case 'agent':
        return Icons.auto_awesome;
      case 'research':
        return Icons.travel_explore;
      default:
        return Icons.bolt;
    }
  }

  void _openDetail(BuildContext context, HistoryTask t) {
    final api = context.read<AsafApi>();
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AsafColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.6,
        maxChildSize: 0.95,
        builder: (_, controller) => FutureBuilder<Map<String, dynamic>>(
          future: api.task(t.taskId),
          builder: (_, snap) {
            if (!snap.hasData && snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              final e = snap.error;
              return Padding(
                padding: const EdgeInsets.all(24),
                child: EmptyState(
                  icon: Icons.error_outline,
                  title: 'Cannot load task',
                  message: e is ApiException ? e.message : e.toString(),
                ),
              );
            }
            final d = snap.data!;
            final result = d['result'];
            final outputs = (t.outputs.isNotEmpty)
                ? t.outputs
                : (((d['output'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList());
            final model = t.model.isNotEmpty ? t.model : (d['model']?.toString() ?? '');
            final provider = t.provider.isNotEmpty ? t.provider : (d['provider']?.toString() ?? '');
            return ListView(
              controller: controller,
              padding: const EdgeInsets.all(20),
              children: [
                Row(
                  children: [
                    Expanded(child: Text(t.title.isEmpty ? t.kind : t.title, style: AsafText.h2)),
                    StatusBadge(t.status),
                  ],
                ),
                const SizedBox(height: 16),
                KeyValue('Generation id', t.taskId),
                KeyValue('Kind', d['kind']?.toString() ?? t.kind),
                KeyValue('Model', model.isEmpty ? '—' : model),
                KeyValue('Provider', provider.isEmpty ? '—' : provider),
                KeyValue('Project', d['project_id']?.toString() ?? t.projectId),
                KeyValue('Started', d['started_at']?.toString() ?? t.createdAt),
                KeyValue('Completed', d['completed_at']?.toString() ?? ''),
                if ((d['error']?.toString() ?? t.error).isNotEmpty)
                  KeyValue('Error', (d['error']?.toString() ?? t.error), valueColor: AsafColors.statusUnavailable),
                if (outputs.isNotEmpty) ...[
                  const SizedBox(height: 16),
                  Text('Output', style: AsafText.h3),
                  const SizedBox(height: 6),
                  ...outputs.map((o) {
                    final ref = ArtifactRef.fromJson(o);
                    return Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Row(
                        children: [
                          const Icon(Icons.insert_drive_file_outlined, size: 17, color: AsafColors.primaryLight),
                          const SizedBox(width: 10),
                          Expanded(child: Text(ref.name, style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis)),
                          Text(ref.sizeLabel, style: AsafText.small),
                        ],
                      ),
                    );
                  }),
                ],
                if (result != null) ...[
                  const SizedBox(height: 16),
                  Text('Stored result', style: AsafText.h3),
                  const SizedBox(height: 6),
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: AsafColors.surfaceAlt, borderRadius: BorderRadius.circular(10)),
                    child: SelectableText(const JsonEncoder.withIndent('  ').convert(result), style: AsafText.mono),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}
