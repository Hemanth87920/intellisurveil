from flask import Flask, render_template, Response, request, redirect, url_for, session, jsonify
from database import db, init_db, User, ActivityLog
from camera import IntelligentCamera
import os

app = Flask(__name__)

# SECRET KEY
app.secret_key = "INTELLISURVEIL_SECURE_KEY"

# DATABASE CONFIG (Cloud friendly)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///intelli.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

init_db(app)

camera = None

def get_camera():
    global camera
    if camera is None:
        camera = IntelligentCamera(app)
    return camera

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(
            username=request.form['username'],
            password=request.form['password']
        ).first()

        if user:
            session['user'] = user.username
            return redirect(url_for('dashboard'))

        return render_template('login.html', error="Invalid Credentials")

    return render_template('login.html')


# REGISTER ROUTE
@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user' in session:
        return redirect(url_for('dashboard'))

    error = None

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']

        if password != confirm_password:
            error = "Passwords do not match!"
        else:
            existing_user = User.query.filter_by(username=username).first()
            if existing_user:
                error = "Username already exists!"
            else:
                new_user = User(username=username, password=password)
                db.session.add(new_user)
                db.session.commit()
                return redirect(url_for('login'))

    return render_template('register.html', error=error)


@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', user=session['user'])


@app.route('/video_feed')
def video_feed():
    return Response(gen_frames(get_camera()),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def gen_frames(cam):
    while True:
        frame = cam.get_frame()
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


# API ROUTES
@app.route('/api/start_system', methods=['POST'])
def start_system():
    get_camera().start_camera()
    return jsonify({"status": "started"})


@app.route('/api/stop_system', methods=['POST'])
def stop_system():
    get_camera().stop_camera()
    return jsonify({"status": "stopped"})


@app.route('/api/toggle_siren', methods=['POST'])
def toggle_siren():
    get_camera().siren_enabled = request.get_json().get('enabled', True)
    return jsonify({"status": "success"})


@app.route('/api/get_logs')
def get_logs():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
    return jsonify([log.to_dict() for log in logs])


@app.route('/logout')
def logout():
    session.pop('user', None)
    if camera:
        camera.stop_camera()
    return redirect(url_for('login'))


# ✅ IMPORTANT FOR DEPLOYMENT
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)