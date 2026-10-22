/**
 * Main Application Entry Point
 *
 * Coordinates all modules and initializes the translation application.
 * This file serves as the central coordinator for the modular architecture.
 */

// ========================================
// Core Infrastructure
// ========================================
import { StateManager } from './core/state-manager.js';
import { ApiClient } from './core/api-client.js';
import { WebSocketManager } from './core/websocket-manager.js';
import { SettingsManager } from './core/settings-manager.js';

// ========================================
// UI Modules
// ========================================
import { DomHelpers } from './ui/dom-helpers.js';
import { MessageLogger } from './ui/message-logger.js';
import { FormManager } from './ui/form-manager.js';
import { SettingsSummary } from './ui/settings-summary.js';
import { NotificationsManager } from './ui/notifications-manager.js';
import { GlossaryManager } from './glossary/glossary-manager.js';

// ========================================
// Provider Modules
// ========================================
import { ProviderManager } from './providers/provider-manager.js';
import { ModelDetector } from './providers/model-detector.js';
import { CostEstimator } from './providers/cost-estimator.js';

// ========================================
// File Management Modules
// ========================================
import { FileUpload } from './files/file-upload.js';
import { FileManager } from './files/file-manager.js';
import { FileActions } from './files/file-actions.js';

// ========================================
// Translation Modules
// ========================================
import { TranslationTracker } from './translation/translation-tracker.js';
import { BatchController } from './translation/batch-controller.js';
import { ProgressManager } from './translation/progress-manager.js';
import { ResumeManager } from './translation/resume-manager.js';
import { QuickTestManager } from './translation/quick-test.js';

// ========================================
// Utilities
// ========================================
import { LifecycleManager } from './utils/lifecycle-manager.js';
import { StatusManager } from './utils/status-manager.js';
import { initializeThemeManager } from './utils/theme-manager.js';

// ========================================
// Sample & Compare
// ========================================
import { SampleManager } from './sample/sample-manager.js';

// ========================================
// i18n
// ========================================
import { initI18n, t } from './i18n/i18n.js';
import { UiLocaleControl } from './i18n/settings-control.js';

// ========================================
// Global State Initialization
// ========================================

/**
 * Initialize application state
 * Note: Some state (like files.toProcess) will be restored from localStorage
 * by their respective modules, so we only set defaults if not already present
 */
function initializeState() {
    // Files state - only initialize if not already set (will be restored by FileUpload)
    if (!StateManager.getState('files.toProcess')) {
        StateManager.setState('files.toProcess', []);
    }
    if (!StateManager.getState('files.selected')) {
        StateManager.setState('files.selected', []);
    }
    if (!StateManager.getState('files.managed')) {
        StateManager.setState('files.managed', []);
    }

    // Translation state - DO NOT reset here, will be restored by TranslationTracker from localStorage
    // TranslationTracker.initialize() will handle loading saved state or initializing defaults

    // UI state
    StateManager.setState('ui.currentProvider', 'ollama');
    StateManager.setState('ui.currentModel', '');
    StateManager.setState('ui.messages', []);

    // Models state
    StateManager.setState('models.currentLoadRequest', null);
    StateManager.setState('models.availableModels', []);
}

// ========================================
// Event Wiring
// ========================================

/**
 * Wire up cross-module events
 */
