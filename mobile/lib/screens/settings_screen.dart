import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_config.dart';
import '../core/errors.dart';
import '../core/theme.dart';
import '../services/api_client.dart';
import '../state/auth_store.dart';
import '../state/studio_store.dart';
import '../widgets/common.dart';

/// Settings — server URL, session info, live backend settings, and sign out.
class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late final TextEditingController _url = TextEditingController(text: AppConfig.baseUrl);
  Map<String, dynamic>? _settings;
  String? _error;
  bool _busy = false;
  bool _testing = false;
  bool? _reachable;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final api = context.read<AsafApi>();
      final res = await api.settingsView();
      setState(() => _settings = res);
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _test() async {
    if (!AppConfig.isValid(_url.text)) {
      setState(() => _error = 'Enter a valid server URL (e.g. https://your-tunnel.trycloudflare.com).');
      return;
    }
    setState(() {
      _testing = true;
      _reachable = null;
      _error = null;
    });
    try {
      await AppConfig.setBaseUrl(_url.text);
      if (!mounted) return;
      setState(() => _url.text = AppConfig.baseUrl);
      final ok = await context.read<AsafApi>().ping();
      setState(() => _reachable = ok);
      if (!ok) setState(() => _error = 'No response from ${AppConfig.baseUrl}/api/health.');
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  Future<void> _save() async {
    if (!AppConfig.isValid(_url.text)) {
      setState(() => _error = 'Enter a valid server URL (e.g. https://your-tunnel.trycloudflare.com).');
      return;
    }
    setState(() => _busy = true);
    await AppConfig.setBaseUrl(_url.text);
    if (!mounted) return;
    setState(() {
      _url.text = AppConfig.baseUrl;
      _busy = false;
    });
    ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Server URL saved. Reconnecting…')));
    await context.read<StudioStore>().refreshAll();
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthStore>();
    final store = context.watch<StudioStore>();
    final h = store.health;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        SectionCard(
          title: 'Connection',
          icon: Icons.settings_ethernet,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: _url,
                decoration: const InputDecoration(
                  labelText: 'ASAF AI server URL',
                  hintText: 'https://your-tunnel.trycloudflare.com',
                  helperText: 'The public HTTPS tunnel URL of your backend, or your LAN IP '
                      'on the same Wi-Fi. Never a hardcoded emulator address.',
                  helperStyle: AsafText.small,
                ),
                keyboardType: TextInputType.url,
              ),
              const SizedBox(height: 14),
              Row(
                children: [
                  ElevatedButton.icon(
                    onPressed: _busy ? null : _save,
                    icon: const Icon(Icons.save, size: 18),
                    label: const Text('Save & reconnect'),
                  ),
                  const SizedBox(width: 10),
                  OutlinedButton.icon(
                    onPressed: (_busy || _testing) ? null : _test,
                    icon: _testing
                        ? const SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2))
                        : Icon(
                            _reachable == true ? Icons.cloud_done : Icons.cloud_queue,
                            size: 18,
                            color: _reachable == true ? AsafColors.statusAvailable : null,
                          ),
                    label: const Text('Test'),
                  ),
                  const SizedBox(width: 10),
                  OutlinedButton.icon(
                    onPressed: () async {
                      await AppConfig.resetBaseUrl();
                      if (!mounted) return;
                      setState(() => _url.text = AppConfig.baseUrl);
                    },
                    icon: const Icon(Icons.restart_alt, size: 18),
                    label: const Text('Reset'),
                  ),
                ],
              ),
              if (_reachable != null) ...[
                const SizedBox(height: 10),
                Row(
                  children: [
                    Text('Health check:', style: AsafText.small),
                    const SizedBox(width: 8),
                    StatusBadge(_reachable! ? 'AVAILABLE' : 'UNAVAILABLE', dense: true),
                  ],
                ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Session',
          icon: Icons.person_outline,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              KeyValue('Signed in as', auth.displayName),
              KeyValue('Email', auth.email),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: () => auth.logout(),
                icon: const Icon(Icons.logout, size: 18),
                label: const Text('Sign out'),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'Backend settings',
          icon: Icons.tune,
          action: IconButton(onPressed: _load, icon: const Icon(Icons.refresh, size: 18)),
          child: _error != null
              ? InfoBanner(message: _error!, color: AsafColors.statusError)
              : _settings == null
                  ? const Text('Loading…', style: AsafText.body)
                  : Column(
                      children: _settings!.entries
                          .where((e) => e.key != 'app_name')
                          .map((e) => KeyValue(_pretty(e.key), e.value.toString()))
                          .toList(),
                    ),
        ),
        const SizedBox(height: 16),
        SectionCard(
          title: 'About ASAF AI',
          icon: Icons.info_outline,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              KeyValue('Product', 'ASAF AI'),
              KeyValue('Client version', '1.0.0'),
              if (h != null) ...[
                KeyValue('Backend', '${h.app} v${h.version}'),
                KeyValue('Environment', h.environment),
              ],
              const SizedBox(height: 8),
              const Text(
                'ASAF AI is an AI Creation & Generation Studio. This client never fabricates results: every '
                'model, provider, runtime and generation status you see comes from your backend, reported honestly.',
                style: AsafText.small,
              ),
            ],
          ),
        ),
      ],
    );
  }

  String _pretty(String key) => key.replaceAll('_', ' ').replaceFirstMapped(RegExp(r'^.'),
      (m) => m.group(0)!.toUpperCase());
}
