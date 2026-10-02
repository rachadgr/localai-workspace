import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_ar.dart';
import 'app_localizations_en.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
    : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
        delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('ar'),
    Locale('en'),
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'ASAF AI'**
  String get appTitle;

  /// No description provided for @appTagline.
  ///
  /// In en, this message translates to:
  /// **'AI Creation & Generation Studio'**
  String get appTagline;

  /// No description provided for @navDashboard.
  ///
  /// In en, this message translates to:
  /// **'Dashboard'**
  String get navDashboard;

  /// No description provided for @navChat.
  ///
  /// In en, this message translates to:
  /// **'Chat'**
  String get navChat;

  /// No description provided for @navImage.
  ///
  /// In en, this message translates to:
  /// **'Image'**
  String get navImage;

  /// No description provided for @navVideo.
  ///
  /// In en, this message translates to:
  /// **'Video'**
  String get navVideo;

  /// No description provided for @navWorkspace.
  ///
  /// In en, this message translates to:
  /// **'Workspace'**
  String get navWorkspace;

  /// No description provided for @navModels.
  ///
  /// In en, this message translates to:
  /// **'Models'**
  String get navModels;

  /// No description provided for @navProviders.
  ///
  /// In en, this message translates to:
  /// **'Providers'**
  String get navProviders;

  /// No description provided for @navHistory.
  ///
  /// In en, this message translates to:
  /// **'History'**
  String get navHistory;

  /// No description provided for @navSettings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get navSettings;

  /// No description provided for @menu.
  ///
  /// In en, this message translates to:
  /// **'Menu'**
  String get menu;

  /// No description provided for @refresh.
  ///
  /// In en, this message translates to:
  /// **'Refresh'**
  String get refresh;

  /// No description provided for @retry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retry;

  /// No description provided for @close.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get close;

  /// No description provided for @test.
  ///
  /// In en, this message translates to:
  /// **'Test'**
  String get test;

  /// No description provided for @reset.
  ///
  /// In en, this message translates to:
  /// **'Reset'**
  String get reset;

  /// No description provided for @settings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get settings;

  /// No description provided for @history.
  ///
  /// In en, this message translates to:
  /// **'History'**
  String get history;

  /// No description provided for @model.
  ///
  /// In en, this message translates to:
  /// **'Model'**
  String get model;

  /// No description provided for @status.
  ///
  /// In en, this message translates to:
  /// **'Status'**
  String get status;

  /// No description provided for @provider.
  ///
  /// In en, this message translates to:
  /// **'Provider'**
  String get provider;

  /// No description provided for @reason.
  ///
  /// In en, this message translates to:
  /// **'Reason'**
  String get reason;

  /// No description provided for @loading.
  ///
  /// In en, this message translates to:
  /// **'Loading…'**
  String get loading;

  /// No description provided for @commonUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Unavailable.'**
  String get commonUnavailable;

  /// No description provided for @commonNoData.
  ///
  /// In en, this message translates to:
  /// **'No data available from {url}.'**
  String commonNoData(String url);

  /// No description provided for @commonNoneWired.
  ///
  /// In en, this message translates to:
  /// **'none wired'**
  String get commonNoneWired;

  /// No description provided for @yes.
  ///
  /// In en, this message translates to:
  /// **'yes'**
  String get yes;

  /// No description provided for @no.
  ///
  /// In en, this message translates to:
  /// **'no'**
  String get no;

  /// No description provided for @dash.
  ///
  /// In en, this message translates to:
  /// **'—'**
  String get dash;

  /// No description provided for @connectivityCannotReach.
  ///
  /// In en, this message translates to:
  /// **'Cannot reach {url}. Check the server URL in Settings.'**
  String connectivityCannotReach(String url);

  /// No description provided for @loginSignInTitle.
  ///
  /// In en, this message translates to:
  /// **'Sign in to your studio'**
  String get loginSignInTitle;

  /// No description provided for @loginRegisterTitle.
  ///
  /// In en, this message translates to:
  /// **'Create your account'**
  String get loginRegisterTitle;

  /// No description provided for @loginSignInSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Authenticate against your ASAF AI server to continue.'**
  String get loginSignInSubtitle;

  /// No description provided for @loginRegisterSubtitle.
  ///
  /// In en, this message translates to:
  /// **'Registration may be disabled by the server administrator.'**
  String get loginRegisterSubtitle;

  /// No description provided for @loginDisplayName.
  ///
  /// In en, this message translates to:
  /// **'Display name'**
  String get loginDisplayName;

  /// No description provided for @loginDisplayNameHint.
  ///
  /// In en, this message translates to:
  /// **'ASAF Creator'**
  String get loginDisplayNameHint;

  /// No description provided for @loginEmail.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get loginEmail;

  /// No description provided for @loginEmailHint.
  ///
  /// In en, this message translates to:
  /// **'you@example.com'**
  String get loginEmailHint;

  /// No description provided for @loginPassword.
  ///
  /// In en, this message translates to:
  /// **'Password'**
  String get loginPassword;

  /// No description provided for @loginServerUrl.
  ///
  /// In en, this message translates to:
  /// **'Server URL'**
  String get loginServerUrl;

  /// No description provided for @loginServerUrlHint.
  ///
  /// In en, this message translates to:
  /// **'https://your-tunnel.trycloudflare.com'**
  String get loginServerUrlHint;

  /// No description provided for @loginServerUrlHelper.
  ///
  /// In en, this message translates to:
  /// **'Your ASAF AI backend URL. Use the public HTTPS tunnel URL for a hosted server, or your LAN IP on the same Wi-Fi.'**
  String get loginServerUrlHelper;

  /// No description provided for @loginTestConnection.
  ///
  /// In en, this message translates to:
  /// **'Test connection'**
  String get loginTestConnection;

  /// No description provided for @loginServerReachable.
  ///
  /// In en, this message translates to:
  /// **'Server reachable'**
  String get loginServerReachable;

  /// No description provided for @loginSignIn.
  ///
  /// In en, this message translates to:
  /// **'Sign in'**
  String get loginSignIn;

  /// No description provided for @loginCreateAccount.
  ///
  /// In en, this message translates to:
  /// **'Create account'**
  String get loginCreateAccount;

  /// No description provided for @loginHaveAccount.
  ///
  /// In en, this message translates to:
  /// **'I already have an account'**
  String get loginHaveAccount;

  /// No description provided for @loginNeedAccount.
  ///
  /// In en, this message translates to:
  /// **'Create a new account'**
  String get loginNeedAccount;

  /// No description provided for @loginInvalidUrl.
  ///
  /// In en, this message translates to:
  /// **'Enter a valid server URL (e.g. https://your-tunnel.trycloudflare.com).'**
  String get loginInvalidUrl;

  /// No description provided for @loginNoResponse.
  ///
  /// In en, this message translates to:
  /// **'No response from {url}/api/health. Is the server running and reachable?'**
  String loginNoResponse(String url);

  /// No description provided for @loginTestFailed.
  ///
  /// In en, this message translates to:
  /// **'Connection test failed: {error}'**
  String loginTestFailed(String error);

  /// No description provided for @loginFailed.
  ///
  /// In en, this message translates to:
  /// **'Sign in failed: {error}'**
  String loginFailed(String error);

  /// No description provided for @settingsConnection.
  ///
  /// In en, this message translates to:
  /// **'Connection'**
  String get settingsConnection;

  /// No description provided for @settingsServerUrl.
  ///
  /// In en, this message translates to:
  /// **'ASAF AI server URL'**
  String get settingsServerUrl;

  /// No description provided for @settingsServerUrlHelper.
  ///
  /// In en, this message translates to:
  /// **'The public HTTPS tunnel URL of your backend, or your LAN IP on the same Wi-Fi. Never a hardcoded emulator address.'**
  String get settingsServerUrlHelper;

  /// No description provided for @settingsSaveReconnect.
  ///
  /// In en, this message translates to:
  /// **'Save & reconnect'**
  String get settingsSaveReconnect;

  /// No description provided for @settingsHealthCheck.
  ///
  /// In en, this message translates to:
  /// **'Health check:'**
  String get settingsHealthCheck;

  /// No description provided for @settingsUrlSaved.
  ///
  /// In en, this message translates to:
  /// **'Server URL saved. Reconnecting…'**
  String get settingsUrlSaved;

  /// No description provided for @settingsNoResponse.
  ///
  /// In en, this message translates to:
  /// **'No response from {url}/api/health.'**
  String settingsNoResponse(String url);

  /// No description provided for @settingsSession.
  ///
  /// In en, this message translates to:
  /// **'Session'**
  String get settingsSession;

  /// No description provided for @settingsSignedInAs.
  ///
  /// In en, this message translates to:
  /// **'Signed in as'**
  String get settingsSignedInAs;

  /// No description provided for @settingsEmail.
  ///
  /// In en, this message translates to:
  /// **'Email'**
  String get settingsEmail;

  /// No description provided for @settingsSignOut.
  ///
  /// In en, this message translates to:
  /// **'Sign out'**
  String get settingsSignOut;

  /// No description provided for @settingsBackendSettings.
  ///
  /// In en, this message translates to:
  /// **'Backend settings'**
  String get settingsBackendSettings;

  /// No description provided for @settingsAbout.
  ///
  /// In en, this message translates to:
  /// **'About ASAF AI'**
  String get settingsAbout;

  /// No description provided for @settingsProduct.
  ///
  /// In en, this message translates to:
  /// **'Product'**
  String get settingsProduct;

  /// No description provided for @settingsClientVersion.
  ///
  /// In en, this message translates to:
  /// **'Client version'**
  String get settingsClientVersion;

  /// No description provided for @settingsBackend.
  ///
  /// In en, this message translates to:
  /// **'Backend'**
  String get settingsBackend;

  /// No description provided for @settingsEnvironment.
  ///
  /// In en, this message translates to:
  /// **'Environment'**
  String get settingsEnvironment;

  /// No description provided for @settingsAppearance.
  ///
  /// In en, this message translates to:
  /// **'Appearance'**
  String get settingsAppearance;

  /// No description provided for @settingsLanguage.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get settingsLanguage;

  /// No description provided for @settingsTheme.
  ///
  /// In en, this message translates to:
  /// **'Theme'**
  String get settingsTheme;

  /// No description provided for @settingsThemeDark.
  ///
  /// In en, this message translates to:
  /// **'Dark'**
  String get settingsThemeDark;

  /// No description provided for @settingsThemeLight.
  ///
  /// In en, this message translates to:
  /// **'Light'**
  String get settingsThemeLight;

  /// No description provided for @settingsAboutBody.
  ///
  /// In en, this message translates to:
  /// **'ASAF AI is an AI Creation & Generation Studio. This client never fabricates results: every model, provider, runtime and generation status you see comes from your backend, reported honestly.'**
  String get settingsAboutBody;

  /// No description provided for @dashCannotReach.
  ///
  /// In en, this message translates to:
  /// **'Cannot reach the backend'**
  String get dashCannotReach;

  /// No description provided for @dashHeroTitle.
  ///
  /// In en, this message translates to:
  /// **'ASAF AI Studio'**
  String get dashHeroTitle;

  /// No description provided for @dashHealthy.
  ///
  /// In en, this message translates to:
  /// **'All systems report healthy.'**
  String get dashHealthy;

  /// No description provided for @dashDegraded.
  ///
  /// In en, this message translates to:
  /// **'Studio is running in a degraded state — see the details below.'**
  String get dashDegraded;

  /// No description provided for @dashModelsUsable.
  ///
  /// In en, this message translates to:
  /// **'Models usable'**
  String get dashModelsUsable;

  /// No description provided for @dashOfCatalog.
  ///
  /// In en, this message translates to:
  /// **'of {count} in catalog'**
  String dashOfCatalog(int count);

  /// No description provided for @dashProvidersOnline.
  ///
  /// In en, this message translates to:
  /// **'Providers online'**
  String get dashProvidersOnline;

  /// No description provided for @dashOfConfigured.
  ///
  /// In en, this message translates to:
  /// **'of {count} configured'**
  String dashOfConfigured(int count);

  /// No description provided for @dashTasksRouteable.
  ///
  /// In en, this message translates to:
  /// **'Tasks routeable'**
  String get dashTasksRouteable;

  /// No description provided for @dashOfTaskClasses.
  ///
  /// In en, this message translates to:
  /// **'of {count} task classes'**
  String dashOfTaskClasses(int count);

  /// No description provided for @dashProjects.
  ///
  /// In en, this message translates to:
  /// **'Projects'**
  String get dashProjects;

  /// No description provided for @dashRecentTasks.
  ///
  /// In en, this message translates to:
  /// **'{count} recent task(s)'**
  String dashRecentTasks(int count);

  /// No description provided for @dashQuickActions.
  ///
  /// In en, this message translates to:
  /// **'Quick actions'**
  String get dashQuickActions;

  /// No description provided for @dashQuickActionsEmpty.
  ///
  /// In en, this message translates to:
  /// **'Quick actions unavailable — backend did not report any.'**
  String get dashQuickActionsEmpty;

  /// No description provided for @dashRecentGenerations.
  ///
  /// In en, this message translates to:
  /// **'Recent generations'**
  String get dashRecentGenerations;

  /// No description provided for @dashNoTasks.
  ///
  /// In en, this message translates to:
  /// **'No tasks yet. Chat and generations will appear here.'**
  String get dashNoTasks;

  /// No description provided for @dashRecentDocuments.
  ///
  /// In en, this message translates to:
  /// **'Recent documents'**
  String get dashRecentDocuments;

  /// No description provided for @dashRecentSlides.
  ///
  /// In en, this message translates to:
  /// **'Recent slides'**
  String get dashRecentSlides;

  /// No description provided for @dashNoDocuments.
  ///
  /// In en, this message translates to:
  /// **'No documents generated yet.'**
  String get dashNoDocuments;

  /// No description provided for @dashNoSlides.
  ///
  /// In en, this message translates to:
  /// **'No slide decks generated yet.'**
  String get dashNoSlides;

  /// No description provided for @dashRuntimeHealth.
  ///
  /// In en, this message translates to:
  /// **'Runtime health'**
  String get dashRuntimeHealth;

  /// No description provided for @dashHealthUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Health unavailable.'**
  String get dashHealthUnavailable;

  /// No description provided for @dashBackend.
  ///
  /// In en, this message translates to:
  /// **'Backend'**
  String get dashBackend;

  /// No description provided for @dashEnvironment.
  ///
  /// In en, this message translates to:
  /// **'Environment'**
  String get dashEnvironment;

  /// No description provided for @dashDatabase.
  ///
  /// In en, this message translates to:
  /// **'Database'**
  String get dashDatabase;

  /// No description provided for @dashOverallStatus.
  ///
  /// In en, this message translates to:
  /// **'Overall status'**
  String get dashOverallStatus;

  /// No description provided for @dashModelLayer.
  ///
  /// In en, this message translates to:
  /// **'Model layer'**
  String get dashModelLayer;

  /// No description provided for @dashImageProvider.
  ///
  /// In en, this message translates to:
  /// **'Image provider'**
  String get dashImageProvider;

  /// No description provided for @dashNetworkTools.
  ///
  /// In en, this message translates to:
  /// **'Network tools'**
  String get dashNetworkTools;

  /// No description provided for @dashCodeExecution.
  ///
  /// In en, this message translates to:
  /// **'Code execution'**
  String get dashCodeExecution;

  /// No description provided for @dashConfigured.
  ///
  /// In en, this message translates to:
  /// **'configured'**
  String get dashConfigured;

  /// No description provided for @dashNotConfigured.
  ///
  /// In en, this message translates to:
  /// **'not configured'**
  String get dashNotConfigured;

  /// No description provided for @dashEnabled.
  ///
  /// In en, this message translates to:
  /// **'enabled'**
  String get dashEnabled;

  /// No description provided for @dashDisabled.
  ///
  /// In en, this message translates to:
  /// **'disabled'**
  String get dashDisabled;

  /// No description provided for @dashTaskRouting.
  ///
  /// In en, this message translates to:
  /// **'Task routing'**
  String get dashTaskRouting;

  /// No description provided for @dashRoutingUnavailable.
  ///
  /// In en, this message translates to:
  /// **'Routing diagnostics unavailable.'**
  String get dashRoutingUnavailable;

  /// No description provided for @chatTitle.
  ///
  /// In en, this message translates to:
  /// **'Chat'**
  String get chatTitle;

  /// No description provided for @chatStartConversation.
  ///
  /// In en, this message translates to:
  /// **'Start a conversation'**
  String get chatStartConversation;

  /// No description provided for @chatNoModel.
  ///
  /// In en, this message translates to:
  /// **'No chat-capable model is AVAILABLE on the backend. Configure a provider to enable chat.'**
  String get chatNoModel;

  /// No description provided for @chatAskAnything.
  ///
  /// In en, this message translates to:
  /// **'Ask anything. Generation streams live from your ASAF AI backend.'**
  String get chatAskAnything;

  /// No description provided for @chatAutoRoute.
  ///
  /// In en, this message translates to:
  /// **'Auto-route'**
  String get chatAutoRoute;

  /// No description provided for @chatYou.
  ///
  /// In en, this message translates to:
  /// **'You'**
  String get chatYou;

  /// No description provided for @chatAssistant.
  ///
  /// In en, this message translates to:
  /// **'ASAF AI'**
  String get chatAssistant;

  /// No description provided for @chatMessageHint.
  ///
  /// In en, this message translates to:
  /// **'Message ASAF AI…'**
  String get chatMessageHint;

  /// No description provided for @chatUnavailableHint.
  ///
  /// In en, this message translates to:
  /// **'Chat unavailable — no model is AVAILABLE'**
  String get chatUnavailableHint;

  /// No description provided for @chatEmptyResponse.
  ///
  /// In en, this message translates to:
  /// **'(the model returned an empty response)'**
  String get chatEmptyResponse;

  /// No description provided for @chatNoProject.
  ///
  /// In en, this message translates to:
  /// **'No project available — the backend did not return one.'**
  String get chatNoProject;

  /// No description provided for @chatGenerationFailed.
  ///
  /// In en, this message translates to:
  /// **'Generation failed.'**
  String get chatGenerationFailed;

  /// No description provided for @imageTitle.
  ///
  /// In en, this message translates to:
  /// **'Image generation'**
  String get imageTitle;

  /// No description provided for @imageNotConfiguredBanner.
  ///
  /// In en, this message translates to:
  /// **'No image provider is configured on the backend. Prompt/brief helpers work; actual image generation reports UNAVAILABLE (never a fabricated image).'**
  String get imageNotConfiguredBanner;

  /// No description provided for @imageDescription.
  ///
  /// In en, this message translates to:
  /// **'Description'**
  String get imageDescription;

  /// No description provided for @imageDescriptionHint.
  ///
  /// In en, this message translates to:
  /// **'A cinematic portrait of a robot artist in a neon studio…'**
  String get imageDescriptionHint;

  /// No description provided for @imageStyle.
  ///
  /// In en, this message translates to:
  /// **'Style (optional)'**
  String get imageStyle;

  /// No description provided for @imageStyleHint.
  ///
  /// In en, this message translates to:
  /// **'photorealistic, 35mm, soft light'**
  String get imageStyleHint;

  /// No description provided for @imageAction.
  ///
  /// In en, this message translates to:
  /// **'Action'**
  String get imageAction;

  /// No description provided for @imageAspect.
  ///
  /// In en, this message translates to:
  /// **'Aspect'**
  String get imageAspect;

  /// No description provided for @imageVariants.
  ///
  /// In en, this message translates to:
  /// **'Variants'**
  String get imageVariants;

  /// No description provided for @imageModel.
  ///
  /// In en, this message translates to:
  /// **'Model'**
  String get imageModel;

  /// No description provided for @imageProviderDefault.
  ///
  /// In en, this message translates to:
  /// **'Provider default'**
  String get imageProviderDefault;

  /// No description provided for @imageRun.
  ///
  /// In en, this message translates to:
  /// **'Run request'**
  String get imageRun;

  /// No description provided for @imageWorking.
  ///
  /// In en, this message translates to:
  /// **'Working…'**
  String get imageWorking;

  /// No description provided for @imageResult.
  ///
  /// In en, this message translates to:
  /// **'Result'**
  String get imageResult;

  /// No description provided for @imageTaskId.
  ///
  /// In en, this message translates to:
  /// **'Task id'**
  String get imageTaskId;

  /// No description provided for @imageArtifacts.
  ///
  /// In en, this message translates to:
  /// **'Artifacts'**
  String get imageArtifacts;

  /// No description provided for @imageCompatibleModels.
  ///
  /// In en, this message translates to:
  /// **'Compatible image models'**
  String get imageCompatibleModels;

  /// No description provided for @imageNoModel.
  ///
  /// In en, this message translates to:
  /// **'No image model passed the runtime gate. Configure LAIW_IMAGE_PROVIDER_URL or install a local image model.'**
  String get imageNoModel;

  /// No description provided for @imageFailed.
  ///
  /// In en, this message translates to:
  /// **'Image request failed: {error}'**
  String imageFailed(String error);

  /// No description provided for @videoTitle.
  ///
  /// In en, this message translates to:
  /// **'Generation runtime'**
  String get videoTitle;

  /// No description provided for @videoRuntimeWired.
  ///
  /// In en, this message translates to:
  /// **'Wired runtimes: {list}. A request runs only when its weights are present locally.'**
  String videoRuntimeWired(String list);

  /// No description provided for @videoRuntimeNotWired.
  ///
  /// In en, this message translates to:
  /// **'No video generation runtime is wired in this build. Requests will report NOT_CONFIGURED — nothing is fabricated.'**
  String get videoRuntimeNotWired;

  /// No description provided for @videoRuntimeStatus.
  ///
  /// In en, this message translates to:
  /// **'Runtime status'**
  String get videoRuntimeStatus;

  /// No description provided for @videoWeightsMissing.
  ///
  /// In en, this message translates to:
  /// **'Weights missing'**
  String get videoWeightsMissing;

  /// No description provided for @videoRegisteredModels.
  ///
  /// In en, this message translates to:
  /// **'Registered models'**
  String get videoRegisteredModels;

  /// No description provided for @videoI2vTitle.
  ///
  /// In en, this message translates to:
  /// **'Image-to-video'**
  String get videoI2vTitle;

  /// No description provided for @videoNoModels.
  ///
  /// In en, this message translates to:
  /// **'No video model is registered by the backend. Video generation reports NOT_CONFIGURED — honestly, nothing is fabricated.'**
  String get videoNoModels;

  /// No description provided for @videoSourceImage.
  ///
  /// In en, this message translates to:
  /// **'Source image (local path on the server)'**
  String get videoSourceImage;

  /// No description provided for @videoSourceHint.
  ///
  /// In en, this message translates to:
  /// **'/path/on/server/input.png'**
  String get videoSourceHint;

  /// No description provided for @videoSourceHelper.
  ///
  /// In en, this message translates to:
  /// **'Remote URLs are rejected by design — no implicit download.'**
  String get videoSourceHelper;

  /// No description provided for @videoMotionPrompt.
  ///
  /// In en, this message translates to:
  /// **'Motion prompt'**
  String get videoMotionPrompt;

  /// No description provided for @videoMotionHint.
  ///
  /// In en, this message translates to:
  /// **'Slow camera push-in, leaves drifting…'**
  String get videoMotionHint;

  /// No description provided for @videoDuration.
  ///
  /// In en, this message translates to:
  /// **'Duration'**
  String get videoDuration;

  /// No description provided for @videoWidth.
  ///
  /// In en, this message translates to:
  /// **'Width'**
  String get videoWidth;

  /// No description provided for @videoHeight.
  ///
  /// In en, this message translates to:
  /// **'Height'**
  String get videoHeight;

  /// No description provided for @videoFps.
  ///
  /// In en, this message translates to:
  /// **'FPS'**
  String get videoFps;

  /// No description provided for @videoGenerate.
  ///
  /// In en, this message translates to:
  /// **'Generate video'**
  String get videoGenerate;

  /// No description provided for @videoGenerating.
  ///
  /// In en, this message translates to:
  /// **'Generating…'**
  String get videoGenerating;

  /// No description provided for @videoResult.
  ///
  /// In en, this message translates to:
  /// **'Result'**
  String get videoResult;

  /// No description provided for @videoArtifact.
  ///
  /// In en, this message translates to:
  /// **'Artifact'**
  String get videoArtifact;

  /// No description provided for @videoFailed.
  ///
  /// In en, this message translates to:
  /// **'Video request failed: {error}'**
  String videoFailed(String error);

  /// No description provided for @workspaceTitle.
  ///
  /// In en, this message translates to:
  /// **'Project Workspace'**
  String get workspaceTitle;

  /// No description provided for @workspaceCannotLoad.
  ///
  /// In en, this message translates to:
  /// **'Cannot load workspace'**
  String get workspaceCannotLoad;

  /// No description provided for @workspaceNoWorkspace.
  ///
  /// In en, this message translates to:
  /// **'No workspace yet'**
  String get workspaceNoWorkspace;

  /// No description provided for @workspaceNoWorkspaceMessage.
  ///
  /// In en, this message translates to:
  /// **'Create a project to store conversations, documents and generations.'**
  String get workspaceNoWorkspaceMessage;

  /// No description provided for @workspaceCreateLoad.
  ///
  /// In en, this message translates to:
  /// **'Create / load project'**
  String get workspaceCreateLoad;

  /// No description provided for @workspaceProjectId.
  ///
  /// In en, this message translates to:
  /// **'Project id'**
  String get workspaceProjectId;

  /// No description provided for @workspaceUpdated.
  ///
  /// In en, this message translates to:
  /// **'Updated'**
  String get workspaceUpdated;

  /// No description provided for @workspaceConversations.
  ///
  /// In en, this message translates to:
  /// **'Conversations'**
  String get workspaceConversations;

  /// No description provided for @workspaceDocuments.
  ///
  /// In en, this message translates to:
  /// **'Documents'**
  String get workspaceDocuments;

  /// No description provided for @workspaceSlideDecks.
  ///
  /// In en, this message translates to:
  /// **'Slide decks'**
  String get workspaceSlideDecks;

  /// No description provided for @workspaceFiles.
  ///
  /// In en, this message translates to:
  /// **'Files'**
  String get workspaceFiles;

  /// No description provided for @workspaceGenerations.
  ///
  /// In en, this message translates to:
  /// **'Generations'**
  String get workspaceGenerations;

  /// No description provided for @workspaceNoDocuments.
  ///
  /// In en, this message translates to:
  /// **'No documents yet.'**
  String get workspaceNoDocuments;

  /// No description provided for @workspaceNoSlides.
  ///
  /// In en, this message translates to:
  /// **'No slide decks yet.'**
  String get workspaceNoSlides;

  /// No description provided for @workspaceNoConversations.
  ///
  /// In en, this message translates to:
  /// **'No conversations yet.'**
  String get workspaceNoConversations;

  /// No description provided for @workspaceNoFiles.
  ///
  /// In en, this message translates to:
  /// **'No files uploaded yet.'**
  String get workspaceNoFiles;

  /// No description provided for @workspaceNoGenerations.
  ///
  /// In en, this message translates to:
  /// **'No generations yet.'**
  String get workspaceNoGenerations;

  /// No description provided for @workspaceUploadedFiles.
  ///
  /// In en, this message translates to:
  /// **'Uploaded files'**
  String get workspaceUploadedFiles;

  /// No description provided for @workspaceProject.
  ///
  /// In en, this message translates to:
  /// **'Project'**
  String get workspaceProject;

  /// No description provided for @workspaceFailed.
  ///
  /// In en, this message translates to:
  /// **'Workspace failed to load: {error}'**
  String workspaceFailed(String error);

  /// No description provided for @modelsTitle.
  ///
  /// In en, this message translates to:
  /// **'Models'**
  String get modelsTitle;

  /// No description provided for @modelsUsableCatalog.
  ///
  /// In en, this message translates to:
  /// **'{usable} usable / {total} catalog'**
  String modelsUsableCatalog(int usable, int total);

  /// No description provided for @modelsSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search models or providers…'**
  String get modelsSearchHint;

  /// No description provided for @modelsNoMatch.
  ///
  /// In en, this message translates to:
  /// **'No models match'**
  String get modelsNoMatch;

  /// No description provided for @modelsNoMatchMessage.
  ///
  /// In en, this message translates to:
  /// **'Adjust the filter or configure a provider on the backend.'**
  String get modelsNoMatchMessage;

  /// No description provided for @modelsFilterAll.
  ///
  /// In en, this message translates to:
  /// **'All'**
  String get modelsFilterAll;

  /// No description provided for @modelsFilterChat.
  ///
  /// In en, this message translates to:
  /// **'Chat'**
  String get modelsFilterChat;

  /// No description provided for @modelsFilterReasoning.
  ///
  /// In en, this message translates to:
  /// **'Reasoning'**
  String get modelsFilterReasoning;

  /// No description provided for @modelsFilterCoding.
  ///
  /// In en, this message translates to:
  /// **'Coding'**
  String get modelsFilterCoding;

  /// No description provided for @modelsFilterVision.
  ///
  /// In en, this message translates to:
  /// **'Vision'**
  String get modelsFilterVision;

  /// No description provided for @modelsFilterImage.
  ///
  /// In en, this message translates to:
  /// **'Image'**
  String get modelsFilterImage;

  /// No description provided for @modelsFilterVideo.
  ///
  /// In en, this message translates to:
  /// **'Video'**
  String get modelsFilterVideo;

  /// No description provided for @modelsFilterEmbedding.
  ///
  /// In en, this message translates to:
  /// **'Embedding'**
  String get modelsFilterEmbedding;

  /// No description provided for @modelsModelId.
  ///
  /// In en, this message translates to:
  /// **'Model id'**
  String get modelsModelId;

  /// No description provided for @modelsKind.
  ///
  /// In en, this message translates to:
  /// **'Kind'**
  String get modelsKind;

  /// No description provided for @modelsServingRuntime.
  ///
  /// In en, this message translates to:
  /// **'Serving runtime'**
  String get modelsServingRuntime;

  /// No description provided for @modelsLocal.
  ///
  /// In en, this message translates to:
  /// **'Local'**
  String get modelsLocal;

  /// No description provided for @modelsRuntimeAvailable.
  ///
  /// In en, this message translates to:
  /// **'Runtime available'**
  String get modelsRuntimeAvailable;

  /// No description provided for @modelsContextWindow.
  ///
  /// In en, this message translates to:
  /// **'Context window'**
  String get modelsContextWindow;

  /// No description provided for @modelsCostTier.
  ///
  /// In en, this message translates to:
  /// **'Cost tier'**
  String get modelsCostTier;

  /// No description provided for @modelsLastError.
  ///
  /// In en, this message translates to:
  /// **'Last error'**
  String get modelsLastError;

  /// No description provided for @modelsRunHealthCheck.
  ///
  /// In en, this message translates to:
  /// **'Run real health check'**
  String get modelsRunHealthCheck;

  /// No description provided for @modelsProbing.
  ///
  /// In en, this message translates to:
  /// **'Probing…'**
  String get modelsProbing;

  /// No description provided for @modelsHealthReport.
  ///
  /// In en, this message translates to:
  /// **'Health report'**
  String get modelsHealthReport;

  /// No description provided for @modelsOk.
  ///
  /// In en, this message translates to:
  /// **'OK'**
  String get modelsOk;

  /// No description provided for @modelsLatency.
  ///
  /// In en, this message translates to:
  /// **'Latency'**
  String get modelsLatency;

  /// No description provided for @providersTitle.
  ///
  /// In en, this message translates to:
  /// **'Providers'**
  String get providersTitle;

  /// No description provided for @providersEmpty.
  ///
  /// In en, this message translates to:
  /// **'No provider reported by the backend.'**
  String get providersEmpty;

  /// No description provided for @providersRuntimeMatrix.
  ///
  /// In en, this message translates to:
  /// **'Runtime capability matrix'**
  String get providersRuntimeMatrix;

  /// No description provided for @providersNoRuntime.
  ///
  /// In en, this message translates to:
  /// **'No runtime matrix available.'**
  String get providersNoRuntime;

  /// No description provided for @providersConfigured.
  ///
  /// In en, this message translates to:
  /// **'Configured'**
  String get providersConfigured;

  /// No description provided for @providersType.
  ///
  /// In en, this message translates to:
  /// **'Type'**
  String get providersType;

  /// No description provided for @providersLocal.
  ///
  /// In en, this message translates to:
  /// **'local (no egress)'**
  String get providersLocal;

  /// No description provided for @providersRemote.
  ///
  /// In en, this message translates to:
  /// **'remote'**
  String get providersRemote;

  /// No description provided for @providersModelsDiscovered.
  ///
  /// In en, this message translates to:
  /// **'Models discovered'**
  String get providersModelsDiscovered;

  /// No description provided for @providersModelsAvailable.
  ///
  /// In en, this message translates to:
  /// **'Models available'**
  String get providersModelsAvailable;

  /// No description provided for @providersEndpoint.
  ///
  /// In en, this message translates to:
  /// **'Endpoint'**
  String get providersEndpoint;

  /// No description provided for @providersTestConnection.
  ///
  /// In en, this message translates to:
  /// **'Test connection'**
  String get providersTestConnection;

  /// No description provided for @providersConnectionTest.
  ///
  /// In en, this message translates to:
  /// **'Connection test · {name}'**
  String providersConnectionTest(String name);

  /// No description provided for @providersNoResults.
  ///
  /// In en, this message translates to:
  /// **'No results returned.'**
  String get providersNoResults;

  /// No description provided for @providersAdapter.
  ///
  /// In en, this message translates to:
  /// **'Adapter'**
  String get providersAdapter;

  /// No description provided for @providersCapabilities.
  ///
  /// In en, this message translates to:
  /// **'Capabilities'**
  String get providersCapabilities;

  /// No description provided for @historyTitle.
  ///
  /// In en, this message translates to:
  /// **'History'**
  String get historyTitle;

  /// No description provided for @historyEmpty.
  ///
  /// In en, this message translates to:
  /// **'No generation history yet'**
  String get historyEmpty;

  /// No description provided for @historyEmptyMessage.
  ///
  /// In en, this message translates to:
  /// **'Chat and generation tasks will appear here.'**
  String get historyEmptyMessage;

  /// No description provided for @historyGenerationId.
  ///
  /// In en, this message translates to:
  /// **'Generation id'**
  String get historyGenerationId;

  /// No description provided for @historyKind.
  ///
  /// In en, this message translates to:
  /// **'Kind'**
  String get historyKind;

  /// No description provided for @historyStarted.
  ///
  /// In en, this message translates to:
  /// **'Started'**
  String get historyStarted;

  /// No description provided for @historyCompleted.
  ///
  /// In en, this message translates to:
  /// **'Completed'**
  String get historyCompleted;

  /// No description provided for @historyError.
  ///
  /// In en, this message translates to:
  /// **'Error'**
  String get historyError;

  /// No description provided for @historyOutput.
  ///
  /// In en, this message translates to:
  /// **'Output'**
  String get historyOutput;

  /// No description provided for @historyStoredResult.
  ///
  /// In en, this message translates to:
  /// **'Stored result'**
  String get historyStoredResult;

  /// No description provided for @historyModelMissing.
  ///
  /// In en, this message translates to:
  /// **'model: —'**
  String get historyModelMissing;

  /// No description provided for @historyCannotLoadTask.
  ///
  /// In en, this message translates to:
  /// **'Cannot load task'**
  String get historyCannotLoadTask;

  /// No description provided for @languageName.
  ///
  /// In en, this message translates to:
  /// **'English'**
  String get languageName;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['ar', 'en'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'ar':
      return AppLocalizationsAr();
    case 'en':
      return AppLocalizationsEn();
  }

  throw FlutterError(
    'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
    'an issue with the localizations generation tool. Please file an issue '
    'on GitHub with a reproducible sample app and the gen-l10n configuration '
    'that was used.',
  );
}
