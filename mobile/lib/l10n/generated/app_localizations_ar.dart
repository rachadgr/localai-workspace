// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Arabic (`ar`).
class AppLocalizationsAr extends AppLocalizations {
  AppLocalizationsAr([String locale = 'ar']) : super(locale);

  @override
  String get appTitle => 'ASAF AI';

  @override
  String get appTagline => 'استوديو الإنشاء والتوليد بالذكاء الاصطناعي';

  @override
  String get navDashboard => 'لوحة التحكم';

  @override
  String get navChat => 'المحادثة';

  @override
  String get navImage => 'الصور';

  @override
  String get navVideo => 'الفيديو';

  @override
  String get navWorkspace => 'مساحة العمل';

  @override
  String get navModels => 'النماذج';

  @override
  String get navProviders => 'المزوّدون';

  @override
  String get navHistory => 'السجل';

  @override
  String get navSettings => 'الإعدادات';

  @override
  String get menu => 'القائمة';

  @override
  String get refresh => 'تحديث';

  @override
  String get retry => 'إعادة المحاولة';

  @override
  String get close => 'إغلاق';

  @override
  String get test => 'اختبار';

  @override
  String get reset => 'إعادة الضبط';

  @override
  String get settings => 'الإعدادات';

  @override
  String get history => 'السجل';

  @override
  String get model => 'النموذج';

  @override
  String get status => 'الحالة';

  @override
  String get provider => 'المزوّد';

  @override
  String get reason => 'السبب';

  @override
  String get loading => 'جارٍ التحميل…';

  @override
  String get commonUnavailable => 'غير متاح.';

  @override
  String commonNoData(String url) {
    return 'لا توجد بيانات متاحة من $url.';
  }

  @override
  String get commonNoneWired => 'غير موصول';

  @override
  String get yes => 'نعم';

  @override
  String get no => 'لا';

  @override
  String get dash => '—';

  @override
  String connectivityCannotReach(String url) {
    return 'تعذّر الوصول إلى $url. تحقّق من عنوان الخادم في الإعدادات.';
  }

  @override
  String get loginSignInTitle => 'تسجيل الدخول إلى الاستوديو';

  @override
  String get loginRegisterTitle => 'إنشاء حسابك';

  @override
  String get loginSignInSubtitle => 'سجّل الدخول إلى خادم ASAF AI للمتابعة.';

  @override
  String get loginRegisterSubtitle =>
      'قد يكون التسجيل معطّلًا من قِبل مسؤول الخادم.';

  @override
  String get loginDisplayName => 'الاسم المعروض';

  @override
  String get loginDisplayNameHint => 'مُنشئ ASAF';

  @override
  String get loginEmail => 'البريد الإلكتروني';

  @override
  String get loginEmailHint => 'you@example.com';

  @override
  String get loginPassword => 'كلمة المرور';

  @override
  String get loginServerUrl => 'عنوان الخادم';

  @override
  String get loginServerUrlHint => 'https://your-tunnel.trycloudflare.com';

  @override
  String get loginServerUrlHelper =>
      'عنوان خادم ASAF AI الخلفي. استخدم رابط النفق العام HTTPS لخادم مستضاف، أو عنوان IP على الشبكة المحلية عند الاتصال بنفس شبكة الواي فاي.';

  @override
  String get loginTestConnection => 'اختبار الاتصال';

  @override
  String get loginServerReachable => 'الخادم متاح';

  @override
  String get loginSignIn => 'تسجيل الدخول';

  @override
  String get loginCreateAccount => 'إنشاء حساب';

  @override
  String get loginHaveAccount => 'لديّ حساب بالفعل';

  @override
  String get loginNeedAccount => 'إنشاء حساب جديد';

  @override
  String get loginInvalidUrl =>
      'أدخل عنوان خادم صالحًا (مثال: https://your-tunnel.trycloudflare.com).';

  @override
  String loginNoResponse(String url) {
    return 'لا يوجد ردّ من $url/api/health. هل الخادم قيد التشغيل وقابل للوصول؟';
  }

