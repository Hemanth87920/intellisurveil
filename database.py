from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

# User Table
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(50), nullable=False)

# Activity Log Table
class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.now)
    event_type = db.Column(db.String(50))
    details = db.Column(db.String(100))
    severity = db.Column(db.String(20))

    def to_dict(self):
        return {
            'time': self.timestamp.strftime('%H:%M:%S'),
            'type': self.event_type,
            'details': self.details,
            'severity': self.severity
        }

def init_db(app):
    db.init_app(app)
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', password='admin123'))
            db.session.commit()
            print("Database Initialized. Admin created.")