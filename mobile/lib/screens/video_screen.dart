import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/errors.dart';
import '../core/theme.dart';
import '../services/api_client.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Video generation workspace (experimental image-to-video runtime).
///
/// The backend only serves this when a real generation runtime is genuinely
/// wired and its weights are present locally. The model selector lists the real
/// registrations from `/api/models/generation`; this screen surfaces the real
/// runtime state and never pretends a clip was produced.
class VideoScreen extends StatefulWidget {
  const VideoScreen({super.key});

  @override
  State<VideoScreen> createState() => _VideoScreenState();
}

class _VideoScreenState extends State<VideoScreen> {
  final _image = TextEditingController();
  final _prompt = TextEditingController();
  String _model = 'wan2.2-i2v';
  double _duration = 5;
  int _width = 832;
  int _height = 480;
  int _fps = 16;
  bool _busy = false;
  Map<String, dynamic>? _result;
  String? _error;

  @override
  void dispose() {
    _image.dispose();
    _prompt.dispose();
    super.dispose();
  }

  /// Real video / i2v registrations from the generation summary.
  List<Map<String, dynamic>> _videoModels(StudioStore store) {
    final models = (store.generation['models'] as List?) ?? [];
    return models
        .map((e) => (e as Map).cast<String, dynamic>())
        .where((m) {
          final kind = m['kind']?.toString() ?? '';
          final surfaces = (m['surfaces'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[];
          return kind == 'video' || surfaces.contains('image_to_video');
        })
        .toList();
  }

  Future<void> _run() async {
    FocusScope.of(context).unfocus();
    final api = context.read<AsafApi>();
    final store = context.read<StudioStore>();
    setState(() {
      _busy = true;
      _error = null;
      _result = null;
    });
    try {
      final res = await api.generateVideo(
        model: _model.trim(),
        image: _image.text.trim(),
        prompt: _prompt.text.trim(),
        duration: _duration,
        width: _width,
        height: _height,
        fps: _fps,
      );
      setState(() => _result = res);
      store.loadHistory();
    } on ApiException catch (e) {
      setState(() {
        _error = '${errorCodeLabel(e.code)}: ${e.message}';
        if (e.detail != null && e.detail!.isNotEmpty) {
          _result = {'error': e.message, 'detail': e.detail};
        }
      });
    } catch (e) {
      setState(() => _error = 'Video request failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final store = context.watch<StudioStore>();
    final rt = store.generationRuntime;
    final runtimeStatus = rt['status']?.toString() ?? (rt['states'] is Map ? 'SEE-MATRIX' : 'NOT_CONFIGURED');
    final wired = (rt['wired'] as List?)?.map((e) => e.toString()).toList() ?? const <String>[];
    final videoModels = _videoModels(store);

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Generation runtime',
          icon: Icons.movie_outlined,
          action: StatusBadge(runtimeStatus, dense: true),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              InfoBanner(
                color: AsafColors.statusMisconfigured,
                icon: Icons.info_outline,
                message: wired.isEmpty
                    ? 'No video generation runtime is wired in this build. Requests will report NOT_CONFIGURED — nothing is fabricated.'
                    : 'Wired runtimes: ${wired.join(", ")}. A request runs only when its weights are present locally.',
              ),
              const SizedBox(height: 12),
              KeyValue('Runtime status', runtimeStatus),
              if (rt['reason'] != null) KeyValue('Reason', rt['reason'].toString()),
              if (rt['weights_missing'] != null) KeyValue('Weights missing', rt['weights_missing'].toString()),
              if (rt['models'] is List) KeyValue('Registered models', '${(rt['models'] as List).length}'),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Image-to-video',
          icon: Icons.auto_awesome_motion,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (videoModels.isEmpty)
                const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: Text('No video generation model is registered in this build.', style: AsafText.body),
                )
              else
                _modelSelector(videoModels),
              const SizedBox(height: 12),
              TextField(
                controller: _image,
                decoration: const InputDecoration(
                  labelText: 'Source image (local path on the server)',
                  hintText: '/path/on/server/input.png',
                  helperText: 'Remote URLs are rejected by design — no implicit download.',
                  helperStyle: AsafText.small,
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _prompt,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(labelText: 'Motion prompt', hintText: 'Slow camera push-in, leaves drifting…'),
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  Text('Duration: ${_duration.toStringAsFixed(1)}s', style: AsafText.body),
                  Expanded(
                    child: Slider(
                      value: _duration,
                      min: 1,
                      max: 15,
                      divisions: 28,
                      activeColor: AsafColors.primary,
                      label: '${_duration.toStringAsFixed(1)}s',
                      onChanged: (v) => setState(() => _duration = v),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  _dropdown('Width', '$_width', const ['512', '640', '768', '832'], (v) => setState(() => _width = int.parse(v))),
                  _dropdown('Height', '$_height', const ['320', '384', '480', '512'], (v) => setState(() => _height = int.parse(v))),
                  _dropdown('FPS', '$_fps', const ['8', '12', '16', '24'], (v) => setState(() => _fps = int.parse(v))),
                ],
              ),
              const SizedBox(height: 16),
              ElevatedButton.icon(
                onPressed: _busy ? null : _run,
                icon: _busy
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                    : const Icon(Icons.play_arrow),
                label: Text(_busy ? 'Generating…' : 'Generate video'),
              ),
            ],
          ),
        ),
        if (_error != null) ...[
          const SizedBox(height: 16),
          InfoBanner(message: _error!, color: AsafColors.statusError, icon: Icons.error_outline),
        ],
        if (_result != null) ...[
          const SizedBox(height: 16),
          SectionCard(
            title: 'Result',
            icon: Icons.terminal,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (_result!['status'] != null) KeyValue('Status', _result!['status'].toString()),
                if (_result!['reason'] != null) KeyValue('Reason', _result!['reason'].toString()),
                if (_result!['model'] != null) KeyValue('Model', _result!['model'].toString()),
                if (_result!['artifact'] != null) KeyValue('Artifact', _result!['artifact'].toString()),
                if (_result!['detail'] != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(color: AsafColors.surfaceAlt, borderRadius: BorderRadius.circular(10)),
                      child: SelectableText(_result!['detail'].toString(), style: AsafText.mono),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ],
    );
  }

  Widget _modelSelector(List<Map<String, dynamic>> models) {
    final ids = models.map((m) => m['id']?.toString() ?? '').where((s) => s.isNotEmpty).toList();
    if (!ids.contains(_model)) {
      _model = ids.isNotEmpty ? ids.first : _model;
    }
    return Column(
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
              value: _model,
              isExpanded: true,
              dropdownColor: AsafColors.surfaceHigh,
              items: models.map((m) {
                final id = m['id']?.toString() ?? '';
                final state = m['state']?.toString() ?? m['status']?.toString() ?? '';
                return DropdownMenuItem(
                  value: id,
                  child: Text('$id${state.isEmpty ? '' : ' · $state'}', style: AsafText.body.copyWith(color: AsafColors.textPrimary), overflow: TextOverflow.ellipsis),
                );
              }).toList(),
              onChanged: (v) => setState(() => _model = v ?? _model),
            ),
          ),
        ),
        const SizedBox(height: 10),
        ...models.map((m) {
          final id = m['id']?.toString() ?? '';
          final state = m['state']?.toString() ?? 'NOT_CONFIGURED';
          final reason = m['reason']?.toString() ?? '';
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 3),
            child: Row(
              children: [
                Expanded(
                  child: Text(reason.isEmpty ? id : '$id — $reason', style: AsafText.small, maxLines: 1, overflow: TextOverflow.ellipsis),
                ),
                StatusBadge(state, dense: true),
              ],
            ),
          );
        }),
      ],
    );
  }

  Widget _dropdown(String label, String value, List<String> options, ValueChanged<String> onChanged) {
    return SizedBox(
      width: 130,
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
