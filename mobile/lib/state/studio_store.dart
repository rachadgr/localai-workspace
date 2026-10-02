import 'package:flutter/foundation.dart';

import '../core/errors.dart';
import '../models/models.dart';
import '../services/api_client.dart';

/// Central studio state: real backend data for the dashboard, models, providers,
/// routing and generation history. Every value comes from the backend — nothing
/// is hardcoded or invented. Unavailable things are shown as unavailable.
class StudioStore extends ChangeNotifier {
  StudioStore(this._api);

  final AsafApi _api;

  bool loading = false;
  String? error;

  HealthInfo? health;
  List<ModelEntry> models = [];
  List<ProviderEntry> providers = [];
  Map<String, RouterDecision> router = {};
  List<HistoryTask> history = [];
  List<Map<String, dynamic>> runtimes = [];
  Map<String, dynamic> generation = {};
  Map<String, dynamic> generationRuntime = {};
  Map<String, dynamic> provisioning = {};

  // Active project used for chat/generation.
  String? activeProjectId;
  List<Map<String, dynamic>> projects = [];

  // Real workspace aggregates (dashboard / documents / slides / per-project).
  Map<String, dynamic> dashboard = {};
  List<Map<String, dynamic>> recentGenerations = [];
  List<Map<String, dynamic>> recentDocuments = [];
  List<Map<String, dynamic>> recentSlides = [];
  List<Map<String, dynamic>> quickActions = [];

