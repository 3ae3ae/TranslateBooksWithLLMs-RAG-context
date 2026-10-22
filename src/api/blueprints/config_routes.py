"""
Configuration and health check routes
"""
import logging
import time
from flask import Blueprint, request, jsonify, render_template, make_response

SUPPORTED_UI_LOCALES = ['en', 'ko']
UI_LOCALE_COOKIE = 'ui_locale'
UI_LOCALE_COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year


def resolve_ui_locale(req):
    """Pick the UI locale to render the page with.

    Order: explicit cookie (user's last choice) → Accept-Language best match
    → 'en'.
    """
    cookie_locale = req.cookies.get(UI_LOCALE_COOKIE)
    if cookie_locale in SUPPORTED_UI_LOCALES:
        return cookie_locale
    best = req.accept_languages.best_match(SUPPORTED_UI_LOCALES)
    return best or 'en'


import src.config as _config

# Setup logger for this module
logger = logging.getLogger('config_routes')
if _config.DEBUG_MODE:
    logger.setLevel(logging.DEBUG)


def create_config_blueprint(server_session_id=None):
    """Create and configure the config blueprint

    Args:
        server_session_id: Server session ID from state manager (optional, generates new if not provided)
    """
    bp = Blueprint('config', __name__)

    # Store server startup time/session ID to detect restarts
    # Use provided session_id from state_manager if available, otherwise generate new
    # Ensure it's an integer for consistency with health check response
    startup_time = int(server_session_id) if server_session_id else int(time.time())

    @bp.route('/')
    def serve_interface():
        """Serve the redesigned app shell (all UI is rendered client-side)."""
        from src.api.auth import API_TOKEN
        return render_template(
            'app.html',
            initial_locale=resolve_ui_locale(request),
            api_token=API_TOKEN,
        )

    @bp.after_app_request
    def revalidate_app_modules(response):
        # ES modules are imported without version suffixes; make browsers
        # revalidate them (cheap 304s) so an updated app is never half-stale.
        if request.path.startswith(('/static/app/', '/static/vendor/')):
            response.headers['Cache-Control'] = 'no-cache'
        return response

    @bp.route('/api/ui-locale', methods=['POST'])
    def set_ui_locale():
        """Persist the user's UI locale choice in a long-lived cookie."""
        data = request.get_json(silent=True) or {}
        locale = data.get('locale')
        if locale not in SUPPORTED_UI_LOCALES:
            return jsonify({"success": False, "error": f"Unsupported locale: {locale}"}), 400

        response = make_response(jsonify({"success": True, "locale": locale}))
        response.set_cookie(
            UI_LOCALE_COOKIE,
            locale,
            max_age=UI_LOCALE_COOKIE_MAX_AGE,
            samesite='Lax',
            httponly=True,
        )
        return response

    @bp.route('/api/ui-locale', methods=['GET'])
    def get_ui_locale():
        """Return the locale the server would pick for this request."""
        return jsonify({
            "locale": resolve_ui_locale(request),
            "supported": SUPPORTED_UI_LOCALES,
        })

    @bp.route('/api/health', methods=['GET'])
    def health_check():
        """API health check endpoint"""
        return jsonify({
            "status": "ok",
            "message": "Translation API is running",
            "translate_module": "loaded",
            "ollama_default_endpoint": _config.API_ENDPOINT,
            "supported_formats": ["txt", "epub", "srt"],
            "startup_time": startup_time,  # Used to detect server restarts
            "session_id": startup_time
        })

    return bp