  @override
  String loginTestFailed(String error) {
    return 'فشل اختبار الاتصال: $error';
  }

  @override
  String loginFailed(String error) {
    return 'فشل تسجيل الدخول: $error';
  }

  @override
  String get settingsConnection => 'الاتصال';

  @override
  String get settingsServerUrl => 'عنوان خادم ASAF AI';

  @override
  String get settingsServerUrlHelper =>
      'رابط النفق العام HTTPS للخادم الخلفي، أو عنوان IP على الشبكة المحلية عند نفس شبكة الواي فاي. ليس عنوان محاكي ثابتًا أبدًا.';

  @override
  String get settingsSaveReconnect => 'حفظ وإعادة الاتصال';

  @override
  String get settingsHealthCheck => 'فحص الحالة:';

  @override
  String get settingsUrlSaved => 'تم حفظ عنوان الخادم. جارٍ إعادة الاتصال…';

  @override
  String settingsNoResponse(String url) {
    return 'لا يوجد ردّ من $url/api/health.';
  }

  @override
  String get settingsSession => 'الجلسة';

  @override
  String get settingsSignedInAs => 'مُسجَّل الدخول باسم';

  @override
  String get settingsEmail => 'البريد الإلكتروني';

  @override
  String get settingsSignOut => 'تسجيل الخروج';

  @override
  String get settingsBackendSettings => 'إعدادات الخادم الخلفي';

  @override
  String get settingsAbout => 'حول ASAF AI';

  @override
  String get settingsProduct => 'المنتج';

  @override
  String get settingsClientVersion => 'إصدار التطبيق';

  @override
  String get settingsBackend => 'الخادم الخلفي';

  @override
  String get settingsEnvironment => 'البيئة';

  @override
  String get settingsAppearance => 'المظهر';

  @override
  String get settingsLanguage => 'اللغة';

  @override
  String get settingsTheme => 'الثيم';

  @override
  String get settingsThemeDark => 'داكن';

  @override
  String get settingsThemeLight => 'فاتح';

  @override
  String get settingsAboutBody =>
      'ASAF AI هو استوديو للإنشاء والتوليد بالذكاء الاصطناعي. لا يختلق هذا التطبيق أي نتائج أبدًا: كل حالة نموذج أو مزوّد أو وقت تشغيل أو توليد تراها تأتي من خادمك الخلفي، وتُعرض بصدق.';

  @override
  String get dashCannotReach => 'تعذّر الوصول إلى الخادم الخلفي';

  @override
  String get dashHeroTitle => 'استوديو ASAF AI';

  @override
  String get dashHealthy => 'جميع الأنظمة سليمة.';

  @override
  String get dashDegraded =>
      'الاستوديو يعمل بحالة متدهورة — راجع التفاصيل أدناه.';

  @override
  String get dashModelsUsable => 'نماذج قابلة للاستخدام';

  @override
  String dashOfCatalog(int count) {
    return 'من $count في الفهرس';
  }

  @override
  String get dashProvidersOnline => 'مزوّدون متصلون';

  @override
  String dashOfConfigured(int count) {
    return 'من $count مُهيّأ';
  }

  @override
  String get dashTasksRouteable => 'مهام قابلة للتوجيه';

  @override
  String dashOfTaskClasses(int count) {
    return 'من $count فئة مهام';
  }

  @override
  String get dashProjects => 'المشاريع';

  @override
  String dashRecentTasks(int count) {
    return '$count مهمة حديثة';
  }

  @override
  String get dashQuickActions => 'إجراءات سريعة';

  @override
  String get dashQuickActionsEmpty =>
      'الإجراءات السريعة غير متاحة — لم يُبلّغ الخادم الخلفي عن أي منها.';

  @override
  String get dashRecentGenerations => 'أحدث عمليات التوليد';

  @override
  String get dashNoTasks =>
      'لا توجد مهام بعد. ستظهر المحادثات وعمليات التوليد هنا.';

  @override
  String get dashRecentDocuments => 'أحدث المستندات';

  @override
  String get dashRecentSlides => 'أحدث العروض التقديمية';

