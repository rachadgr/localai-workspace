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
      providers = p.entries
          .map((e) => ProviderEntry.fromJson({...((e.value as Map).cast<String, dynamic>()), 'name': e.key}))
          .toList();
    } on ApiException {
      providers = [];
    }
  }

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

  Future<void> loadHistory() async {
    try {
      final res = await _api.tasks(projectId: activeProjectId, limit: 100);
      final list = (res['tasks'] as List?) ?? [];
      history = list.map((e) => HistoryTask.fromJson((e as Map).cast<String, dynamic>())).toList();
      notifyListeners();
    } on ApiException catch (e) {
      error = e.message;
      notifyListeners();
    }
  }

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
