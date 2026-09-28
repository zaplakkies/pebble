from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from pebble.config import Config

db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)

    from pebble import models  # noqa: F401  (register models for migrations)
    from pebble.api.routes import api
    from pebble.main.routes import main
    from pebble.manage.routes import manage
    from pebble.cli import register_cli
    from pebble.filters import register_filters

    app.register_blueprint(main)
    app.register_blueprint(api, url_prefix='/api/v1')
    app.register_blueprint(manage, url_prefix='/' + app.config['MANAGE_PATH'].strip('/'))
    register_cli(app)
    register_filters(app)

    return app
