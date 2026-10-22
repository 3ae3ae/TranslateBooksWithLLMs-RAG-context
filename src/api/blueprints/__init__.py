"""
API Routes
"""
from .config_routes import create_config_blueprint
from .translation_routes import create_translation_blueprint
from .file_routes import create_file_blueprint
from .security_routes import create_security_blueprint
from .glossary_routes import create_glossary_blueprint
from .sample_routes import create_sample_blueprint
from .preferences_routes import create_preferences_blueprint
from .notes_routes import create_notes_blueprint
from .styles_routes import create_styles_blueprint
from .estimate_routes import create_estimate_blueprint
from .connections_routes import create_connections_blueprint

__all__ = [
    'create_config_blueprint',
    'create_translation_blueprint',
    'create_file_blueprint',
    'create_security_blueprint',
    'create_glossary_blueprint',
    'create_sample_blueprint',
    'create_preferences_blueprint',
    'create_notes_blueprint',
    'create_styles_blueprint',
    'create_estimate_blueprint',
    'create_connections_blueprint',
    'create_jobs_blueprint',
]

from .jobs_routes import create_jobs_blueprint