  @override
  String get dashNoDocuments => 'لم يتم توليد أي مستندات بعد.';

  @override
  String get dashNoSlides => 'لم يتم توليد أي عروض تقديمية بعد.';

  @override
  String get dashRuntimeHealth => 'حالة وقت التشغيل';

  @override
  String get dashHealthUnavailable => 'الحالة غير متاحة.';

  @override
  String get dashBackend => 'الخادم الخلفي';

  @override
  String get dashEnvironment => 'البيئة';

  @override
  String get dashDatabase => 'قاعدة البيانات';

  @override
  String get dashOverallStatus => 'الحالة العامة';

  @override
  String get dashModelLayer => 'طبقة النماذج';

  @override
  String get dashImageProvider => 'مزوّد الصور';

  @override
  String get dashNetworkTools => 'أدوات الشبكة';

  @override
  String get dashCodeExecution => 'تنفيذ الشيفرة';

  @override
  String get dashConfigured => 'مُهيّأ';

  @override
  String get dashNotConfigured => 'غير مُهيّأ';

  @override
  String get dashEnabled => 'مُمكّن';

  @override
  String get dashDisabled => 'مُعطّل';

  @override
  String get dashTaskRouting => 'توجيه المهام';

  @override
  String get dashRoutingUnavailable => 'تشخيصات التوجيه غير متاحة.';

  @override
  String get chatTitle => 'المحادثة';

  @override
  String get chatStartConversation => 'ابدأ محادثة';

  @override
  String get chatNoModel =>
      'لا يوجد نموذج يدعم المحادثة وحالته AVAILABLE على الخادم الخلفي. هيّئ مزوّدًا لتمكين المحادثة.';

  @override
  String get chatAskAnything =>
      'اسأل عن أي شيء. يُبَثّ التوليد مباشرةً من خادم ASAF AI.';

  @override
  String get chatAutoRoute => 'توجيه تلقائي';

  @override
  String get chatYou => 'أنت';

  @override
  String get chatAssistant => 'ASAF AI';

  @override
  String get chatMessageHint => 'راسل ASAF AI…';

  @override
  String get chatUnavailableHint =>
      'المحادثة غير متاحة — لا يوجد نموذج بحالة AVAILABLE';

  @override
  String get chatEmptyResponse => '(أعاد النموذج ردًّا فارغًا)';

  @override
  String get chatNoProject =>
      'لا يوجد مشروع متاح — لم يُرجِع الخادم الخلفي أي مشروع.';

  @override
  String get chatGenerationFailed => 'فشل التوليد.';

  @override
  String get imageTitle => 'توليد الصور';

  @override
  String get imageNotConfiguredBanner =>
      'لا يوجد مزوّد صور مُهيّأ على الخادم الخلفي. تعمل أدوات الوصف الموجز فقط؛ أما التوليد الفعلي للصور فيُبلّغ عنه بأنه UNAVAILABLE (ولا تُختلق أي صورة أبدًا).';

  @override
  String get imageDescription => 'الوصف';

  @override
  String get imageDescriptionHint =>
      'بورتريه سينمائي لفنان روبوت في استوديو نيون…';

  @override
  String get imageStyle => 'الأسلوب (اختياري)';

  @override
  String get imageStyleHint => 'واقعي، 35mm، إضاءة ناعمة';

  @override
  String get imageAction => 'الإجراء';

  @override
  String get imageAspect => 'الأبعاد';

  @override
  String get imageVariants => 'الأشكال';

  @override
  String get imageModel => 'النموذج';

  @override
  String get imageProviderDefault => 'افتراضي المزوّد';

  @override
  String get imageRun => 'تنفيذ الطلب';

  @override
  String get imageWorking => 'جارٍ العمل…';

  @override
  String get imageResult => 'النتيجة';

  @override
  String get imageTaskId => 'معرّف المهمة';

  @override
  String get imageArtifacts => 'المخرجات';

  @override
  String get imageCompatibleModels => 'نماذج الصور المتوافقة';

