/**
 * Model Detector - Detect model size, thinking behavior, and show recommendations
 *
 * Analyzes model names to determine parameter size.
 * Also checks for uncontrollable thinking models and displays warnings.
 */

import { DomHelpers } from '../ui/dom-helpers.js';

/**
 * Check if model is an uncontrollable thinking model and show warning
 * @param {string} modelName - Model name
 */
async function checkThinkingModelWarning(modelName) {
    const warningDiv = document.getElementById('thinkingModelWarning');
    const warningText = document.getElementById('thinkingModelWarningText');

    if (!warningDiv || !warningText) {
        return;
    }

    if (!modelName) {
        warningDiv.style.display = 'none';
        return;
    }

    try {
        // Get API endpoint for cache differentiation
        const endpoint = DomHelpers.getValue('apiEndpoint') || '';

        const response = await fetch(`/api/model/warning?model=${encodeURIComponent(modelName)}&endpoint=${encodeURIComponent(endpoint)}`);
        const data = await response.json();

        if (data.warning && data.is_uncontrollable) {
            warningText.textContent = data.warning;
            warningDiv.style.display = 'block';
        } else {
            warningDiv.style.display = 'none';
        }
    } catch (error) {
        console.warn('Failed to check thinking model warning:', error);
        warningDiv.style.display = 'none';
    }
}

export const ModelDetector = {
    /**
     * Check for thinking model warning
     * Called when model selection changes
     */
    checkAndShowRecommendation() {
        const modelName = DomHelpers.getValue('model');
        // Check for thinking model warning (async, non-blocking)
        checkThinkingModelWarning(modelName);
    },

    /**
     * Initialize model detector event listeners
     */
    initialize() {
        const modelSelect = DomHelpers.getElement('model');

        if (modelSelect) {
            modelSelect.addEventListener('change', () => {
                this.checkAndShowRecommendation();
            });
        }
    }
};
