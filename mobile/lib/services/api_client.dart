import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../core/app_config.dart';
import '../core/errors.dart';

/// Real HTTP client for the ASAF AI backend.
///
/// Every method targets the true FastAPI routes (see the project's API.md) and
/// never fabricates a result. Non-2xx responses are translated to
/// [ApiException] with a structured [ApiErrorCode].
class AsafApi {
  AsafApi({http.Client? client}) : _client = client ?? http.Client();

  final http.Client _client;
  String? _token;

  void setToken(String? token) => _token = token;
  String? get token => _token;

  Map<String, String> _headers({bool json = true}) {
    final h = <String, String>{'Accept': 'application/json'};
    if (json) h['Content-Type'] = 'application/json';
    if (_token != null && _token!.isNotEmpty) {
      h['Authorization'] = 'Bearer $_token';
    }
    return h;
  }

  Duration _timeout(String path) {
    // Long-running generation/agent calls need a generous timeout.
    if (path.contains('/chat') || path.contains('/agent') || path.contains('/research')) {
      return const Duration(minutes: 5);
    }
    return const Duration(seconds: 45);
  }

  dynamic _decode(http.Response res) {
    final body = res.body.isEmpty ? '' : res.body;
    dynamic parsed;
    if (body.isNotEmpty) {
      try {
        parsed = jsonDecode(body);
      } catch (_) {
        parsed = body;
      }
    }
    if (res.statusCode >= 200 && res.statusCode < 300) {
      return parsed;
    }
    String detail = '';
    if (parsed is Map && parsed['detail'] != null) {
      final d = parsed['detail'];
      detail = d is String ? d : jsonEncode(d);
    } else if (parsed is Map && parsed['message'] != null) {
      detail = parsed['message'].toString();
    } else if (parsed is String) {
      detail = parsed;
    }
    throw ApiException.fromStatus(res.statusCode, detail);
  }

  Future<dynamic> _get(String path, {Map<String, String>? query}) async {
    final uri = Uri.parse(AppConfig.api(path)).replace(queryParameters: query);
    try {
      final res = await _client.get(uri, headers: _headers(json: false)).timeout(_timeout(path));
      return _decode(res);
    } on TimeoutException {
      throw ApiException(ApiErrorCode.timeout, 'The request timed out. The runtime may be busy.');
    } on http.ClientException catch (e) {
      throw ApiException(ApiErrorCode.network, 'Cannot reach ASAF AI backend at ${AppConfig.baseUrl}. (${e.message})');
    }
  }

  Future<dynamic> _post(String path, Map<String, dynamic> body) async {
    final uri = Uri.parse(AppConfig.api(path));
    try {
      final res = await _client.post(uri, headers: _headers(), body: jsonEncode(body)).timeout(_timeout(path));
      return _decode(res);
    } on TimeoutException {
      throw ApiException(ApiErrorCode.timeout, 'The request timed out. The runtime may be busy.');
    } on http.ClientException catch (e) {
      throw ApiException(ApiErrorCode.network, 'Cannot reach ASAF AI backend at ${AppConfig.baseUrl}. (${e.message})');
    }
  }

  Future<dynamic> _delete(String path) async {
    // Kept for the job-cancel surface; wired where a job id is known.
    final uri = Uri.parse(AppConfig.api(path));
    try {
      final res = await _client.delete(uri, headers: _headers(json: false)).timeout(_timeout(path));
      return _decode(res);
    } on http.ClientException catch (e) {
      throw ApiException(ApiErrorCode.network, 'Cannot reach ASAF AI backend at ${AppConfig.baseUrl}. (${e.message})');
    }
  }

  /// Cancel a running job (`DELETE /api/jobs/{job_id}`).
  Future<Map<String, dynamic>> cancelJob(String jobId) async =>
      Map<String, dynamic>.from(await _delete('/api/jobs/${Uri.encodeComponent(jobId)}') as Map);

  /// Cancel a task (`POST /api/tasks/{task_id}/cancel`).
  Future<Map<String, dynamic>> cancelTask(String taskId) async =>
      Map<String, dynamic>.from(await _post('/api/tasks/${Uri.encodeComponent(taskId)}/cancel', const {}) as Map);

