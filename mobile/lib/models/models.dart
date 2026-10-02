import 'package:flutter/material.dart';

import '../core/theme.dart';

/// Parsed representations of the ASAF AI backend payloads.
///
/// They intentionally keep the backend's exact vocabulary (statuses, kinds,
/// capabilities) so nothing is lost or invented in translation.

class ModelEntry {
  ModelEntry({
    required this.id,
    required this.name,
    required this.provider,
    required this.kind,
    required this.capabilities,
    required this.category,
    required this.modalities,
    required this.status,
    required this.available,
    required this.local,
    required this.error,
    this.contextWindow = 0,
    this.servingRuntime = '',
    this.costTier = 'unknown',
    this.reasoning = false,
    this.vision = false,
    this.tools = false,
    this.streaming = false,
  });

  final String id;
  final String name;
  final String provider;
  final String kind;
  final List<String> capabilities;
  final List<String> category;
  final List<String> modalities;
  final String status;
  final bool available;
  final bool local;
  final String error;
  final int contextWindow;
  final String servingRuntime;
  final String costTier;
  final bool reasoning;
  final bool vision;
  final bool tools;
  final bool streaming;

  /// True when the backend confirmed the model with a real probe.
  bool get usable => status == 'AVAILABLE' && available;

  factory ModelEntry.fromJson(Map<String, dynamic> j) {
    List<String> list(dynamic v) => (v as List?)?.map((e) => e.toString()).toList() ?? <String>[];
    return ModelEntry(
      id: j['id']?.toString() ?? '',
      name: (j['name']?.toString().isNotEmpty ?? false) ? j['name'].toString() : (j['id']?.toString() ?? ''),
      provider: j['provider']?.toString() ?? '',
      kind: (j['kind']?.toString().isNotEmpty ?? false) ? j['kind'].toString() : (j['type']?.toString() ?? ''),
      capabilities: list(j['capabilities']),
      category: list(j['category']),
      modalities: list(j['modalities'] ?? j['modality']),
      status: j['status']?.toString() ?? 'UNKNOWN',
      available: j['available'] == true,
      local: j['local'] == true,
      error: j['error']?.toString() ?? '',
      contextWindow: (j['context_window'] as num?)?.toInt() ?? 0,
      servingRuntime: j['serving_runtime']?.toString() ?? '',
      costTier: j['cost_tier']?.toString() ?? 'unknown',
      reasoning: j['reasoning'] == true,
      vision: j['vision'] == true,
      tools: j['tools'] == true,
      streaming: j['streaming'] == true,
    );
  }

  /// A model created from the `health()` endpoint's `models` array (same shape).
  factory ModelEntry.fromHealthJson(Map<String, dynamic> j) => ModelEntry.fromJson(j);

  String get subtitle {
    final parts = <String>[provider, kind];
    return parts.where((p) => p.isNotEmpty).join(' · ');
  }
}

class ProviderEntry {
  ProviderEntry({
    required this.name,
    required this.status,
    required this.configured,
    required this.local,
    required this.endpoint,
    required this.error,
  });

  final String name;
  final String status;
  final bool configured;
  final bool local;
  final String endpoint;
  final String error;

  factory ProviderEntry.fromJson(Map<String, dynamic> j) => ProviderEntry(
        name: j['name']?.toString() ?? j['provider']?.toString() ?? '',
        status: j['status']?.toString() ?? 'UNKNOWN',
        configured: j['configured'] == true,
        local: j['local'] == true,
        endpoint: j['endpoint']?.toString() ?? '',
        error: j['error']?.toString() ?? '',
      );
}

/// A routed task decision (from `/api/models/router`).
class RouterDecision {
  RouterDecision({
    required this.task,
    required this.outcome,
    required this.model,
    required this.provider,
    required this.reason,
    required this.required,
    required this.modalities,
  });

  final String task;
  final String outcome;
  final String model;
  final String provider;
  final String reason;
  final List<String> required;
  final List<String> modalities;

