/// Structured, user-facing errors mirroring the backend error vocabulary.
///
/// The client never invents success: whenever the backend reports an
/// unavailable/misconfigured state or a non-2xx status, it is surfaced through
/// [ApiException] with an [ApiErrorCode] so the UI can react precisely.
enum ApiErrorCode {
  authenticationRequired,
  forbidden,
  notFound,
  validation,
  modelNotFound,
  modelNotConfigured,
  modelMisconfigured,
  modelUnavailable,
  modelDisabled,
  providerNotConfigured,
  providerUnavailable,
  invalidTask,
  invalidModelCapability,
  generationFailed,
  runtimeError,
  network,
  timeout,
  unreachable,
  cors,
  server,
  unknown,
}

ApiErrorCode _codeFromStatus(int status, String detail) {
  final d = detail.toLowerCase();
  if (status == 401) return ApiErrorCode.authenticationRequired;
  if (status == 403) return ApiErrorCode.forbidden;
  if (status == 404) {
    if (d.contains('model')) return ApiErrorCode.modelNotFound;
    return ApiErrorCode.notFound;
  }
  if (status == 422) return ApiErrorCode.validation;
  if (status == 503) {
    if (d.contains('not_configured') || d.contains('not configured')) return ApiErrorCode.modelNotConfigured;
    if (d.contains('misconfig')) return ApiErrorCode.modelMisconfigured;
    return ApiErrorCode.modelUnavailable;
  }
  if (status == 400) {
    if (d.contains('capabil')) return ApiErrorCode.invalidModelCapability;
    if (d.contains('generation')) return ApiErrorCode.generationFailed;
    return ApiErrorCode.validation;
  }
  if (status >= 500) return ApiErrorCode.server;
  return ApiErrorCode.unknown;
}

/// Human-readable, secret-free error returned by [AsafApi].
class ApiException implements Exception {
  ApiException(this.code, this.message, {this.statusCode, this.detail});

  /// Friendly, actionable message for a transport-level failure reaching the
  /// backend (DNS, refused connection, TLS, timeout). The [url] is the exact
  /// server address the client tried, so the user can correct it.
  factory ApiException.unreachable(String url, {String? reason}) {
    final hint = reason == null || reason.isEmpty ? '' : ' ($reason)';
    return ApiException(
      ApiErrorCode.unreachable,
      'Cannot reach the ASAF AI backend at $url.\n'
          'Check that the server is running, that the URL is correct, and that '
          'the phone has a network route to it (use the public HTTPS tunnel URL '
          'for a hosted backend, or your LAN IP on the same Wi-Fi).$hint',
      detail: url,
    );
  }

  /// Raised when a browser (web client) blocks the response for CORS reasons.
  factory ApiException.cors(String url) => ApiException(
        ApiErrorCode.cors,
        'The server at $url responded, but the browser blocked it as a '
            'cross-origin request (CORS). Set LAIW_CORS_ORIGINS to include this '
            "app's origin on the backend `/api/version`.",
        detail: url,
      );

  final ApiErrorCode code;
  final String message;
  final int? statusCode;
  final String? detail;

  factory ApiException.fromStatus(int status, String detail) {
    return ApiException(
      _codeFromStatus(status, detail),
      _friendly(status, detail),
      statusCode: status,
      detail: detail,
    );
  }

  static String _friendly(int status, String detail) {
    switch (status) {
      case 401:
        return 'Authentication required. Please sign in again.';
      case 403:
        return 'You do not have permission to perform this action.';
      case 404:
        return detail.isEmpty ? 'Resource not found.' : detail;
      case 422:
        return 'Invalid request. Please check your input.';
      case 503:
        return detail.isEmpty ? 'The requested capability is currently unavailable.' : detail;
      default:
        if (status >= 500) return 'Server error. The backend reported a problem.';
        return detail.isEmpty ? 'Request failed (HTTP $status).' : detail;
    }
  }

  @override
  String toString() => message;
}