  Future<void> refreshAll() async {
    loading = true;
    error = null;
    notifyListeners();
    try {
      await _loadHealth();
      await _loadModels();
      await _loadProviders();
      await _loadRouter();
      await _loadRuntimes();
      await _loadGeneration();
    } on ApiException catch (e) {
      error = e.message;
    } catch (e) {
      error = 'Unexpected error while loading studio data: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  /// Load the authenticated dashboard aggregate (projects, recent generations,
  /// documents, slides, models, providers, runtimes, quick actions).
  Future<void> loadDashboard({int limit = 8}) async {
    try {
      final res = await _api.dashboard(limit: limit);
      dashboard = res;
      projects = ((res['projects'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      recentGenerations = ((res['recent_generations'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      recentDocuments = ((res['recent_documents'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      recentSlides = ((res['recent_slides'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      quickActions = ((res['quick_actions'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      activeProjectId ??= projects.isNotEmpty ? projects.first['id']?.toString() : null;
      notifyListeners();
    } on ApiException catch (e) {
      error = e.message;
      notifyListeners();
    }
  }

  Future<void> _loadHealth() async {
    health = HealthInfo(raw: await _api.health());
  }

  Future<void> _loadModels() async {
    try {
      final catalog = await _api.modelCatalog();
      final list = (catalog['models'] as List?) ?? [];
      models = list.map((e) => ModelEntry.fromJson((e as Map).cast<String, dynamic>())).toList();
    } on ApiException {
      // Fall back to the registry health model list if the catalog is unavailable.
      final m = await _api.models();
      final list = (m['models'] as List?) ?? [];
      models = list.map((e) => ModelEntry.fromJson((e as Map).cast<String, dynamic>())).toList();
    }
  }

  Future<void> _loadProviders() async {
    try {
      final res = await _api.providers();
      final p = (res['providers'] as Map?)?.cast<String, dynamic>() ?? {};
      providers = p.entries.map((e) {
        final raw = (e.value as Map).cast<String, dynamic>();
        // Enrich each provider with the real model counts derived from the catalog.
        final owned = models.where((m) => m.provider == e.key).toList();
        return ProviderEntry.fromJson({
          ...raw,
          'name': e.key,
          'model_count': owned.length,
          'available_count': owned.where((m) => m.usable).length,
        });
      }).toList();
    } on ApiException {
      providers = [];
    }
  }

  /// Models belonging to a provider (for the Provider Center detail view).
  List<ModelEntry> modelsForProvider(String provider) => models.where((m) => m.provider == provider).toList();

  Future<void> _loadRouter() async {
    try {
      final res = await _api.routerPreview();
      final tasks = (res['tasks'] as Map?)?.cast<String, dynamic>() ?? {};
      router = tasks.map((k, v) => MapEntry(k, RouterDecision.fromJson(k, (v as Map).cast<String, dynamic>())));
    } on ApiException {
      router = {};
    }
  }

  Future<void> _loadRuntimes() async {
    try {
      final res = await _api.runtimes();
      runtimes = ((res['runtimes'] as List?) ?? (res['entries'] as List?) ?? [])
          .map((e) => (e as Map).cast<String, dynamic>())
          .toList();
    } on ApiException {
      runtimes = [];
    }
  }

  Future<void> _loadGeneration() async {
    try {
      generation = await _api.generationModels();
    } on ApiException {
      generation = {};
    }
    try {
      generationRuntime = await _api.generationRuntimeStatus();
    } on ApiException {
      generationRuntime = {};
    }
  }

  Future<void> loadProjects() async {
    try {
      final res = await _api.projects();
      projects = ((res['projects'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
      if (projects.isEmpty) {
        final created = await _api.createProject('ASAF AI Workspace', 'Auto-created by the ASAF AI mobile client.');
        activeProjectId = created['id']?.toString();
        projects = [created.map((k, v) => MapEntry(k.toString(), v))];
      } else {
        activeProjectId ??= projects.first['id']?.toString();
      }
      notifyListeners();
    } on ApiException catch (e) {
      error = e.message;
      notifyListeners();
    }
  }

  Future<String?> ensureActiveProject() async {
    if (activeProjectId != null) return activeProjectId;
    await loadProjects();
    return activeProjectId;
  }

  /// Load real generation history, enriched with model / provider / output.
  Future<void> loadHistory() async {
    try {
      final res = await _api.generations(projectId: activeProjectId, limit: 100);
      final list = (res['generations'] as List?) ?? [];
      history = list.map((e) => HistoryTask.fromJson((e as Map).cast<String, dynamic>())).toList();
      notifyListeners();
    } on ApiException catch (e) {
      // Fall back to the raw task list if the aggregate endpoint is unavailable.
      try {
        final res = await _api.tasks(projectId: activeProjectId, limit: 100);
        final list = (res['tasks'] as List?) ?? [];
        history = list.map((e) => HistoryTask.fromJson((e as Map).cast<String, dynamic>())).toList();
        notifyListeners();
      } on ApiException {
        error = e.message;
        notifyListeners();
      }
    }
  }

  /// Real generated documents for the active project.
  Future<List<Map<String, dynamic>>> loadDocuments() async {
    try {
      final res = await _api.documents(projectId: activeProjectId);
      return ((res['documents'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
    } on ApiException {
      return const [];
    }
  }

  /// Real generated slide decks for the active project.
  Future<List<Map<String, dynamic>>> loadSlides() async {
    try {
      final res = await _api.slides(projectId: activeProjectId);
      return ((res['slides'] as List?) ?? []).map((e) => (e as Map).cast<String, dynamic>()).toList();
    } on ApiException {
      return const [];
    }
  }

  /// The real per-project workspace view (conversations, artifacts, files, tasks).
  Future<Map<String, dynamic>> workspace(String projectId) async => _api.workspace(projectId);

  Future<Map<String, dynamic>> testProvider(String provider) async {
    return _api.testConnection(provider: provider);
  }

  Future<Map<String, dynamic>> checkModelHealth(String id) async {
    return _api.modelHealth(id, force: true);
  }

  /// Models that pass the backend's hard routing gate for a given task.
  List<ModelEntry> modelsForTask(String task) {
    final required = _taskRequirements[task];
    if (required == null) return models.where((m) => m.usable).toList();
    return models.where((m) {
      if (!m.usable) return false;
      if (required.kind != null && m.kind != required.kind) return false;
      for (final cap in required.caps) {
        if (!m.capabilities.contains(cap)) return false;
      }
      for (final mod in required.modalities) {
        if (!m.modalities.contains(mod)) return false;
      }
      return true;
    }).toList();
  }

  List<ModelEntry> get chatModels => modelsForTask('chat');
}

class _TaskReq {
  const _TaskReq({this.kind, this.caps = const [], this.modalities = const []});
  final String? kind;
  final List<String> caps;
  final List<String> modalities;
}

/// Mirrors `models/router.py::TASK_REQUIREMENTS` hard gates for client-side gating.
const Map<String, _TaskReq> _taskRequirements = {
  'chat': _TaskReq(kind: 'chat'),
  'coding': _TaskReq(kind: 'chat'),
  'vision': _TaskReq(kind: 'chat', caps: ['vision'], modalities: ['text', 'image']),
  'reasoning': _TaskReq(kind: 'chat', caps: ['reasoning']),
  'document': _TaskReq(kind: 'chat'),
  'embedding': _TaskReq(kind: 'embedding', caps: ['embeddings'], modalities: ['embedding']),
  'image_generation': _TaskReq(kind: 'image', caps: ['image_generation'], modalities: ['image']),
  'video_generation': _TaskReq(kind: 'video', caps: ['video_generation'], modalities: ['video']),
};
