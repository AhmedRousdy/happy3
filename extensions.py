from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

# Configure login manager
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in with your Exchange credentials to access this application.'
login_manager.login_message_category = 'info'