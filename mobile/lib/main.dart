import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/app_config.dart';
import 'core/theme.dart';
import 'screens/home_shell.dart';
import 'screens/login_screen.dart';
import 'services/api_client.dart';
import 'state/auth_store.dart';
import 'state/studio_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppConfig.load();
  runApp(const AsafAiApp());
}

/// ASAF AI — AI Creation & Generation Studio (Android client).
///
/// The root wires the real HTTP client, the session store and the studio store,
/// then shows the workspace or the sign-in screen depending on the session.
class AsafAiApp extends StatelessWidget {
  const AsafAiApp({super.key});

  @override
  Widget build(BuildContext context) {
    final api = AsafApi();
    return MultiProvider(
      providers: [
        Provider<AsafApi>.value(value: api),
        ChangeNotifierProvider<AuthStore>(create: (_) => AuthStore(api)..restore()),
        ChangeNotifierProvider<StudioStore>(create: (_) => StudioStore(api)),
      ],
      child: MaterialApp(
        title: 'ASAF AI',
        debugShowCheckedModeBanner: false,
        theme: AsafTheme.dark(),
        home: const _RootGate(),
      ),
    );
  }
}

class _RootGate extends StatelessWidget {
  const _RootGate();

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthStore>();
    if (auth.restoring) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    return auth.isAuthenticated ? const HomeShell() : const LoginScreen();
  }
}
