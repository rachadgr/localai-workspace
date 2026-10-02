import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../models/models.dart';
import '../services/api_client.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Image generation workspace.
///
/// Uses the real `/api/images` module. The backend reports `UNAVAILABLE` when no
/// image provider is configured — this screen shows that honestly rather than a
/// fabricated image.
class ImageScreen extends StatefulWidget {
  const ImageScreen({super.key});

  @override
  State<ImageScreen> createState() => _ImageScreenState();
}

class _ImageScreenState extends State<ImageScreen> {
  final _prompt = TextEditingController();
  String _action = 'brief';
  String _aspect = '1:1';
  int _variants = 1;
  bool _busy = false;
  ModuleResult? _result;
  String? _error;

  @override
  void dispose() {
    _prompt.dispose();
    super.dispose();
  }

  Future<void> _run() async {
    if (_prompt.text.trim().isEmpty) return;
    FocusScope.of(context).unfocus();
    final store = context.read<StudioStore>();
    final api = context.read<AsafApi>();
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
    });
    try {
      final projectId = await store.ensureActiveProject();
      if (projectId == null) {
        setState(() => _error = 'No active project — the backend did not return one.');
        return;
      }
      final res = await api.generateImage(
        description: _prompt.text.trim(),
        projectId: projectId,
        action: _action,
        aspectRatio: _aspect,
        variants: _variants,
      );
      setState(() => _result = ModuleResult.fromJson(res));
      if (store.activeProjectId != null) store.loadHistory();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Image request failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    final imageModels = store.modelsForTask('image_generation');
    final providerConfigured = store.health?.imageProvider ?? false;
    final configured = providerConfigured && imageModels.isNotEmpty;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Image generation',
          icon: Icons.image_outlined,
          action: StatusBadge(configured ? 'AVAILABLE' : 'UNAVAILABLE', dense: true),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!configured)
                InfoBanner(
                  color: AsafColors.statusMisconfigured,
                  icon: Icons.warning_amber,
                  message: providerConfigured
                      ? 'An image provider is configured but no image model passed the runtime check. Requests may be served by the provider directly.'
                      : 'No image provider is configured on the backend. Prompt/brief helpers work; actual image generation reports UNAVAILABLE.',
                ),
              const SizedBox(height: 14),
              TextField(
                controller: _prompt,
                minLines: 2,
                maxLines: 5,
                decoration: const InputDecoration(
                  labelText: 'Description',
                  hintText: 'A cinematic portrait of a robot artist in a neon studio…',
                ),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _dropdown('Action', _action, const ['brief', 'prompt', 'generate', 'variant'], (v) => setState(() => _action = v)),
                  _dropdown('Aspect', _aspect, const ['1:1', '16:9', '9:16', '4:3', '3:4'], (v) => setState(() => _aspect = v)),
                  _dropdown('Variants', '$_variants', const ['1', '2', '3', '4'], (v) => setState(() => _variants = int.parse(v))),
                ],
              ),
              const SizedBox(height: 18),
              ElevatedButton.icon(
                onPressed: _busy ? null : _run,
                icon: _busy
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.auto_awesome),
                label: Text(_busy ? 'Working…' : 'Run request'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (_error != null) InfoBanner(message: _error!, color: AsafColors.statusError, icon: Icons.error_outline),
        if (_result != null) _resultView(_result!),
        if (imageModels.isNotEmpty) ...[
          const SizedBox(height: 16),
          SectionCard(
            title: 'Compatible image models',
            icon: Icons.memory,
            child: Column(
              children: imageModels
                  .map((m) => ListTile(
                        contentPadding: EdgeInsets.zero,
                        dense: true,
                        title: Text(m.id, style: AsafText.body.copyWith(color: AsafColors.textPrimary)),
                        subtitle: Text(m.subtitle, style: AsafText.small),
                        trailing: StatusBadge(m.status, dense: true),
                      ))
                  .toList(),
            ),
          ),
        ],
      ],
    );
  }

  Widget _resultView(ModuleResult r) {
    return SectionCard(
      title: 'Result',
      icon: Icons.terminal,
      action: StatusBadge(r.success ? 'AVAILABLE' : 'UNAVAILABLE', dense: true),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (r.summary.isNotEmpty) ...[
            Text(r.summary, style: AsafText.body.copyWith(color: AsafColors.textPrimary)),
            const SizedBox(height: 12),
          ],
          if (r.error.isNotEmpty) InfoBanner(message: r.error, color: AsafColors.statusError, icon: Icons.error_outline),
          if (r.response.isNotEmpty) ...[
            const SizedBox(height: 8),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: AsafColors.surfaceAlt, borderRadius: BorderRadius.circular(10)),
              child: SelectableText(r.response, style: AsafText.mono),
            ),
          ],
          if (r.data['images'] is List && (r.data['images'] as List).isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Artifacts:', style: AsafText.small),
            const SizedBox(height: 6),
            ...(r.data['images'] as List).map((img) => Text(img.toString(), style: AsafText.small)),
          ],
        ],
      ),
    );
  }

  Widget _dropdown(String label, String value, List<String> options, ValueChanged<String> onChanged) {
    return SizedBox(
      width: 150,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: AsafText.small),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            decoration: BoxDecoration(
              color: AsafColors.surfaceAlt,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AsafColors.border),
            ),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<String>(
                value: value,
                isExpanded: true,
                dropdownColor: AsafColors.surfaceHigh,
                items: options.map((o) => DropdownMenuItem(value: o, child: Text(o, style: AsafText.body.copyWith(color: AsafColors.textPrimary)))).toList(),
                onChanged: (v) => onChanged(v ?? value),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
