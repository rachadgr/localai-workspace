import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Models screen — the real catalog merged with live runtime status.
///
/// Catalog metadata and runtime availability are shown separately so a listed
/// model is never mistaken for a usable one.
class ModelsScreen extends StatefulWidget {
  const ModelsScreen({super.key});

  @override
  State<ModelsScreen> createState() => _ModelsScreenState();
}

class _ModelsScreenState extends State<ModelsScreen> {
  String _filter = 'all';
  String _query = '';

  static const _filters = ['all', 'chat', 'reasoning', 'coding', 'vision', 'image', 'video', 'embedding'];

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    var models = store.models;
    if (_filter != 'all') {
      models = models.where((m) => m.category.contains(_filter) || m.kind == _filter).toList();
    }
    if (_query.isNotEmpty) {
      final q = _query.toLowerCase();
      models = models.where((m) => m.id.toLowerCase().contains(q) || m.provider.toLowerCase().contains(q)).toList();
    }

    return Column(
      children: [
        _toolbar(store),
        const Divider(height: 1),
        Expanded(
          child: store.loading && store.models.isEmpty
              ? const Center(child: CircularProgressIndicator())
              : models.isEmpty
                  ? const EmptyState(icon: Icons.memory, title: 'No models match', message: 'Adjust the filter or configure a provider on the backend.')
                  : RefreshIndicator(
                      color: AsafColors.primary,
                      onRefresh: store.refreshAll,
                      child: ListView.builder(
                        padding: const EdgeInsets.all(16),
                        itemCount: models.length,
                        itemBuilder: (_, i) => _card(models[i]),
                      ),
                    ),
        ),
      ],
    );
  }

  Widget _toolbar(StudioStore store) {
    final usable = store.models.where((m) => m.usable).length;
    return Container(
      color: AsafColors.surface,
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      child: Column(
        children: [
          Row(
            children: [
              const Icon(Icons.memory, size: 18, color: AsafColors.primaryLight),
              const SizedBox(width: 8),
              const Text('Models', style: AsafText.h3),
              const SizedBox(width: 10),
              Text('$usable usable / ${store.models.length} catalog', style: AsafText.small),
              const Spacer(),
              IconButton(onPressed: store.refreshAll, icon: const Icon(Icons.refresh, size: 20), tooltip: 'Refresh'),
            ],
          ),
          const SizedBox(height: 8),
          TextField(
            onChanged: (v) => setState(() => _query = v.trim()),
            decoration: const InputDecoration(
              isDense: true,
              hintText: 'Search models or providers…',
              prefixIcon: Icon(Icons.search, size: 18),
              contentPadding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            ),
          ),
          const SizedBox(height: 10),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: _filters
                  .map((f) => Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: Text(f),
                          selected: _filter == f,
                          onSelected: (_) => setState(() => _filter = f),
                          selectedColor: AsafColors.primary.withValues(alpha: 0.25),
                          labelStyle: TextStyle(color: _filter == f ? AsafColors.textPrimary : AsafColors.textSecondary, fontSize: 12),
                        ),
                      ))
                  .toList(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _card(ModelEntry m) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: () => _openDetail(m),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(m.name, style: AsafText.h3, maxLines: 1, overflow: TextOverflow.ellipsis),
                        const SizedBox(height: 2),
                        Text(m.subtitle, style: AsafText.small),
                      ],
                    ),
                  ),
                  StatusBadge(m.status, dense: true),
                ],
              ),
              const SizedBox(height: 12),
              Wrap(
                children: [
                  if (m.local) const Tag('local', color: AsafColors.accent),
                  if (m.reasoning) const Tag('reasoning'),
                  if (m.vision) const Tag('vision'),
                  if (m.tools) const Tag('tools'),
                  if (m.streaming) const Tag('streaming'),
                  ...m.capabilities.take(4).map((c) => Tag(c)),
                ],
              ),
              if (m.error.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(m.error, style: AsafText.small.copyWith(color: AsafColors.statusUnavailable), maxLines: 2, overflow: TextOverflow.ellipsis),
              ],
            ],
          ),
        ),
      ),
    );
  }

  void _openDetail(ModelEntry m) {
    final api = context.read<AsafApi>();
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: AsafColors.surface,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.7,
        maxChildSize: 0.95,
        builder: (_, controller) => _ModelDetail(m: m, api: api, store: context.read<StudioStore>(), scroll: controller),
      ),
    );
  }
}

class _ModelDetail extends StatefulWidget {
  const _ModelDetail({required this.m, required this.api, required this.store, required this.scroll});
  final ModelEntry m;
  final AsafApi api;
  final StudioStore store;
  final ScrollController scroll;

  @override
  State<_ModelDetail> createState() => _ModelDetailState();
}

class _ModelDetailState extends State<_ModelDetail> {
  bool _busy = false;
  Map<String, dynamic>? _health;
  String? _error;

  Future<void> _check() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      _health = await widget.store.checkModelHealth(widget.m.id);
    } on ApiException catch (e) {
      _error = e.message;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final m = widget.m;
    return ListView(
      controller: widget.scroll,
      padding: const EdgeInsets.all(20),
      children: [
        Row(
          children: [
            Expanded(child: Text(m.name, style: AsafText.h2)),
            StatusBadge(m.status),
          ],
        ),
        const SizedBox(height: 4),
        Text('${m.provider} · ${m.kind}', style: AsafText.small),
        const SizedBox(height: 16),
        Wrap(children: m.capabilities.map((c) => Tag(c)).toList()),
        const SizedBox(height: 16),
        KeyValue('Model id', m.id),
        KeyValue('Provider', m.provider),
        KeyValue('Kind', m.kind),
        KeyValue('Serving runtime', m.servingRuntime),
        KeyValue('Local', m.local ? 'yes' : 'no'),
        KeyValue('Runtime available', m.available ? 'yes' : 'no', valueColor: m.available ? AsafColors.statusAvailable : AsafColors.statusUnavailable),
        KeyValue('Context window', m.contextWindow > 0 ? '$m.contextWindow tokens' : '—'),
        KeyValue('Cost tier', m.costTier),
        if (m.error.isNotEmpty) KeyValue('Last error', m.error, valueColor: AsafColors.statusUnavailable),
        const SizedBox(height: 16),
        ElevatedButton.icon(
          onPressed: _busy ? null : _check,
          icon: _busy
              ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              : const Icon(Icons.favorite_border),
          label: Text(_busy ? 'Probing…' : 'Run real health check'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          InfoBanner(message: _error!, color: AsafColors.statusError),
        ],
        if (_health != null) ...[
          const SizedBox(height: 16),
          SectionCard(
            title: 'Health report',
            icon: Icons.monitor_heart,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                KeyValue('Status', _health!['status']?.toString() ?? '', valueColor: AsafColors.forStatus(_health!['status']?.toString() ?? '')),
                KeyValue('OK', _health!['ok'] == true ? 'yes' : 'no'),
                KeyValue('Latency', '${_health!['latency_ms'] ?? 0} ms'),
                if ((_health!['error']?.toString() ?? '').isNotEmpty) KeyValue('Error', _health!['error'].toString(), valueColor: AsafColors.statusUnavailable),
                if ((_health!['detail']?.toString() ?? '').isNotEmpty) KeyValue('Detail', _health!['detail'].toString()),
              ],
            ),
          ),
        ],
      ],
    );
  }
}
