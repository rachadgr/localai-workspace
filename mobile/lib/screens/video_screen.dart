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
/// wired and its weights are present locally. This screen surfaces the real
/// runtime state and never pretends a clip was produced.
class VideoScreen extends StatefulWidget {
  const VideoScreen({super.key});

  @override
  State<VideoScreen> createState() => _VideoScreenState();
}

class _VideoScreenState extends State<VideoScreen> {
  final _image = TextEditingController();
  final _prompt = TextEditingController();
  final _model = TextEditingController(text: 'wan2.2-i2v');
  double _duration = 5;
  bool _busy = false;
  Map<String, dynamic>? _result;
  String? _error;

  @override
  void dispose() {
    _image.dispose();
    _prompt.dispose();
    _model.dispose();
    super.dispose();
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
        model: _model.text.trim(),
        image: _image.text.trim(),
        prompt: _prompt.text.trim(),
        duration: _duration,
      );
      setState(() => _result = res);
      store.loadHistory();
    } on ApiException catch (e) {
      setState(() => _error = e.message);
      if (e.detail != null && e.detail!.isNotEmpty) {
        setState(() => _result = {'error': e.message, 'detail': e.detail});
      }
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
              if (rt['models'] is List)
                KeyValue('Registered models', '${(rt['models'] as List).length}'),
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
              TextField(
                controller: _model,
                decoration: const InputDecoration(labelText: 'Model id', hintText: 'wan2.2-i2v'),
              ),
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
              const SizedBox(height: 8),
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
}