  @override
  String get imageNoModel =>
      'لم يجتز أي نموذج صور بوابة وقت التشغيل. هيّئ LAIW_IMAGE_PROVIDER_URL أو ثبّت نموذج صور محليًا.';

  @override
  String imageFailed(String error) {
    return 'فشل طلب الصورة: $error';
  }

  @override
  String get videoTitle => 'وقت تشغيل التوليد';

  @override
  String videoRuntimeWired(String list) {
    return 'أوقات تشغيل موصولة: $list. يُنفّذ الطلب فقط عند توفر أوزانه محليًا.';
  }

  @override
  String get videoRuntimeNotWired =>
      'لا يوجد وقت تشغيل لتوليد الفيديو موصول في هذا الإصدار. ستُبلّغ الطلبات عن NOT_CONFIGURED — ولا يُختلق أي شيء.';

  @override
  String get videoRuntimeStatus => 'حالة وقت التشغيل';

  @override
  String get videoWeightsMissing => 'أوزان مفقودة';

  @override
  String get videoRegisteredModels => 'النماذج المسجّلة';

  @override
  String get videoI2vTitle => 'من صورة إلى فيديو';

  @override
  String get videoNoModels =>
      'لا يوجد نموذج فيديو مسجّل من قِبل الخادم الخلفي. يُبلّغ توليد الفيديو عن NOT_CONFIGURED — بصدق، دون اختلاق أي شيء.';

  @override
  String get videoSourceImage => 'الصورة المصدر (مسار محلي على الخادم)';

  @override
  String get videoSourceHint => '/path/on/server/input.png';

  @override
  String get videoSourceHelper =>
      'تُرفض الروابط البعيدة بحكم التصميم — بلا تنزيل ضمني.';

  @override
  String get videoMotionPrompt => 'وصف الحركة';

  @override
  String get videoMotionHint => 'تحرّك بطيء للكاميرا للأمام، أوراق تتطاير…';

  @override
  String get videoDuration => 'المدة';

  @override
  String get videoWidth => 'العرض';

  @override
  String get videoHeight => 'الارتفاع';

  @override
  String get videoFps => 'معدل الإطارات';

  @override
  String get videoGenerate => 'توليد الفيديو';

  @override
  String get videoGenerating => 'جارٍ التوليد…';

  @override
  String get videoResult => 'النتيجة';

  @override
  String get videoArtifact => 'المخرج';

  @override
  String videoFailed(String error) {
    return 'فشل طلب الفيديو: $error';
  }

  @override
  String get workspaceTitle => 'مساحة عمل المشروع';

  @override
  String get workspaceCannotLoad => 'تعذّر تحميل مساحة العمل';

  @override
  String get workspaceNoWorkspace => 'لا توجد مساحة عمل بعد';

  @override
  String get workspaceNoWorkspaceMessage =>
      'أنشئ مشروعًا لتخزين المحادثات والمستندات وعمليات التوليد.';

  @override
  String get workspaceCreateLoad => 'إنشاء / تحميل مشروع';

  @override
  String get workspaceProjectId => 'معرّف المشروع';

  @override
  String get workspaceUpdated => 'آخر تحديث';

  @override
  String get workspaceConversations => 'المحادثات';

  @override
  String get workspaceDocuments => 'المستندات';

  @override
  String get workspaceSlideDecks => 'العروض التقديمية';

  @override
  String get workspaceFiles => 'الملفات';

  @override
  String get workspaceGenerations => 'عمليات التوليد';

  @override
  String get workspaceNoDocuments => 'لا توجد مستندات بعد.';

  @override
  String get workspaceNoSlides => 'لا توجد عروض تقديمية بعد.';

  @override
  String get workspaceNoConversations => 'لا توجد محادثات بعد.';

  @override
  String get workspaceNoFiles => 'لم يتم رفع أي ملفات بعد.';

  @override
  String get workspaceNoGenerations => 'لا توجد عمليات توليد بعد.';

  @override
  String get workspaceUploadedFiles => 'الملفات المرفوعة';

  @override
  String get workspaceProject => 'مشروع';

  @override
  String workspaceFailed(String error) {
    return 'تعذّر تحميل مساحة العمل: $error';
  }

