"""
Test for hybrid endpoint logic (Option 3)

Tests that verify:
1. First load: uses .env server default
2. User modification: endpoint marked as customized, badge shown
3. Reset button: restores server default, clears customized flag

This implements GitHub issue #108 enhancement: hybrid smart endpoint management.
"""

import pytest
import re
from pathlib import Path


class TestEndpointHybridLogic:
    """
    Tests for the hybrid endpoint configuration logic.
    
    The logic is:
    - First load: use .env server default
    - User modifies endpoint: mark as customized, show badge
    - User clicks reset: restore to .env value, hide badge
    """

    @pytest.fixture
    def js_files(self):
        """Get paths to relevant JavaScript files."""
        base_path = Path(__file__).parent.parent.parent / "src" / "web" / "static" / "js"
        return {
            "settings_manager": base_path / "core" / "settings-manager.js",
            "form_manager": base_path / "ui" / "form-manager.js",
        }

    @pytest.fixture
    def html_file(self):
        """Get path to HTML template."""
        return Path(__file__).parent.parent.parent / "src" / "web" / "templates" / "translation_interface.html"

    def test_settings_manager_tracks_customized_state(self, js_files):
        """
        Verify SettingsManager tracks whether endpoints are customized.
        
        Should have:
        - apiEndpointCustomized in LOCAL_SETTINGS
        - openaiEndpointCustomized in LOCAL_SETTINGS
        - markEndpointCustomized() method
        - resetEndpointToServerDefault() method
        """
        settings_manager = js_files["settings_manager"]
        assert settings_manager.exists(), f"settings-manager.js not found"
        
        content = settings_manager.read_text(encoding='utf-8')
        
        # Check that customized flags are in LOCAL_SETTINGS
        assert "apiEndpointCustomized" in content, \
            "SettingsManager should track apiEndpointCustomized in localStorage"
        assert "openaiEndpointCustomized" in content, \
            "SettingsManager should track openaiEndpointCustomized in localStorage"
        
        # Check for the methods
        assert "markEndpointCustomized" in content, \
            "SettingsManager should have markEndpointCustomized() method"
        assert "resetEndpointToServerDefault" in content, \
            "SettingsManager should have resetEndpointToServerDefault() method"

    def test_settings_manager_updates_badges(self, js_files):
        """
        Verify SettingsManager can update endpoint badges visibility.
        """
        settings_manager = js_files["settings_manager"]
        content = settings_manager.read_text(encoding='utf-8')
        
        # Should have updateEndpointBadge method
        assert "updateEndpointBadge" in content, \
            "SettingsManager should have updateEndpointBadge() method"
        
        # Should reference badge IDs
        assert "apiEndpointBadge" in content or "EndpointBadge" in content, \
            "Should reference endpoint badge elements"

    def test_form_manager_detects_manual_changes(self, js_files):
        """
        Verify FormManager detects when user manually changes endpoints.
        """
        form_manager = js_files["form_manager"]
        assert form_manager.exists(), f"form-manager.js not found"
        
        content = form_manager.read_text(encoding='utf-8')
        
        # Check for event listeners on endpoint changes
        assert "markEndpointCustomized" in content, \
            "FormManager should call markEndpointCustomized when endpoint changes"
        
        # Check that it listens for apiEndpoint changes
        assert "apiEndpoint" in content and "addEventListener" in content, \
            "FormManager should listen for endpoint input changes"

    def test_form_manager_smart_merge_logic(self, js_files):
        """
        Verify FormManager uses smart merge for endpoints:
        - If customized: keep localStorage value and show badge
        - If not customized: use server default
        """
        form_manager = js_files["form_manager"]
        content = form_manager.read_text(encoding='utf-8')
        
        # Should check for customized flag
        assert "apiEndpointCustomized" in content, \
            "FormManager should check apiEndpointCustomized flag"
        
        # Should have logic to decide between localStorage and server
        assert "lastApiEndpoint" in content, \
            "FormManager should consider lastApiEndpoint from localStorage"
        
        # Should call updateEndpointBadge
        assert "updateEndpointBadge" in content, \
            "FormManager should update badge visibility based on customization"

    def test_html_has_badge_and_reset_button(self, html_file):
        """
        Verify HTML template has badge and reset button for endpoints.
        """
        assert html_file.exists(), f"translation_interface.html not found"
        
        content = html_file.read_text(encoding='utf-8')
        
        # Check for Ollama endpoint badge
        assert "apiEndpointBadge" in content, \
            "HTML should have apiEndpointBadge element"
        
        # Check for Ollama reset button
        assert "resetApiEndpointBtn" in content, \
            "HTML should have resetApiEndpointBtn element"
        
        # Check for OpenAI endpoint badge
        assert "openaiEndpointBadge" in content, \
            "HTML should have openaiEndpointBadge element"
        
        # Check for OpenAI reset button
        assert "resetOpenaiEndpointBtn" in content, \
            "HTML should have resetOpenaiEndpointBtn element"
        
        # Check for badge styling (hidden by default)
        badge_pattern = r'apiEndpointBadge.*style.*display:\s*none'
        assert re.search(badge_pattern, content, re.DOTALL | re.IGNORECASE), \
            "Badge should be hidden by default (display: none)"
        
        # Check for reset button styling (hidden by default)
        btn_pattern = r'resetApiEndpointBtn.*style.*display:\s*none'
        assert re.search(btn_pattern, content, re.DOTALL | re.IGNORECASE), \
            "Reset button should be hidden by default (display: none)"

    def test_html_badge_has_personnalise_text(self, html_file):
        """
        Verify badge shows 'personnalisé' text (French) or appropriate label.
        """
        content = html_file.read_text(encoding='utf-8')
        
        # Badge should have appropriate text
        # Could be "personnalisé" (French) or "customized" (English)
        has_personnalise = "personnalis" in content.lower() or "custom" in content.lower()
        
        assert has_personnalise, \
            "Badge should indicate customized state with appropriate text"

    def test_reset_button_has_icon(self, html_file):
        """
        Verify reset button has a restart/refresh icon.
        """
        content = html_file.read_text(encoding='utf-8')
        
        # Should have material icons or similar
        assert "restart_alt" in content or "refresh" in content.lower() or "undo" in content.lower(), \
            "Reset button should have an appropriate icon"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
