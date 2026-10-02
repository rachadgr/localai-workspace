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
/// fabricated image. The model selector lists only image models that genuinely
/// passed the backend's runtime gate.
class ImageScreen extends StatefulWidget {
  const ImageScreen({super.key});

  @override
  State<ImageScreen> createState() => _ImageScreenState();
}

class _ImageScreenState extends State<ImageScreen> {
  final _prompt = TextEditingController();
  final _style = TextEditingController();
  String _action = 'brief';
  String _aspect = '1:1';
  int _variants = 1;
  String _model = '';
  bool _busy = false;
  GenerationResult? _result;
  String? _error;

  @override
  void dispose() {
    _prompt.dispose();
    _style.dispose();
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
        style: _style.text.trim(),
        aspectRatio: _aspect,
        variants: _variants,
        model: _model,
      );
      setState(() => _result = GenerationResult.fromJson(res));
      await store.loadHistory();
    } on ApiException catch (e) {
      setState(() => _error = '${errorCodeLabel(e.code)}: ${e.message}');
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
    final configured = providerConfigured || imageModels.isNotEmpty;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Image generation',
          icon: Icons.image_outlined,
          action: StatusBadge(configured ? 'AVAILABLE' : 'NOT_CONFIGURED', dense: true),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!configured)
                const InfoBanner(
                  color: AsafColors.statusMisconfigured,
                  icon: Icons.warning_amber,
                  message: 'No image provider is configured on the backend. Prompt/brief helpers work; actual image generation reports UNAVAILABLE (never a fabricated image).',
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
              TextField(
                controller: _style,
                decoration: const InputDecoration(labelText: 'Style (optional)', hintText: 'photorealistic, 35mm, soft light'),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _dropdown('Action', _action, const ['brief', 'prompt', 'generate', 'variant'], (v) => setState(() => _action = v)),
                  _dropdown('Aspect', _aspect, const ['1:1', '16:9', '9:16', '4:3', '3:4'], (v) => setState(() => _aspect = v)),
                  _dropdown('Variants', '$_variants', const ['1', '2', '3', '4'], (v) => setState(() => _variants = int.parse(v))),
                  _modelDropdown(imageModels),
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
        const SizedBox(height: 16),
        SectionCard(
          title: 'Compatible image models',
          icon: Icons.memory,
          child: imageModels.isEmpty
              ? const Text('No image model passed the runtime gate. Configure LAIW_IMAGE_PROVIDER_URL or install a local image model.', style: AsafText.body)
              : Column(
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
    );
  }

  Widget _resultView(GenerationResult r) {
    return SectionCard(
      title: 'Result',
      icon: Icons.terminal,
      action: StatusBadge(r.success ? 'AVAILABLE' : (r.unavailable ? 'UNAVAILABLE' : 'ERROR'), dense: true),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          KeyValue('Task id', r.taskId),
          if (r.summary.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(r.summary, style: AsafText.body.copyWith(color: AsafColors.textPrimary)),
          ],
          if (r.error.isNotEmpty) ...[
            const SizedBox(height: 10),
            InfoBanner(message: r.error, color: AsafColors.statusError, icon: Icons.error_outline),
          ],
          if (r.response.isNotEmpty) ...[
            const SizedBox(height: 10),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: AsafColors.surfaceAlt, borderRadius: BorderRadius.circular(10)),
              child: SelectableText(r.response, style: AsafText.mono),
            ),
          ],
          if (r.artifacts.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Artifacts', style: AsafText.h3),
            const SizedBox(height: 6),
            ...r.artifacts.map((a) => Padding(
                  padding: const EdgeInsets.symmetric(vertical: 4),
                  child: Row(
                    children: [
                      const Icon(Icons.image_outlined, size: 17, color: AsafColors.primaryLight),
                      const SizedBox(width: 10),
                      Expanded(child: Text(a.name, style: AsafText.body.copyWith(color: AsafColors.textPrimary), maxLines: 1, overflow: TextOverflow.ellipsis)),
                      Text(a.sizeLabel, style: AsafText.small),
                    ],
                  ),
                )),
          ],
        ],
      ),
    );
  }

  Widget _modelDropdown(List<ModelEntry> models) {
    final value = models.any((m) => m.id == _model) ? _model : '';
    return SizedBox(
      width: 190,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Model', style: AsafText.small),
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
                hint: const Text('Provider default', style: AsafText.small),
                items: [
                  const DropdownMenuItem(value: '', child: Text('Provider default', style: AsafText.small)),
                  ...models.map((m) => DropdownMenuItem(
                        value: m.id,
                        child: Text(m.id, style: AsafText.body.copyWith(color: AsafColors.textPrimary), overflow: TextOverflow.ellipsis),
                      )),
                ],
                onChanged: (v) => setState(() => _model = v ?? ''),
              ),
            ),
          ),
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
