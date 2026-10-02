// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'ASAF AI';

  @override
  String get appTagline => 'AI Creation & Generation Studio';

  @override
  String get navDashboard => 'Dashboard';

  @override
  String get navChat => 'Chat';

  @override
  String get navImage => 'Image';

  @override
  String get navVideo => 'Video';

  @override
  String get navWorkspace => 'Workspace';

  @override
  String get navModels => 'Models';

  @override
  String get navProviders => 'Providers';

  @override
  String get navHistory => 'History';

  @override
  String get navSettings => 'Settings';

  @override
  String get menu => 'Menu';

  @override
  String get refresh => 'Refresh';

  @override
  String get retry => 'Retry';

  @override
  String get close => 'Close';

  @override
  String get test => 'Test';

  @override
  String get reset => 'Reset';

  @override
  String get settings => 'Settings';

  @override
  String get history => 'History';

  @override
  String get model => 'Model';

  @override
  String get status => 'Status';

  @override
  String get provider => 'Provider';

  @override
  String get reason => 'Reason';

  @override
  String get loading => 'Loading…';

  @override
  String get commonUnavailable => 'Unavailable.';

  @override
  String commonNoData(String url) {
    return 'No data available from $url.';
  }

  @override
  String get commonNoneWired => 'none wired';

  @override
  String get yes => 'yes';

  @override
  String get no => 'no';

  @override
  String get dash => '—';

  @override
  String connectivityCannotReach(String url) {
    return 'Cannot reach $url. Check the server URL in Settings.';
  }

  @override
  String get loginSignInTitle => 'Sign in to your studio';

  @override
  String get loginRegisterTitle => 'Create your account';

  @override
  String get loginSignInSubtitle =>
      'Authenticate against your ASAF AI server to continue.';

  @override
  String get loginRegisterSubtitle =>
      'Registration may be disabled by the server administrator.';

  @override
  String get loginDisplayName => 'Display name';

  @override
  String get loginDisplayNameHint => 'ASAF Creator';

  @override
  String get loginEmail => 'Email';

  @override
  String get loginEmailHint => 'you@example.com';

  @override
  String get loginPassword => 'Password';

  @override
  String get loginServerUrl => 'Server URL';

  @override
  String get loginServerUrlHint => 'https://your-tunnel.trycloudflare.com';

  @override
  String get loginServerUrlHelper =>
      'Your ASAF AI backend URL. Use the public HTTPS tunnel URL for a hosted server, or your LAN IP on the same Wi-Fi.';

  @override
  String get loginTestConnection => 'Test connection';

  @override
  String get loginServerReachable => 'Server reachable';

  @override
  String get loginSignIn => 'Sign in';

  @override
  String get loginCreateAccount => 'Create account';

  @override
  String get loginHaveAccount => 'I already have an account';

  @override
  String get loginNeedAccount => 'Create a new account';

  @override
  String get loginInvalidUrl =>
      'Enter a valid server URL (e.g. https://your-tunnel.trycloudflare.com).';

  @override
  String loginNoResponse(String url) {
    return 'No response from $url/api/health. Is the server running and reachable?';
  }

  @override
  String loginTestFailed(String error) {
    return 'Connection test failed: $error';
  }

  @override
  String loginFailed(String error) {
    return 'Sign in failed: $error';
  }

  @override
  String get settingsConnection => 'Connection';

  @override
  String get settingsServerUrl => 'ASAF AI server URL';

  @override
  String get settingsServerUrlHelper =>
      'The public HTTPS tunnel URL of your backend, or your LAN IP on the same Wi-Fi. Never a hardcoded emulator address.';

  @override
  String get settingsSaveReconnect => 'Save & reconnect';

  @override
  String get settingsHealthCheck => 'Health check:';

  @override
  String get settingsUrlSaved => 'Server URL saved. Reconnecting…';

  @override
  String settingsNoResponse(String url) {
    return 'No response from $url/api/health.';
  }

  @override
  String get settingsSession => 'Session';

  @override
  String get settingsSignedInAs => 'Signed in as';

  @override
  String get settingsEmail => 'Email';

  @override
  String get settingsSignOut => 'Sign out';

  @override
  String get settingsBackendSettings => 'Backend settings';

  @override
  String get settingsAbout => 'About ASAF AI';

  @override
  String get settingsProduct => 'Product';

  @override
  String get settingsClientVersion => 'Client version';

  @override
  String get settingsBackend => 'Backend';

  @override
  String get settingsEnvironment => 'Environment';

  @override
  String get settingsAppearance => 'Appearance';

  @override
  String get settingsLanguage => 'Language';

  @override
  String get settingsTheme => 'Theme';

  @override
  String get settingsThemeDark => 'Dark';

  @override
  String get settingsThemeLight => 'Light';

  @override
  String get settingsAboutBody =>
      'ASAF AI is an AI Creation & Generation Studio. This client never fabricates results: every model, provider, runtime and generation status you see comes from your backend, reported honestly.';

  @override
  String get dashCannotReach => 'Cannot reach the backend';

  @override
  String get dashHeroTitle => 'ASAF AI Studio';

  @override
  String get dashHealthy => 'All systems report healthy.';

  @override
  String get dashDegraded =>
      'Studio is running in a degraded state — see the details below.';

  @override
  String get dashModelsUsable => 'Models usable';

  @override
  String dashOfCatalog(int count) {
    return 'of $count in catalog';
  }

  @override
  String get dashProvidersOnline => 'Providers online';

  @override
  String dashOfConfigured(int count) {
    return 'of $count configured';
  }

  @override
  String get dashTasksRouteable => 'Tasks routeable';

  @override
  String dashOfTaskClasses(int count) {
    return 'of $count task classes';
  }

  @override
  String get dashProjects => 'Projects';

  @override
  String dashRecentTasks(int count) {
    return '$count recent task(s)';
  }

  @override
  String get dashQuickActions => 'Quick actions';

  @override
  String get dashQuickActionsEmpty =>
      'Quick actions unavailable — backend did not report any.';

  @override
  String get dashRecentGenerations => 'Recent generations';

  @override
  String get dashNoTasks =>
      'No tasks yet. Chat and generations will appear here.';

  @override
  String get dashRecentDocuments => 'Recent documents';

  @override
  String get dashRecentSlides => 'Recent slides';

  @override
  String get dashNoDocuments => 'No documents generated yet.';

  @override
  String get dashNoSlides => 'No slide decks generated yet.';

  @override
  String get dashRuntimeHealth => 'Runtime health';

  @override
  String get dashHealthUnavailable => 'Health unavailable.';

  @override
  String get dashBackend => 'Backend';

  @override
  String get dashEnvironment => 'Environment';

  @override
  String get dashDatabase => 'Database';

  @override
  String get dashOverallStatus => 'Overall status';

  @override
  String get dashModelLayer => 'Model layer';

  @override
  String get dashImageProvider => 'Image provider';

  @override
  String get dashNetworkTools => 'Network tools';

  @override
  String get dashCodeExecution => 'Code execution';

  @override
  String get dashConfigured => 'configured';

  @override
  String get dashNotConfigured => 'not configured';

  @override
  String get dashEnabled => 'enabled';

  @override
  String get dashDisabled => 'disabled';

  @override
  String get dashTaskRouting => 'Task routing';

  @override
  String get dashRoutingUnavailable => 'Routing diagnostics unavailable.';

  @override
  String get chatTitle => 'Chat';

  @override
  String get chatStartConversation => 'Start a conversation';

  @override
  String get chatNoModel =>
      'No chat-capable model is AVAILABLE on the backend. Configure a provider to enable chat.';

  @override
  String get chatAskAnything =>
      'Ask anything. Generation streams live from your ASAF AI backend.';

  @override
  String get chatAutoRoute => 'Auto-route';

  @override
  String get chatYou => 'You';

  @override
  String get chatAssistant => 'ASAF AI';

  @override
  String get chatMessageHint => 'Message ASAF AI…';

  @override
  String get chatUnavailableHint => 'Chat unavailable — no model is AVAILABLE';

  @override
  String get chatEmptyResponse => '(the model returned an empty response)';

  @override
  String get chatNoProject =>
      'No project available — the backend did not return one.';

  @override
  String get chatGenerationFailed => 'Generation failed.';

  @override
  String get imageTitle => 'Image generation';

  @override
  String get imageNotConfiguredBanner =>
      'No image provider is configured on the backend. Prompt/brief helpers work; actual image generation reports UNAVAILABLE (never a fabricated image).';

  @override
  String get imageDescription => 'Description';

  @override
  String get imageDescriptionHint =>
      'A cinematic portrait of a robot artist in a neon studio…';

  @override
  String get imageStyle => 'Style (optional)';

  @override
  String get imageStyleHint => 'photorealistic, 35mm, soft light';

  @override
  String get imageAction => 'Action';

  @override
  String get imageAspect => 'Aspect';

  @override
  String get imageVariants => 'Variants';

  @override
  String get imageModel => 'Model';

  @override
  String get imageProviderDefault => 'Provider default';

  @override
  String get imageRun => 'Run request';

  @override
  String get imageWorking => 'Working…';

  @override
  String get imageResult => 'Result';

  @override
  String get imageTaskId => 'Task id';

  @override
  String get imageArtifacts => 'Artifacts';

  @override
  String get imageCompatibleModels => 'Compatible image models';

  @override
  String get imageNoModel =>
      'No image model passed the runtime gate. Configure LAIW_IMAGE_PROVIDER_URL or install a local image model.';

  @override
  String imageFailed(String error) {
    return 'Image request failed: $error';
  }

  @override
  String get videoTitle => 'Generation runtime';

  @override
  String videoRuntimeWired(String list) {
    return 'Wired runtimes: $list. A request runs only when its weights are present locally.';
  }

  @override
  String get videoRuntimeNotWired =>
      'No video generation runtime is wired in this build. Requests will report NOT_CONFIGURED — nothing is fabricated.';

  @override
  String get videoRuntimeStatus => 'Runtime status';

  @override
  String get videoWeightsMissing => 'Weights missing';

  @override
  String get videoRegisteredModels => 'Registered models';

  @override
  String get videoI2vTitle => 'Image-to-video';

  @override
  String get videoNoModels =>
      'No video model is registered by the backend. Video generation reports NOT_CONFIGURED — honestly, nothing is fabricated.';

  @override
  String get videoSourceImage => 'Source image (local path on the server)';

  @override
  String get videoSourceHint => '/path/on/server/input.png';

  @override
  String get videoSourceHelper =>
      'Remote URLs are rejected by design — no implicit download.';

  @override
  String get videoMotionPrompt => 'Motion prompt';

  @override
  String get videoMotionHint => 'Slow camera push-in, leaves drifting…';

  @override
  String get videoDuration => 'Duration';

  @override
  String get videoWidth => 'Width';

  @override
  String get videoHeight => 'Height';

  @override
  String get videoFps => 'FPS';

  @override
  String get videoGenerate => 'Generate video';

  @override
  String get videoGenerating => 'Generating…';

  @override
  String get videoResult => 'Result';

  @override
  String get videoArtifact => 'Artifact';

  @override
  String videoFailed(String error) {
    return 'Video request failed: $error';
  }

  @override
  String get workspaceTitle => 'Project Workspace';

  @override
  String get workspaceCannotLoad => 'Cannot load workspace';

  @override
  String get workspaceNoWorkspace => 'No workspace yet';

  @override
  String get workspaceNoWorkspaceMessage =>
      'Create a project to store conversations, documents and generations.';

  @override
  String get workspaceCreateLoad => 'Create / load project';

  @override
  String get workspaceProjectId => 'Project id';

  @override
  String get workspaceUpdated => 'Updated';

  @override
  String get workspaceConversations => 'Conversations';

  @override
  String get workspaceDocuments => 'Documents';

  @override
  String get workspaceSlideDecks => 'Slide decks';

  @override
  String get workspaceFiles => 'Files';

  @override
  String get workspaceGenerations => 'Generations';

  @override
  String get workspaceNoDocuments => 'No documents yet.';

  @override
  String get workspaceNoSlides => 'No slide decks yet.';

  @override
  String get workspaceNoConversations => 'No conversations yet.';

  @override
  String get workspaceNoFiles => 'No files uploaded yet.';

  @override
  String get workspaceNoGenerations => 'No generations yet.';

  @override
  String get workspaceUploadedFiles => 'Uploaded files';

  @override
  String get workspaceProject => 'Project';

  @override
  String workspaceFailed(String error) {
    return 'Workspace failed to load: $error';
  }

  @override
  String get modelsTitle => 'Models';

  @override
  String modelsUsableCatalog(int usable, int total) {
    return '$usable usable / $total catalog';
  }

  @override
  String get modelsSearchHint => 'Search models or providers…';

  @override
  String get modelsNoMatch => 'No models match';

  @override
  String get modelsNoMatchMessage =>
      'Adjust the filter or configure a provider on the backend.';

  @override
  String get modelsFilterAll => 'All';

  @override
  String get modelsFilterChat => 'Chat';

  @override
  String get modelsFilterReasoning => 'Reasoning';

  @override
  String get modelsFilterCoding => 'Coding';

  @override
  String get modelsFilterVision => 'Vision';

  @override
  String get modelsFilterImage => 'Image';

  @override
  String get modelsFilterVideo => 'Video';

  @override
  String get modelsFilterEmbedding => 'Embedding';

  @override
  String get modelsModelId => 'Model id';

  @override
  String get modelsKind => 'Kind';

  @override
  String get modelsServingRuntime => 'Serving runtime';

  @override
  String get modelsLocal => 'Local';

  @override
  String get modelsRuntimeAvailable => 'Runtime available';

  @override
  String get modelsContextWindow => 'Context window';

  @override
  String get modelsCostTier => 'Cost tier';

  @override
  String get modelsLastError => 'Last error';

  @override
  String get modelsRunHealthCheck => 'Run real health check';

  @override
  String get modelsProbing => 'Probing…';

  @override
  String get modelsHealthReport => 'Health report';

  @override
  String get modelsOk => 'OK';

  @override
  String get modelsLatency => 'Latency';

  @override
  String get providersTitle => 'Providers';

  @override
  String get providersEmpty => 'No provider reported by the backend.';

  @override
  String get providersRuntimeMatrix => 'Runtime capability matrix';

  @override
  String get providersNoRuntime => 'No runtime matrix available.';

  @override
  String get providersConfigured => 'Configured';

  @override
  String get providersType => 'Type';

  @override
  String get providersLocal => 'local (no egress)';

  @override
  String get providersRemote => 'remote';

  @override
  String get providersModelsDiscovered => 'Models discovered';

  @override
  String get providersModelsAvailable => 'Models available';

  @override
  String get providersEndpoint => 'Endpoint';

  @override
  String get providersTestConnection => 'Test connection';

  @override
  String providersConnectionTest(String name) {
    return 'Connection test · $name';
  }

  @override
  String get providersNoResults => 'No results returned.';

  @override
  String get providersAdapter => 'Adapter';

  @override
  String get providersCapabilities => 'Capabilities';

  @override
  String get historyTitle => 'History';

  @override
  String get historyEmpty => 'No generation history yet';

  @override
  String get historyEmptyMessage =>
      'Chat and generation tasks will appear here.';

  @override
  String get historyGenerationId => 'Generation id';

  @override
  String get historyKind => 'Kind';

  @override
  String get historyStarted => 'Started';

  @override
  String get historyCompleted => 'Completed';

  @override
  String get historyError => 'Error';

  @override
  String get historyOutput => 'Output';

  @override
  String get historyStoredResult => 'Stored result';

  @override
  String get historyModelMissing => 'model: —';

  @override
  String get historyCannotLoadTask => 'Cannot load task';

  @override
  String get languageName => 'English';
}