  // --------------------------------------------------------------- system
  Future<Map<String, dynamic>> health() async => Map<String, dynamic>.from(await _get('/api/health') as Map);

  Future<Map<String, dynamic>> version() async => Map<String, dynamic>.from(await _get('/api/version') as Map);

  Future<Map<String, dynamic>> settingsView() async => Map<String, dynamic>.from(await _get('/api/settings') as Map);

  // ----------------------------------------------------------------- auth
  Future<Map<String, dynamic>> login(String email, String password) async =>
      Map<String, dynamic>.from(await _post('/api/auth/login', {'email': email, 'password': password}) as Map);

  Future<Map<String, dynamic>> register(String email, String password, String displayName) async => Map<String, dynamic>.from(
        await _post('/api/auth/register', {'email': email, 'password': password, 'display_name': displayName}) as Map,
      );

  Future<Map<String, dynamic>> me() async => Map<String, dynamic>.from(await _get('/api/auth/me') as Map);

  // --------------------------------------------------------------- models
  /// Registry health (providers, models, usability).
  Future<Map<String, dynamic>> models() async => Map<String, dynamic>.from(await _get('/api/models') as Map);

  /// Declarative catalog merged with real runtime status.
  Future<Map<String, dynamic>> modelCatalog() async => Map<String, dynamic>.from(await _get('/api/models/catalog') as Map);

  Future<Map<String, dynamic>> modelDetail(String id) async =>
      Map<String, dynamic>.from(await _get('/api/models/${Uri.encodeComponent(id)}') as Map);

  Future<Map<String, dynamic>> modelHealth(String id, {bool force = false}) async => Map<String, dynamic>.from(
        await _get('/api/models/${Uri.encodeComponent(id)}/health', query: {'force': force.toString()}) as Map,
      );

  Future<Map<String, dynamic>> providers() async => Map<String, dynamic>.from(await _get('/api/models/providers') as Map);

  Future<Map<String, dynamic>> routerPreview() async => Map<String, dynamic>.from(await _get('/api/models/router') as Map);

  Future<Map<String, dynamic>> runtimes() async => Map<String, dynamic>.from(await _get('/api/models/runtimes') as Map);

  Future<Map<String, dynamic>> provisioning() async => Map<String, dynamic>.from(await _get('/api/models/provisioning') as Map);

  Future<Map<String, dynamic>> localActivation() async =>
      Map<String, dynamic>.from(await _get('/api/models/local/activation') as Map);

  Future<Map<String, dynamic>> generationModels() async =>
      Map<String, dynamic>.from(await _get('/api/models/generation') as Map);

  Future<Map<String, dynamic>> generationRuntimeStatus({bool load = false}) async => Map<String, dynamic>.from(
        await _get('/api/models/generation/status', query: {'load': load.toString()}) as Map,
      );

  Future<Map<String, dynamic>> generationRouter() async =>
      Map<String, dynamic>.from(await _get('/api/models/generation/router') as Map);

  Future<Map<String, dynamic>> testConnection({String provider = '', String model = ''}) async => Map<String, dynamic>.from(
        await _post('/api/models/test-connection', {'provider': provider, 'model': model}) as Map,
      );

  // ------------------------------------------------------------ projects
  Future<Map<String, dynamic>> projects() async => Map<String, dynamic>.from(await _get('/api/projects') as Map);

  Future<Map<String, dynamic>> createProject(String name, String description) async => Map<String, dynamic>.from(
        await _post('/api/projects', {'name': name, 'description': description, 'settings': <String, dynamic>{}}) as Map,
      );

  Future<Map<String, dynamic>> project(String id) async =>
      Map<String, dynamic>.from(await _get('/api/projects/$id') as Map);

  Future<List<dynamic>> conversationMessages(String conversationId) async {
    final res = await _get('/api/conversations/$conversationId/messages') as Map;
    return (res['messages'] as List?) ?? [];
  }

