import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_config.dart';
import '../core/theme.dart';
import '../state/auth_store.dart';
import '../state/locale_store.dart';
import '../state/studio_store.dart';
import 'chat_screen.dart';
import 'dashboard_screen.dart';
import 'history_screen.dart';
import 'image_screen.dart';
import 'models_screen.dart';
import 'providers_screen.dart';
import 'settings_screen.dart';
import 'video_screen.dart';
import 'workspace_screen.dart';

/// ASAF AI Studio shell: a 9-section workspace with a permanent rail on wide
/// screens and a drawer on phones. Fully RTL-aware (Arabic first).
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();

  List<_NavItem> _items(AsafLocalizations t) => <_NavItem>[
        _NavItem(t.navDashboard, Icons.dashboard_outlined, Icons.dashboard),
        _NavItem(t.navChat, Icons.forum_outlined, Icons.forum),
        _NavItem(t.navImage, Icons.image_outlined, Icons.image),
        _NavItem(t.navVideo, Icons.movie_outlined, Icons.movie),
        _NavItem(t.navWorkspace, Icons.folder_copy_outlined, Icons.folder_copy),
        _NavItem(t.navModels, Icons.memory_outlined, Icons.memory),
        _NavItem(t.navProviders, Icons.hub_outlined, Icons.hub),
        _NavItem(t.navHistory, Icons.history_outlined, Icons.history),
        _NavItem(t.navSettings, Icons.settings_outlined, Icons.settings),
      ];

  late final List<Widget> _screens = <Widget>[
    DashboardScreen(onNavigate: _select),
    const ChatScreen(),
    const ImageScreen(),
    const VideoScreen(),
    const WorkspaceScreen(),
    const ModelsScreen(),
    const ProvidersScreen(),
    const HistoryScreen(),
    const SettingsScreen(),
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final store = context.read<StudioStore>();
      await store.refreshAll();
      await store.loadDashboard();
    });
  }

  void _select(int i) {
    setState(() => _index = i);
    if (_scaffoldKey.currentState?.isDrawerOpen ?? false) {
      Navigator.of(context).pop(); // close the drawer
    }
    if (i == 7) context.read<StudioStore>().loadHistory();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.l10n;
    final items = _items(t);
    final wide = MediaQuery.of(context).size.width >= 900;
    final item = items[_index];

    final body = Column(
      children: [
        _topBar(t, item, items, showMenu: !wide),
        const Divider(height: 1),
        _connectivityBanner(t),
        Expanded(child: IndexedStack(index: _index, children: _screens)),
      ],
    );

    if (!wide) {
      return Scaffold(
        key: _scaffoldKey,
        drawer: _drawer(t, items),
        body: body,
      );
    }

    return Scaffold(
      key: _scaffoldKey,
      body: Row(
        children: [
          _rail(t, items),
          const VerticalDivider(width: 1),
          Expanded(child: body),
        ],
      ),
    );
  }

  /// A slim banner shown only when the studio failed to load, e.g. because the
  /// backend is unreachable or the URL is wrong — so connectivity issues are
  /// impossible to miss.
  Widget _connectivityBanner(AsafLocalizations t) {
    final store = context.watch<StudioStore>();
    if (store.error == null) return const SizedBox.shrink();
    final offline = AppConfig.baseUrl;
    return Container(
      width: double.infinity,
      color: AsafColors.statusError.withValues(alpha: 0.12),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Row(
        children: [
          const Icon(Icons.cloud_off, size: 18, color: AsafColors.statusError),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              t.connectivityCannotReach(offline),
              style: AsafText.small.copyWith(color: AsafColors.textPrimary),
            ),
          ),
          TextButton.icon(
            onPressed: () => _select(8),
            icon: const Icon(Icons.settings, size: 16),
            label: Text(t.navSettings),
          ),
          IconButton(onPressed: () => store.refreshAll(), icon: const Icon(Icons.refresh, size: 18), tooltip: t.retry),
        ],
      ),
    );
  }

  Widget _topBar(AsafLocalizations t, _NavItem item, List<_NavItem> items, {required bool showMenu}) {
    final store = context.watch<StudioStore>();
    return Container(
      color: AsafColors.background,
      padding: EdgeInsets.only(top: MediaQuery.of(context).padding.top),
      child: SizedBox(
        height: 56,
        child: Row(
          children: [
            if (showMenu)
              IconButton(onPressed: () => _scaffoldKey.currentState?.openDrawer(), icon: const Icon(Icons.menu)),
            const SizedBox(width: 4),
            ShaderMask(
              shaderCallback: (r) => const LinearGradient(colors: [AsafColors.primaryLight, AsafColors.accent]).createShader(r),
              child: const Padding(
                padding: EdgeInsets.symmetric(horizontal: 8),
                child: Text('ASAF AI', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: Colors.white, letterSpacing: 1)),
              ),
            ),
            const SizedBox(width: 6),
            Text('/ ${item.label}', style: AsafText.small),
            const Spacer(),
            if (store.loading)
              const Padding(
                padding: EdgeInsets.only(right: 12),
                child: SizedBox(height: 16, width: 16, child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            IconButton(onPressed: () => store.refreshAll(), icon: const Icon(Icons.refresh, size: 20), tooltip: t.refresh),
          ],
        ),
      ),
    );
  }

  Widget _rail(AsafLocalizations t, List<_NavItem> items) {
    final auth = context.watch<AuthStore>();
    return Container(
      width: 232,
      color: AsafColors.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: EdgeInsets.only(
              top: MediaQuery.of(context).padding.top + 20,
              left: 18,
              right: 18,
              bottom: 16,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 30,
                      height: 30,
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(colors: [AsafColors.primary, AsafColors.accent]),
                        borderRadius: BorderRadius.circular(9),
                      ),
                      child: const Icon(Icons.auto_awesome, color: Colors.white, size: 17),
                    ),
                    const SizedBox(width: 10),
                    const Text('ASAF AI', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 16, color: AsafColors.textPrimary, letterSpacing: 1)),
                  ],
                ),
                const SizedBox(height: 6),
                Text(t.appTagline, style: AsafText.small),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 10),
              children: [
                for (var i = 0; i < items.length; i++) _railTile(items, i),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(auth.displayName, style: AsafText.small.copyWith(color: AsafColors.textPrimary), overflow: TextOverflow.ellipsis),
                const SizedBox(height: 2),
                Text(AppConfig.baseUrl, style: AsafText.small, overflow: TextOverflow.ellipsis),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _railTile(List<_NavItem> items, int i) {
    final selected = _index == i;
    final item = items[i];
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Material(
        color: selected ? AsafColors.primary.withValues(alpha: 0.16) : Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => _select(i),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(
              children: [
                Icon(selected ? item.activeIcon : item.icon, size: 19, color: selected ? AsafColors.primaryLight : AsafColors.textSecondary),
                const SizedBox(width: 12),
                Text(item.label, style: AsafText.body.copyWith(color: selected ? AsafColors.textPrimary : AsafColors.textSecondary, fontWeight: selected ? FontWeight.w600 : FontWeight.w400)),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _drawer(AsafLocalizations t, List<_NavItem> items) {
    return Drawer(
      backgroundColor: AsafColors.surface,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.all(20),
              child: Row(
                children: [
                  Container(
                    width: 34,
                    height: 34,
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(colors: [AsafColors.primary, AsafColors.accent]),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: const Icon(Icons.auto_awesome, color: Colors.white, size: 19),
                  ),
                  const SizedBox(width: 12),
                  const Text('ASAF AI', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18, color: AsafColors.textPrimary, letterSpacing: 1)),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
                children: [for (var i = 0; i < items.length; i++) _railTile(items, i)],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _NavItem {
  const _NavItem(this.label, this.icon, this.activeIcon);
  final String label;
  final IconData icon;
  final IconData activeIcon;
}
