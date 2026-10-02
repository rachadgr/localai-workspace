import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_config.dart';
import '../core/errors.dart';
import '../core/theme.dart';
import '../services/api_client.dart';
import '../state/auth_store.dart';
import '../widgets/common.dart';

/// ASAF AI sign-in / registration screen.
///
/// Uses the real `/api/auth/login` and `/api/auth/register` routes. The backend
/// URL is editable so the user can point the client at their own server.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  final _baseUrl = TextEditingController(text: AppConfig.baseUrl);
  bool _register = false;
  bool _busy = false;
  bool _obscure = true;
  bool? _reachable; // null = unknown, true/false after an explicit test
  bool _testing = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    // Surface a "session expired" notice raised by AuthStore (e.g. after a 401).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final auth = context.read<AuthStore>();
      if (auth.sessionNotice != null) {
        setState(() => _error = auth.sessionNotice);
        auth.clearSessionNotice();
      }
    });
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _name.dispose();
    _baseUrl.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    FocusScope.of(context).unfocus();
    if (!AppConfig.isValid(_baseUrl.text)) {
      setState(() => _error = 'Enter a valid server URL (e.g. https://your-tunnel.trycloudflare.com).');
      return;
    }
    final api = context.read<AsafApi>();
    setState(() {
      _testing = true;
      _reachable = null;
      _error = null;
    });
    try {
      // Persist first so the probe targets the typed URL, then probe /api/health.
      await AppConfig.setBaseUrl(_baseUrl.text);
      if (!mounted) return;
      _baseUrl.text = AppConfig.baseUrl;
      final ok = await api.ping();
      if (!mounted) return;
      setState(() => _reachable = ok);
      if (!ok) {
        setState(() => _error = 'No response from ${AppConfig.baseUrl}/api/health. Is the server running and reachable?');
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _reachable = false;
        _error = 'Connection test failed: $e';
      });
    } finally {
      if (mounted) setState(() => _testing = false);
    }
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    final auth = context.read<AuthStore>();
    if (!AppConfig.isValid(_baseUrl.text)) {
      setState(() => _error = 'Enter a valid server URL (e.g. https://your-tunnel.trycloudflare.com).');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await AppConfig.setBaseUrl(_baseUrl.text);
      _baseUrl.text = AppConfig.baseUrl;
      if (_register) {
        await auth.register(_email.text, _password.text, _name.text);
      } else {
        await auth.login(_email.text, _password.text);
      }
    } on ApiException catch (e) {
      setState(() => _error = e.message);
    } catch (e) {
      setState(() => _error = 'Sign in failed: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  _brand(),
                  const SizedBox(height: 28),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(22),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Text(_register ? 'Create your account' : 'Sign in to your studio', style: AsafText.h2),
                          const SizedBox(height: 6),
                          Text(
                            _register
                                ? 'Registration may be disabled by the server administrator.'
                                : 'Authenticate against your ASAF AI server to continue.',
                            style: AsafText.small,
                          ),
                          const SizedBox(height: 20),
                          if (_register) ...[
                            TextField(
                              controller: _name,
                              decoration: const InputDecoration(labelText: 'Display name', hintText: 'ASAF Creator'),
                              textInputAction: TextInputAction.next,
                            ),
                            const SizedBox(height: 14),
                          ],
                          TextField(
                            controller: _email,
                            keyboardType: TextInputType.emailAddress,
                            decoration: const InputDecoration(labelText: 'Email', hintText: 'demo@localai.workspace'),
                            textInputAction: TextInputAction.next,
                          ),
                          const SizedBox(height: 14),
                          TextField(
                            controller: _password,
                            obscureText: _obscure,
                            decoration: InputDecoration(
                              labelText: 'Password',
                              suffixIcon: IconButton(
                                icon: Icon(_obscure ? Icons.visibility_off : Icons.visibility, size: 20),
                                onPressed: () => setState(() => _obscure = !_obscure),
                              ),
                            ),
                            onSubmitted: (_) => _submit(),
                          ),
                          const SizedBox(height: 14),
                          TextField(
                            controller: _baseUrl,
                            decoration: const InputDecoration(
                              labelText: 'Server URL',
                              hintText: 'https://your-tunnel.trycloudflare.com',
                              helperText: 'Your ASAF AI backend URL. Use the public HTTPS tunnel '
                                  'URL for a hosted (Kaggle/Colab) server, or your LAN IP on the same Wi-Fi.',
                              helperStyle: AsafText.small,
                            ),
                            keyboardType: TextInputType.url,
                          ),
                          const SizedBox(height: 10),
                          Row(
                            children: [
                              OutlinedButton.icon(
                                onPressed: (_busy || _testing) ? null : _testConnection,
                                icon: _testing
                                    ? const SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2))
                                    : Icon(
                                        _reachable == true ? Icons.cloud_done : Icons.cloud_queue,
                                        size: 18,
                                        color: _reachable == true ? AsafColors.statusAvailable : null,
                                      ),
                                label: Text(_reachable == true ? 'Server reachable' : 'Test connection'),
                              ),
                              const SizedBox(width: 10),
                              if (_reachable == true)
                                const StatusBadge('AVAILABLE', dense: true)
                              else if (_reachable == false)
                                const StatusBadge('UNAVAILABLE', dense: true),
                            ],
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 16),
                            _errorBanner(_error!),
                          ],
                          const SizedBox(height: 20),
                          ElevatedButton(
                            onPressed: _busy ? null : _submit,
                            child: _busy
                                ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                                : Text(_register ? 'Create account' : 'Sign in'),
                          ),
                          const SizedBox(height: 8),
                          TextButton(
                            onPressed: _busy
                                ? null
                                : () => setState(() {
                                      _register = !_register;
                                      _error = null;
                                    }),
                            child: Text(_register ? 'I already have an account' : 'Create a new account'),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'ASAF AI · AI Creation & Generation Studio',
                    textAlign: TextAlign.center,
                    style: AsafText.small,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _brand() {
    return Column(
      children: [
        Container(
          width: 64,
          height: 64,
          decoration: BoxDecoration(
            gradient: const LinearGradient(colors: [AsafColors.primary, AsafColors.accent]),
            borderRadius: BorderRadius.circular(18),
          ),
          child: const Icon(Icons.auto_awesome, color: Colors.white, size: 32),
        ),
        const SizedBox(height: 16),
        ShaderMask(
          shaderCallback: (r) => const LinearGradient(colors: [AsafColors.primaryLight, AsafColors.accent]).createShader(r),
          child: const Text(
            'ASAF AI',
            style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, color: Colors.white, letterSpacing: 1.5),
          ),
        ),
        const SizedBox(height: 4),
        Text('AI Creation & Generation Studio', style: AsafText.small),
      ],
    );
  }

  Widget _errorBanner(String message) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AsafColors.statusError.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AsafColors.statusError.withValues(alpha: 0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.error_outline, size: 18, color: AsafColors.statusError),
          const SizedBox(width: 10),
          Expanded(child: Text(message, style: AsafText.body.copyWith(color: AsafColors.textPrimary))),
        ],
      ),
    );
  }
}