  // ---------------------------------------------------------------- chat
  Future<Map<String, dynamic>> chat({
    required String message,
    required String projectId,
    String? conversationId,
    String model = '',
    List<Map<String, String>> history = const [],
    double? temperature,
    int? maxTokens,
  }) async {
    final body = <String, dynamic>{
      'message': message,
      'project_id': projectId,
      'stream': false,
      'history': history,
    };
    if (conversationId != null) body['conversation_id'] = conversationId;
    if (model.isNotEmpty) body['model'] = model;
    if (temperature != null) body['temperature'] = temperature;
    if (maxTokens != null) body['max_tokens'] = maxTokens;
    return Map<String, dynamic>.from(await _post('/api/chat', body) as Map);
  }

  /// Server-sent-events chat stream. Yields raw JSON maps decoded from `data:`.
  Stream<Map<String, dynamic>> chatStream({
    required String message,
    required String projectId,
    String? conversationId,
    String model = '',
    List<Map<String, String>> history = const [],
  }) async* {
    final body = <String, dynamic>{
      'message': message,
      'project_id': projectId,
      'stream': true,
      'history': history,
    };
    if (conversationId != null) body['conversation_id'] = conversationId;
    if (model.isNotEmpty) body['model'] = model;

    final req = http.Request('POST', Uri.parse(AppConfig.api('/api/chat')));
    req.headers.addAll(_headers());
    req.body = jsonEncode(body);

    final http.StreamedResponse streamed;
    try {
      streamed = await _client.send(req);
    } on http.ClientException catch (e) {
      throw ApiException(ApiErrorCode.network, 'Cannot reach ASAF AI backend. (${e.message})');
    }
    if (streamed.statusCode >= 400) {
      final raw = await streamed.stream.bytesToString();
      String detail = raw;
      try {
        final parsed = jsonDecode(raw);
        if (parsed is Map && parsed['detail'] != null) detail = parsed['detail'].toString();
      } catch (_) {}
      throw ApiException.fromStatus(streamed.statusCode, detail);
    }
    final lines = streamed.stream.transform(utf8.decoder).transform(const LineSplitter());
    await for (final line in lines) {
      if (line.startsWith('data:')) {
        final payload = line.substring(5).trim();
        if (payload.isEmpty) continue;
        try {
          final decoded = jsonDecode(payload);
          if (decoded is Map<String, dynamic>) yield decoded;
        } catch (_) {
          // Ignore malformed keep-alive fragments.
        }
      }
    }
  }

  // ------------------------------------------------------------- modules
  Future<Map<String, dynamic>> generateImage({
    required String description,
    required String projectId,
    String action = 'brief',
    String style = '',
    String aspectRatio = '1:1',
    int variants = 1,
    String model = '',
  }) async =>
      Map<String, dynamic>.from(
        await _post('/api/images', {
          'description': description,
          'project_id': projectId,
          'action': action,
          'style': style,
          'aspect_ratio': aspectRatio,
          'variants': variants,
          if (model.isNotEmpty) 'model': model,
        }) as Map,
      );

  /// Experimental I2V generation runtime. `image` must be a local path on the
  /// server host (no remote URLs, by backend design).
  Future<Map<String, dynamic>> generateVideo({
    required String model,
    required String image,
    required String prompt,
    double duration = 5.0,
    int width = 832,
    int height = 480,
    int fps = 16,
  }) async =>
      Map<String, dynamic>.from(
        await _post('/api/models/generation', {
          'model': model,
          'image': image,
          'prompt': prompt,
          'duration': duration,
          'width': width,
          'height': height,
          'fps': fps,
        }) as Map,
      );

  // ------------------------------------------------------------- history
  Future<Map<String, dynamic>> tasks({String? projectId, int limit = 50}) async {
    final q = <String, String>{'limit': '$limit'};
    if (projectId != null) q['project_id'] = projectId;
    return Map<String, dynamic>.from(await _get('/api/tasks', query: q) as Map);
  }

  Future<Map<String, dynamic>> task(String id) async => Map<String, dynamic>.from(await _get('/api/tasks/$id') as Map);

  Future<Map<String, dynamic>> jobs({int limit = 50}) async =>
      Map<String, dynamic>.from(await _get('/api/jobs', query: {'limit': '$limit'}) as Map);

  Future<Map<String, dynamic>> tools() async => Map<String, dynamic>.from(await _get('/api/tools') as Map);

  void dispose() => _client.close();
}