  @override
  String get modelsTitle => 'النماذج';

  @override
  String modelsUsableCatalog(int usable, int total) {
    return '$usable قابلة للاستخدام / $total في الفهرس';
  }

  @override
  String get modelsSearchHint => 'ابحث عن النماذج أو المزوّدين…';

  @override
  String get modelsNoMatch => 'لا توجد نماذج مطابقة';

  @override
  String get modelsNoMatchMessage =>
      'عدّل عامل التصفية أو هيّئ مزوّدًا على الخادم الخلفي.';

  @override
  String get modelsFilterAll => 'الكل';

  @override
  String get modelsFilterChat => 'محادثة';

  @override
  String get modelsFilterReasoning => 'استدلال';

  @override
  String get modelsFilterCoding => 'برمجة';

  @override
  String get modelsFilterVision => 'رؤية';

  @override
  String get modelsFilterImage => 'صور';

  @override
  String get modelsFilterVideo => 'فيديو';

  @override
  String get modelsFilterEmbedding => 'تضمين';

  @override
  String get modelsModelId => 'معرّف النموذج';

  @override
  String get modelsKind => 'النوع';

  @override
  String get modelsServingRuntime => 'وقت تشغيل الخدمة';

  @override
  String get modelsLocal => 'محلي';

  @override
  String get modelsRuntimeAvailable => 'وقت التشغيل متاح';

  @override
  String get modelsContextWindow => 'نافذة السياق';

  @override
  String get modelsCostTier => 'فئة التكلفة';

  @override
  String get modelsLastError => 'آخر خطأ';

  @override
  String get modelsRunHealthCheck => 'تشغيل فحص الحالة الحقيقي';

  @override
  String get modelsProbing => 'جارٍ الفحص…';

  @override
  String get modelsHealthReport => 'تقرير الحالة';

  @override
  String get modelsOk => 'سليم';

  @override
  String get modelsLatency => 'زمن الاستجابة';

  @override
  String get providersTitle => 'المزوّدون';

  @override
  String get providersEmpty => 'لم يُبلّغ الخادم الخلفي عن أي مزوّد.';

  @override
  String get providersRuntimeMatrix => 'مصفوفة قدرات وقت التشغيل';

  @override
  String get providersNoRuntime => 'لا توجد مصفوفة وقت تشغيل متاحة.';

  @override
  String get providersConfigured => 'مُهيّأ';

  @override
  String get providersType => 'النوع';

  @override
  String get providersLocal => 'محلي (بلا إنترنت)';

  @override
  String get providersRemote => 'بعيد';

  @override
  String get providersModelsDiscovered => 'النماذج المكتشفة';

  @override
  String get providersModelsAvailable => 'النماذج المتاحة';

  @override
  String get providersEndpoint => 'نقطة النهاية';

  @override
  String get providersTestConnection => 'اختبار الاتصال';

  @override
  String providersConnectionTest(String name) {
    return 'اختبار الاتصال · $name';
  }

  @override
  String get providersNoResults => 'لم تُرجَع أي نتائج.';

  @override
  String get providersAdapter => 'المهايئ';

  @override
  String get providersCapabilities => 'القدرات';

  @override
  String get historyTitle => 'السجل';

  @override
  String get historyEmpty => 'لا يوجد سجل توليد بعد';

  @override
  String get historyEmptyMessage => 'ستظهر مهام المحادثة والتوليد هنا.';

  @override
  String get historyGenerationId => 'معرّف التوليد';

  @override
  String get historyKind => 'النوع';

  @override
  String get historyStarted => 'وقت البدء';

  @override
  String get historyCompleted => 'وقت الإكمال';

  @override
  String get historyError => 'خطأ';

  @override
  String get historyOutput => 'المخرج';

  @override
  String get historyStoredResult => 'النتيجة المخزّنة';

  @override
  String get historyModelMissing => 'النموذج: —';

  @override
  String get historyCannotLoadTask => 'تعذّر تحميل المهمة';

  @override
  String get languageName => 'العربية';
}