  bool get selected => outcome == 'SELECTED' && model.isNotEmpty;

  factory RouterDecision.fromJson(String task, Map<String, dynamic> j) => RouterDecision(
        task: task,
        outcome: j['outcome']?.toString() ?? 'UNKNOWN',
        model: j['model']?.toString() ?? j['selected']?.toString() ?? '',
        provider: j['provider']?.toString() ?? '',
        reason: j['reason']?.toString() ?? '',
        required: (j['required'] as List?)?.map((e) => e.toString()).toList() ?? const [],
        modalities: (j['modalities'] as List?)?.map((e) => e.toString()).toList() ?? const [],
      );
}

/// One entry of generation history (`/api/tasks`).
class HistoryTask {
  HistoryTask({
    required this.taskId,
    required this.kind,
    required this.title,
    required this.status,
    required this.projectId,
    required this.createdAt,
    required this.error,
    this.progress = 0,
  });

  final String taskId;
  final String kind;
  final String title;
  final String status;
  final String projectId;
  final String createdAt;
  final String error;
  final double progress;

  String get when {
    if (createdAt.isEmpty) return '';
    final dt = DateTime.tryParse(createdAt);
    if (dt == null) return createdAt;
    final local = dt.toLocal();
    return '${local.year}-${_pad2(local.month)}-${_pad2(local.day)} ${_pad2(local.hour)}:${_pad2(local.minute)}';
  }

  static String _pad2(int n) => n < 10 ? '0$n' : '$n';

  factory HistoryTask.fromJson(Map<String, dynamic> j) => HistoryTask(
        taskId: j['task_id']?.toString() ?? '',
        kind: j['kind']?.toString() ?? '',
        title: j['title']?.toString() ?? '',
        status: j['status']?.toString() ?? 'UNKNOWN',
        projectId: j['project_id']?.toString() ?? '',
        createdAt: j['started_at']?.toString() ?? '',
        error: j['error']?.toString() ?? '',
        progress: (j['progress'] as num?)?.toDouble() ?? 0,
      );
}

/// A module/generation result returned by `/api/images` etc.
class ModuleResult {
  ModuleResult({required this.status, required this.summary, required this.response, required this.data, required this.error});

  final String status;
  final String summary;
  final String response;
  final Map<String, dynamic> data;
  final String error;

  bool get success => status == 'SUCCESS';

  factory ModuleResult.fromJson(Map<String, dynamic> j) => ModuleResult(
        status: j['status']?.toString() ?? 'UNKNOWN',
        summary: j['summary']?.toString() ?? '',
        response: j['response']?.toString() ?? '',
        data: (j['data'] as Map?)?.cast<String, dynamic>() ?? <String, dynamic>{},
        error: j['error']?.toString() ?? '',
      );
}

class HealthInfo {
  HealthInfo({required this.raw});
  final Map<String, dynamic> raw;

  String get status => raw['status']?.toString() ?? 'unknown';
  String get app => raw['app']?.toString() ?? '';
  String get version => raw['version']?.toString() ?? '';
  String get environment => raw['environment']?.toString() ?? '';
  String get database => raw['database']?.toString() ?? '';
  int get chatAvailable => (raw['models']?['chat_available'] as num?)?.toInt() ?? 0;
  String get modelsStatus => raw['models']?['status']?.toString() ?? '';
  bool get imageProvider => raw['image_provider'] == true;
  bool get networkTools => raw['network_tools'] == true;
  bool get codeExecution => raw['code_execution'] == true;
}

/// Colour helper shared by the UI for any status string.
Color statusColor(String status) => AsafColors.forStatus(status);

/// A single chat turn kept client-side for history.
class ChatTurn {
  ChatTurn({required this.role, required this.content, this.model = '', this.pending = false, this.error = ''});
  final String role; // 'user' | 'assistant'
  String content;
  String model;
  bool pending;
  String error;
}