function wireModuleEvents() {
    // File list changed -> update display
    window.addEventListener('fileListChanged', () => {
        FileUpload.updateFileDisplay();
    });

    // File status changed -> update display
    window.addEventListener('fileStatusChanged', () => {
        FileUpload.updateFileDisplay();
    });

    // Translation started -> update active translations state
    window.addEventListener('translationStarted', () => {
        TranslationTracker.updateActiveTranslationsState();
    });

    // Translation resumed -> update active translations state
    window.addEventListener('translationResumed', () => {
        TranslationTracker.updateActiveTranslationsState();
    });

    // Translation completed -> process next in queue
    window.addEventListener('translationCompleted', () => {
        BatchController.processNextFileInQueue();
    });

    // Translation error -> process next in queue
    window.addEventListener('translationError', () => {
        BatchController.processNextFileInQueue();
    });

    // Process next file in queue (from TranslationTracker)
    window.addEventListener('processNextFile', () => {
        BatchController.processNextFileInQueue();
    });

    // WebSocket events -> module handlers
    WebSocketManager.on('connect', () => {
        // Only refresh models if we don't have any loaded yet
        const hasModels = StateManager.getState('models.availableModels')?.length > 0;
        if (!hasModels) {
            ProviderManager.refreshModels();
        }

        ResumeManager.loadResumableJobs();
        FileManager.refreshFileList();
        TranslationTracker.updateActiveTranslationsState();
    });

    WebSocketManager.on('translation_update', (data) => {
        TranslationTracker.handleTranslationUpdate(data);
    });

    WebSocketManager.on('file_list_changed', (data) => {
        FileManager.refreshFileList();
    });

    WebSocketManager.on('checkpoint_created', (data) => {
        ResumeManager.loadResumableJobs();
    });

    // State changes -> update UI
    StateManager.subscribe('translation.isBatchActive', (isActive) => {
        const translateBtn = DomHelpers.getElement('translateBtn');
        if (translateBtn) {
            translateBtn.disabled = isActive;
        }
    });

    StateManager.subscribe('translation.hasActive', (hasActive) => {
        TranslationTracker.updateResumeButtonsState();
    });

    StateManager.subscribe('files.toProcess', (files) => {
        const translateBtn = DomHelpers.getElement('translateBtn');
        if (translateBtn && !StateManager.getState('translation.isBatchActive')) {
            // Only enable if files exist AND LLM is connected
            translateBtn.disabled = files.length === 0 || !StatusManager.isConnected();
        }
    });
}

// ========================================
// Module Initialization
// ========================================

/**
 * Initialize all modules in proper order
 *
 * CRITICAL ordering rule: every event wiring (wireModuleEvents, LifecycleManager,
 * WebSocketManager.on handlers) must run synchronously BEFORE any awaitable
 * network call AND before WebSocketManager.connect(). Otherwise:
 *   - A slow /api/health or /api/translations response can hang the await on
 *     TranslationTracker.initialize() and leave the UI un-wired (translate
 *     button disabled, no WS handlers, no lifecycle handlers).
 *   - Or the socket connects during the await and emits "connect" before its
 *     handler is registered, so the post-connect refresh (provider models,
 *     file list, resumable jobs) is silently dropped — that's why the
 *     "LLM: Checking..." indicator gets stuck (issue #155).
 */
async function initializeModules() {
    // 0. Boot i18next first so every module that renders text can call t().
    //    initI18n() resolves to applying data-i18n nodes already in the DOM
    //    and binding the languageChanged listener. We await it because the
    //    rest of the init expects translations to be available.
    try {
        await initI18n();
    } catch (e) {
        console.warn('initI18n failed:', e);
    }
    UiLocaleControl.initialize();

    // 1. Synchronous state + UI/module init (no awaits).
    initializeState();
    initializeThemeManager();
    SettingsManager.initialize();
    FormManager.initialize();
    SettingsSummary.initialize();
    NotificationsManager.initialize();
    GlossaryManager.initialize();
    StatusManager.initialize();
    ProviderManager.initialize();
    ModelDetector.initialize();
    // FileUpload must initialize before CostEstimator so its `change` listeners
    // on source/target language fire first and recreate the file <li>s (with
    // empty cost-badge slots) before CostEstimator's listener queries the DOM.
    FileUpload.initialize();
    CostEstimator.initialize();
    FileManager.initialize();
    ProgressManager.reset();
    ResumeManager.initialize();
    LifecycleManager.initialize();

    // 2. Wire cross-module + WebSocket handlers BEFORE the socket connects.
    wireModuleEvents();

    // 3. Now safe to open the WebSocket — the "connect" handler is registered.
    WebSocketManager.connect();

    // 4. Background-only inits. Do not await: a slow server must not freeze
    //    the UI. TranslationTracker.initialize() is async and performs
    //    network calls; failures are logged and the UI stays usable.
    SampleManager.init();
    QuickTestManager.init();
    TranslationTracker.initialize().catch((error) => {
        console.error('TranslationTracker initialization failed:', error);
    });
}

