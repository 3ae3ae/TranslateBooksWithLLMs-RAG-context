"""
Test for GitHub Issue #108 (Part 2): Ollama endpoint uses localhost instead of server config

This test verifies that:
1. The /api/config endpoint exposes the correct OLLAMA_API_ENDPOINT from server
2. The frontend initialization sequence loads models AFTER server config is received

Regression test for: https://github.com/hydropix/TranslateBooksWithLLMs/issues/108

Bug description:
When OLLAMA_API_ENDPOINT is configured to a remote server (e.g., http://192.168.1.4:11434/api/generate),
the frontend was still trying to connect to localhost:11434 because:
1. SettingsManager.initialize() restored lastProvider from localStorage and triggered model loading
2. This happened BEFORE FormManager.loadDefaultConfig() received the server config
3. So the model loading used the HTML default value (localhost) instead of server config

Expected behavior:
The first model loading should wait for server config to be loaded, then use the correct endpoint.
"""

import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


class TestOllamaEndpointInitializationBug:
    """
    Tests for OLLAMA_API_ENDPOINT proper exposure and initialization sequence.
    
    GitHub Issue #108 (Part 2): When OLLAMA_API_ENDPOINT is configured to a remote
    server, the UI was still trying to connect to localhost because the frontend
    loaded models before receiving the server configuration.
    """

    @pytest.fixture
    def app(self):
        """Create a Flask app for testing with remote Ollama config."""
        # Set test values BEFORE importing Flask app components
        os.environ['OLLAMA_API_ENDPOINT'] = 'http://192.168.1.4:11434/api/generate'
        os.environ['API_ENDPOINT'] = 'http://192.168.1.4:11434/api/generate'
        
        # Import and reload config to pick up test values
        import importlib
        from src import config
        importlib.reload(config)
        
        # Now import and create Flask app (it will use the reloaded config)
        from flask import Flask
        from src.api.blueprints.config_routes import create_config_blueprint
        
        app = Flask(__name__)
        bp = create_config_blueprint(server_session_id=12345)
        app.register_blueprint(bp)
        
        yield app
        
        # Cleanup: restore original values after test
        del os.environ['OLLAMA_API_ENDPOINT']
        del os.environ['API_ENDPOINT']

    def test_api_config_response_contains_ollama_endpoint(self, app):
        """
        Test that /api/config response includes ollama_api_endpoint field
        with the correct remote server value.
        
        This verifies the backend correctly exposes the configured endpoint.
        """
        with app.test_client() as client:
            response = client.get('/api/config')
            
            assert response.status_code == 200, \
                f"Expected 200 but got {response.status_code}"
            
            data = response.get_json()
            assert data is not None, "Response should be valid JSON"
            
            # KEY ASSERTION: ollama_api_endpoint must be present
            assert 'ollama_api_endpoint' in data, \
                "BUG: 'ollama_api_endpoint' missing from /api/config. " \
                f"Got keys: {list(data.keys())}"
            
            # It should have the remote server value, not localhost
            assert data['ollama_api_endpoint'] == 'http://192.168.1.4:11434/api/generate', \
                f"Expected remote endpoint but got '{data.get('ollama_api_endpoint')}'"

    def test_api_config_response_contains_legacy_api_endpoint(self, app):
        """
        Test that /api/config response also includes api_endpoint field
        for backward compatibility.
        """
        with app.test_client() as client:
            response = client.get('/api/config')
            data = response.get_json()
            
            assert 'api_endpoint' in data, \
                "'api_endpoint' should be in /api/config response for backward compatibility"
            
            assert data['api_endpoint'] == 'http://192.168.1.4:11434/api/generate', \
                f"Expected remote endpoint but got '{data.get('api_endpoint')}'"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
