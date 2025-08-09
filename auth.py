import os
import secrets
import requests
from flask import session, request, redirect, url_for, jsonify, flash, render_template
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from authlib.integrations.flask_client import OAuth
    OAUTH_AVAILABLE = True
except ImportError:
    logger.warning("Authlib not available. OAuth features will be disabled.")
    OAUTH_AVAILABLE = False
    OAuth = None

try:
    from flask_session import Session as FlaskSession
    FLASK_SESSION_AVAILABLE = True
except ImportError:
    logger.warning("Flask-Session not available. Using basic sessions.")
    FLASK_SESSION_AVAILABLE = False
    FlaskSession = None

from db import Session as DBSession, User

class AuthManager:
    def __init__(self, app):
        self.app = app
        self.oauth_available = OAUTH_AVAILABLE
        if OAUTH_AVAILABLE:
            self.oauth = OAuth(app)
            self.setup_oauth_providers()
        else:
            self.oauth = None
            logger.warning("OAuth not available. Authentication features disabled.")
    
    def setup_oauth_providers(self):
        """Setup OAuth providers (Google only)"""
        if not self.oauth_available:
            return
            
        # Google OAuth setup
        self.google = self.oauth.register(
            name='google',
            client_id=os.getenv('GOOGLE_CLIENT_ID'),
            client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
            authorization_endpoint='https://accounts.google.com/o/oauth2/auth',
            token_endpoint='https://oauth2.googleapis.com/token',
            userinfo_endpoint='https://www.googleapis.com/oauth2/v3/userinfo',
            client_kwargs={'scope': 'openid email profile'},
        )
    
    def login_required(self, f):
        """Decorator to require authentication"""
        def decorated_function(*args, **kwargs):
            if not self.is_authenticated():
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    
    def is_authenticated(self):
        """Check if user is authenticated"""
        return 'user_id' in session and 'user_email' in session
    
    def is_authenticated_or_guest(self):
        """Check if user is authenticated or in guest mode"""
        return self.is_authenticated() or session.get('guest_mode', False)
    
    def get_current_user(self):
        """Get current user from session"""
        if not self.is_authenticated():
            return None
        
        try:
            db_session = DBSession()
            user = db_session.query(User).filter_by(id=session['user_id']).first()
            db_session.close()
            return user
        except Exception as e:
            logger.error(f"Error getting current user: {str(e)}")
            return None
    
    def get_current_user_with_avatar(self):
        """Get current user from session with avatar fallback"""
        if not self.is_authenticated():
            return None
        
        try:
            db_session = DBSession()
            user = db_session.query(User).filter_by(id=session['user_id']).first()
            
            # Ensure session has latest avatar info
            if user and user.avatar_url and session.get('user_avatar') != user.avatar_url:
                session['user_avatar'] = user.avatar_url
                logger.debug(f"Updated session avatar from DB: {user.avatar_url}")
            
            db_session.close()
            return user
        except Exception as e:
            logger.error(f"Error getting current user with avatar: {str(e)}")
            return None
    
    def login_user(self, user_data, provider):
        """Login or create user from OAuth data"""
        try:
            # Clear any existing session data first
            session.clear()
            
            db_session = DBSession()
            
            # Check if user exists by email first (regardless of provider_id)
            user = db_session.query(User).filter_by(
                email=user_data['email']
            ).first()
            
            if not user:
                # Create new user
                user = User(
                    email=user_data['email'],
                    name=user_data.get('name', user_data['email'].split('@')[0]),
                    provider=provider,
                    provider_id=str(user_data.get('sub', user_data.get('id', ''))),
                    avatar_url=user_data.get('picture', user_data.get('avatar_url')),
                    created_at=datetime.utcnow(),
                    last_login=datetime.utcnow()
                )
                db_session.add(user)
                db_session.commit()
                logger.info(f"Created new user: {user.email} with avatar: {user.avatar_url}")
            else:
                # Update existing user with latest info
                user.last_login = datetime.utcnow()
                user.name = user_data.get('name', user.name)  # Update name if provided
                user.provider_id = str(user_data.get('sub', user_data.get('id', user.provider_id)))  # Update provider_id
                
                # Always update avatar if available
                new_avatar = user_data.get('picture', user_data.get('avatar_url'))
                if new_avatar:
                    user.avatar_url = new_avatar
                    logger.info(f"Updated user avatar: {user.avatar_url}")
                
                db_session.commit()
                logger.info(f"User logged in: {user.email} with updated avatar: {user.avatar_url}")
            
            # Set session with fresh data
            session.permanent = True
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_name'] = user.name
            session['user_avatar'] = user.avatar_url
            session['provider'] = provider
            
            # Clear any guest mode flags
            session.pop('guest_mode', None)
            
            # Debug session information
            logger.debug(f"Setting session - User ID: {user.id}, Avatar URL: {user.avatar_url}")
            logger.debug(f"Session after login: {dict(session)}")
            
            db_session.close()
            return user
            
        except Exception as e:
            logger.error(f"Error logging in user: {str(e)}")
            if 'db_session' in locals():
                db_session.rollback()
                db_session.close()
            return None
    
    def logout_user(self):
        """Logout current user"""
        # Clear all session data
        session.clear()
        # Force session to be regenerated
        session.permanent = False
        logger.info("User logged out and session cleared")
    
    def setup_routes(self):
        """Setup authentication routes"""
        
        @self.app.route('/login')
        def login():
            """Show login page"""
            if self.is_authenticated():
                return redirect(url_for('home'))
            return render_template('login.html')
        
        @self.app.route('/logout')
        def logout():
            """Logout user"""
            self.logout_user()
            flash('You have been logged out successfully.', 'success')
            return redirect(url_for('home'))
        
        @self.app.route('/refresh-session')
        def refresh_session():
            """Force refresh session with latest database data"""
            if not self.is_authenticated():
                return jsonify({'error': 'Not authenticated'}), 401
            
            try:
                user = self.get_current_user()
                if user:
                    # Update session with latest database values
                    session['user_name'] = user.name
                    session['user_email'] = user.email
                    session['user_avatar'] = user.avatar_url
                    session.permanent = True
                    
                    logger.info(f"Session refreshed for user: {user.email}")
                    return jsonify({
                        'message': 'Session refreshed successfully',
                        'user_name': user.name,
                        'user_email': user.email,
                        'user_avatar': user.avatar_url
                    })
                else:
                    # User not found in database, clear session
                    session.clear()
                    return jsonify({'error': 'User not found, session cleared'}), 404
            except Exception as e:
                logger.error(f"Error refreshing session: {str(e)}")
                return jsonify({'error': 'Failed to refresh session'}), 500
        
        @self.app.route('/auth/<provider>')
        def oauth_login(provider):
            """Initiate OAuth login"""
            if not self.oauth_available:
                flash('Authentication not available. Please install required dependencies.', 'error')
                return redirect(url_for('home'))
                
            if provider != 'google':
                flash('Invalid authentication provider.', 'error')
                return redirect(url_for('home'))
            
            oauth_provider = getattr(self, provider)
            redirect_uri = 'http://localhost:5000/auth/google/callback'
            logger.info(f"Using redirect URI: {redirect_uri}")
            return oauth_provider.authorize_redirect(redirect_uri)
        
        @self.app.route('/auth/<provider>/callback')
        def oauth_callback(provider):
            """Handle OAuth callback"""
            if not self.oauth_available:
                flash('Authentication not available.', 'error')
                return redirect(url_for('home'))
                
            if provider != 'google':
                flash('Invalid authentication provider.', 'error')
                return redirect(url_for('home'))
            
            try:
                # Get the authorization code from the callback
                code = request.args.get('code')
                if not code:
                    flash('Authorization failed. No code received.', 'error')
                    return redirect(url_for('login'))
                
                # Exchange code for access token
                token_data = {
                    'client_id': os.getenv('GOOGLE_CLIENT_ID'),
                    'client_secret': os.getenv('GOOGLE_CLIENT_SECRET'),
                    'code': code,
                    'grant_type': 'authorization_code',
                    'redirect_uri': 'http://localhost:5000/auth/google/callback'
                }
                
                token_response = requests.post('https://oauth2.googleapis.com/token', data=token_data)
                token_json = token_response.json()
                
                if 'access_token' not in token_json:
                    logger.error(f"Token exchange failed: {token_json}")
                    flash('Authentication failed. Please try again.', 'error')
                    return redirect(url_for('login'))
                
                # Get user info using the access token
                headers = {'Authorization': f'Bearer {token_json["access_token"]}'}
                resp = requests.get('https://www.googleapis.com/oauth2/v3/userinfo', headers=headers)
                user_data = resp.json()
                
                logger.debug(f"Google user data received: {user_data}")
                
                if not user_data or not user_data.get('email'):
                    flash('Failed to get user information from provider.', 'error')
                    return redirect(url_for('login'))
                
                user = self.login_user(user_data, provider)
                if user:
                    flash(f'Welcome back, {user.name}! Successfully signed in with Google.', 'success')
                    return redirect(url_for('home'))
                else:
                    flash('Failed to log in. Please try again.', 'error')
                    return redirect(url_for('login'))
                    
            except Exception as e:
                logger.error(f"OAuth callback error for {provider}: {str(e)}")
                flash('Authentication failed. Please try again.', 'error')
                return redirect(url_for('login'))
        
        @self.app.route('/user/profile')
        def user_profile():
            """User profile API endpoint"""
            if not self.is_authenticated():
                return jsonify({'error': 'Not authenticated'}), 401
            
            user = self.get_current_user()
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            return jsonify({
                'id': user.id,
                'email': user.email,
                'name': user.name,
                'provider': user.provider,
                'avatar_url': user.avatar_url,
                'created_at': user.created_at.isoformat(),
                'last_login': user.last_login.isoformat()
            })

def init_auth(app):
    """Initialize authentication for the Flask app"""
    # Set up session configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', secrets.token_hex(32))
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['SESSION_PERMANENT'] = False
    app.config['SESSION_USE_SIGNER'] = True
    app.config['SESSION_FILE_THRESHOLD'] = 500
    
    # Initialize Flask-Session if available
    if FLASK_SESSION_AVAILABLE:
        try:
            from flask_session import Session
            Session(app)
            logger.info("Flask-Session initialized successfully")
        except Exception as e:
            logger.warning(f"Failed to initialize Flask-Session: {e}")
    else:
        logger.info("Using basic Flask sessions (Flask-Session not available)")
    
    # Create auth manager
    auth_manager = AuthManager(app)
    auth_manager.setup_routes()
    
    return auth_manager