// ========================================
// Global Function Exposure for HTML onclick
// ========================================

/**
 * Expose functions to window for onclick handlers in HTML
 * These functions will be called directly from HTML attributes
 */

// File Upload
window.handleFileSelect = FileUpload.handleFileSelect.bind(FileUpload);
window.handleFileSelectRefine = FileUpload.handleFileSelectRefine.bind(FileUpload);
// Form Manager
window.toggleSettingsOptions = FormManager.toggleSettingsOptions.bind(FormManager);
window.togglePromptOptions = FormManager.togglePromptOptions.bind(FormManager);
window.toggleActivityLog = FormManager.toggleActivityLog.bind(FormManager);

// Notifications Manager
window.toggleNotificationOptions = NotificationsManager.toggleOptions.bind(NotificationsManager);
window.testNotification = NotificationsManager.testNotification.bind(NotificationsManager);
window.checkCustomSourceLanguage = (element) => FormManager.checkCustomSourceLanguage(element);
window.checkCustomTargetLanguage = (element) => FormManager.checkCustomTargetLanguage(element);

// Batch Controller
window.startBatchTranslation = BatchController.startBatchTranslation.bind(BatchController);
window.interruptCurrentTranslation = async () => {
    const currentJob = StateManager.getState('translation.currentJob');
    if (!currentJob) {
        MessageLogger.showMessage(t('translation:no_active_translation'), 'info');
        return;
    }

    const interruptBtn = DomHelpers.getElement('interruptBtn');
    if (interruptBtn) {
        interruptBtn.disabled = true;
        DomHelpers.setText(interruptBtn, t('translation:interrupting'));
    }

    try {
        await ApiClient.interruptTranslation(currentJob.translationId);
        MessageLogger.showMessage(t('translation:interrupt_request_sent'), 'info');
        MessageLogger.addLog(t('translation:interrupt_log'));
    } catch (error) {
        MessageLogger.showMessage(t('translation:interrupt_error', { error: error.message }), 'error');
        if (interruptBtn) {
            interruptBtn.disabled = false;
            DomHelpers.setText(interruptBtn, `⏹️ ${t('translation:interrupt_batch')}`);
        }
    }
};

// Resume Manager
window.resumeJob = ResumeManager.resumeJob.bind(ResumeManager);
window.deleteCheckpoint = ResumeManager.deleteCheckpoint.bind(ResumeManager);
window.loadResumableJobs = ResumeManager.loadResumableJobs.bind(ResumeManager);

// Provider Manager
window.refreshModels = ProviderManager.refreshModels.bind(ProviderManager);

// Settings Manager
window.saveSettings = async () => {
    const result = await SettingsManager.saveAllSettings(true);
    if (result.success && result.savedToEnv && result.savedToEnv.length > 0) {
        const keys = result.savedToEnv.join(', ');
        MessageLogger.showMessage(t('translation:settings_saved_env', { keys }), 'success');
        MessageLogger.addLog(t('translation:settings_saved_env_log', { keys }));
    } else if (result.success) {
        MessageLogger.showMessage(t('translation:preferences_saved'), 'success');
    } else {
        MessageLogger.showMessage(t('translation:settings_save_failed', { error: result.error }), 'error');
    }
    return result;
};

// Message Logger
window.clearActivityLog = MessageLogger.clearLog.bind(MessageLogger);

// File Manager
window.refreshFileList = FileManager.refreshFileList.bind(FileManager);
window.openOutputFolder = () => FileActions.openOutputFolder();
window.openContextFolder = () => ApiClient.openContextFolder();
// ========================================
// Application Bootstrap
// ========================================

/**
 * Start application when DOM is ready
 */
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', async () => {
        await initializeModules();
    });
} else {
    // DOM already loaded - initialize immediately
    (async () => {
        await initializeModules();
    })();
}
