from flask import Flask, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room
from flask_mysqldb import MySQL
from flask_cors import CORS
import bcrypt
import MySQLdb.cursors
from datetime import datetime
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your_secret_key')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# MySQL Configuration
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', 'your_password')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'tamil_chat')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_PORT'] = int(os.getenv('MYSQL_PORT', 3306))

# Initialize extensions
mysql = MySQL(app)
CORS(app, supports_credentials=True, origins=["http://127.0.0.1:5001"])
socketio = SocketIO(app, cors_allowed_origins="http://127.0.0.1:5001", manage_session=True)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Serve Static Files
@app.route("/")
def home():
    return send_from_directory("static", "main.html")

@app.route("/chat.html")
def chat():
    return send_from_directory("static", "chat.html")

@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory("static", filename)

# ===================== 🔐 Registration =====================
@app.route('/add_user', methods=['POST'])
def add_user():
    try:
        data = request.json
        name = data.get('name')
        email = data.get('email')
        password = data.get('password')
        gender = data.get('gender')
        age = data.get('age')

        if not all([name, email, password, gender, age]):
            logger.warning("Registration failed: Missing fields")
            return jsonify({"error": "All fields are required!"}), 400

        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE email = %s OR name = %s", (email, name))
        existing_user = cur.fetchone()

        if existing_user:
            cur.close()
            logger.warning(f"Registration failed: Email or username already exists - {email}, {name}")
            return jsonify({"error": "Email or username already registered!"}), 400

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        cur.execute(
            "INSERT INTO users (name, email, password, gender, age) VALUES (%s, %s, %s, %s, %s)",
            (name, email, hashed_password.decode('utf-8'), gender, age)
        )
        mysql.connection.commit()
        cur.close()
        logger.info(f"User registered successfully: {name}")
        return jsonify({"message": "User added successfully!"}), 201
    except Exception as e:
        logger.error(f"Error during registration: {e}")
        return jsonify({"error": "Database error occurred!"}), 500

# ===================== 🔓 Login =====================
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        # Validate input
        if not username or not password:
            logger.warning("Login failed: Missing username or password")
            return jsonify({"error": "Username and password are required!"}), 400

        # Fetch user from the database
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, name, password, avatar FROM users WHERE name = %s", (username,))
        user = cur.fetchone()
        cur.close()

        # Check if user exists
        if not user:
            logger.warning(f"Login failed: User not found for username: {username}")
            return jsonify({"error": "Invalid username or password!"}), 401

        # Check password
        if not user['password'] or not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            logger.warning(f"Login failed: Invalid password for username: {username}")
            return jsonify({"error": "Invalid username or password!"}), 401

        # Set session
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        session['avatar'] = user['avatar'] or 'default-profile.png'
        logger.info(f"User logged in successfully: {username}")

        return jsonify({"message": "Login successful!", "user": user['name'], "avatar": session['avatar']}), 200

    except Exception as e:
        logger.error(f"Error during login: {type(e).__name__}: {e}")
        return jsonify({"error": "An error occurred during login"}), 500
# ===================== 👤 Get Logged-in User =====================
@app.route('/get_user', methods=['GET'])
def get_user():
    if 'user_id' not in session:
        logger.warning("Get user failed: Not logged in")
        return jsonify({"error": "Not logged in"}), 401
    return jsonify({
        "message": "User is logged in",
        "user_id": session['user_id'],
        "user_name": session['user_name'],
        "avatar": session['avatar']
    }), 200

# ===================== 🚪 Logout =====================
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    logger.info("User logged out")
    return jsonify({"message": "Logged out successfully!"}), 200

# ===================== 📸 Upload Profile Picture =====================
@app.route('/upload_profile_picture', methods=['POST'])
def upload_profile_picture():
    if 'user_id' not in session:
        logger.warning("Profile picture upload failed: Not logged in")
        return jsonify({"error": "Not logged in"}), 401
    if 'profilePicture' not in request.files:
        logger.warning("Profile picture upload failed: No file provided")
        return jsonify({"error": "No file provided"}), 400
    file = request.files['profilePicture']
    if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']:
        filename = f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file.filename.rsplit('.', 1)[1].lower()}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        file_url = f"/static/uploads/{filename}"
        try:
            cur = mysql.connection.cursor()
            cur.execute("UPDATE users SET avatar = %s WHERE id = %s", (file_url, session['user_id']))
            mysql.connection.commit()
            cur.close()
            session['avatar'] = file_url
            if session['user_id'] in online_users:
                online_users[session['user_id']]['avatar'] = file_url
            socketio.emit('update_users', {"online": list(online_users.values())}, broadcast=True)
            logger.info(f"Profile picture uploaded for user: {session['user_name']}")
            return jsonify({"success": True, "url": file_url}), 200
        except Exception as e:
            logger.error(f"Error uploading profile picture: {e}")
            return jsonify({"error": "Failed to upload picture"}), 500
    logger.warning("Profile picture upload failed: Invalid file type")
    return jsonify({"error": "Invalid file type"}), 400

# ===================== 🔄 Update Status =====================
@app.route('/update_status', methods=['POST'])
def update_status():
    if 'user_id' not in session:
        logger.warning("Status update failed: Not logged in")
        return jsonify({"error": "Not logged in"}), 401
    data = request.json
    status = data.get('status')
    if status not in ['online', 'offline', 'away']:
        logger.warning(f"Status update failed: Invalid status - {status}")
        return jsonify({"error": "Invalid status"}), 400
    try:
        cur = mysql.connection.cursor()
        cur.execute("UPDATE users SET status = %s WHERE id = %s", (status, session['user_id']))
        mysql.connection.commit()
        cur.close()
        session['status'] = status
        if session['user_id'] in online_users:
            online_users[session['user_id']]['status'] = status
        socketio.emit('update_users', {"online": list(online_users.values())}, broadcast=True)
        logger.info(f"Status updated to {status} for user: {session['user_name']}")
        return jsonify({"message": f"Status updated to {status}"}), 200
    except Exception as e:
        logger.error(f"Error updating status: {e}")
        return jsonify({"error": "Failed to update status"}), 500

# ===================== 📰 News API =====================
@app.route('/api/news', methods=['GET'])
def get_news():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT title, content, created_at FROM news ORDER BY created_at DESC LIMIT 10")
        news = cur.fetchall()
        cur.close()
        logger.info("News fetched successfully")
        return jsonify(news), 200
    except Exception as e:
        logger.error(f"Error fetching news: {e}")
        return jsonify({"error": "Failed to fetch news"}), 500

# ===================== 💬 Messages API =====================
@app.route('/api/messages', methods=['GET'])
def get_messages():
    page = int(request.args.get('page', 1))
    per_page = 50
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "SELECT sender, sender_photo, message, created_at, private FROM messages ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (per_page, (page - 1) * per_page)
        )
        messages = cur.fetchall()
        cur.close()
        logger.info(f"Messages fetched for page {page}")
        return jsonify(messages), 200
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        return jsonify({"error": "Failed to fetch messages"}), 500

# ===================== 📝 Forum Posts API =====================
@app.route('/add_forum_post', methods=['POST'])
def add_forum_post():
    if 'user_id' not in session:
        logger.warning("Forum post failed: Not logged in")
        return jsonify({"error": "Not logged in"}), 401
    data = request.json
    title = data.get('title')
    content = data.get('content')
    if not title or not content:
        logger.warning("Forum post failed: Missing title or content")
        return jsonify({"error": "Title and content are required"}), 400
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO forum_posts (user_id, title, content) VALUES (%s, %s, %s)",
            (session['user_id'], title, content)
        )
        mysql.connection.commit()
        cur.close()
        logger.info(f"Forum post added by user: {session['user_name']}")
        return jsonify({"message": "Forum post added successfully"}), 201
    except Exception as e:
        logger.error(f"Error adding forum post: {e}")
        return jsonify({"error": "Failed to add forum post"}), 500

@app.route('/api/forum', methods=['GET'])
def get_forum():
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT f.id, f.title, f.content, f.created_at, u.name AS user_name FROM forum_posts f JOIN users u ON f.user_id = u.id ORDER BY f.created_at DESC LIMIT 10")
        posts = cur.fetchall()
        cur.close()
        logger.info("Forum posts fetched successfully")
        return jsonify(posts), 200
    except Exception as e:
        logger.error(f"Error fetching forum posts: {e}")
        return jsonify({"error": "Failed to fetch forum posts"}), 500

# ===================== ⚙️ Update Settings =====================
@app.route('/update_settings', methods=['POST'])
def update_settings():
    if 'user_id' not in session:
        logger.warning("Settings update failed: Not logged in")
        return jsonify({"error": "Not logged in"}), 401
    data = request.json
    theme = data.get('theme')
    chat_sounds = data.get('chat_sounds')
    private_chat = data.get('private_chat')
    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "UPDATE users SET theme = %s, chat_sounds = %s, private_chat = %s WHERE id = %s",
            (theme, chat_sounds, private_chat, session['user_id'])
        )
        mysql.connection.commit()
        cur.close()
        session['theme'] = theme
        session['chat_sounds'] = chat_sounds
        session['private_chat'] = private_chat
        logger.info(f"Settings updated for user: {session['user_name']}")
        return jsonify({"message": "Settings updated successfully"}), 200
    except Exception as e:
        logger.error(f"Error updating settings: {e}")
        return jsonify({"error": "Failed to update settings"}), 500

# ===================== 💬 SocketIO Chat =====================
online_users = {}

@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if not user_id:
        logger.warning("SocketIO connect rejected: Not logged in")
        return False  # Disconnect unauthenticated users

    user_info = {
        "id": user_id,
        "name": session.get('user_name', 'Guest'),
        "avatar": session.get('avatar', 'default-profile.png'),
        "status": session.get('status', 'online'),
        "level": session.get('level', 1)
    }

    online_users[user_id] = user_info
    join_room('global')
    logger.info(f"{user_info['name']} connected to SocketIO")

    # Notify all users
    socketio.emit('update_users', {"online": list(online_users.values())}, broadcast=True)
    socketio.emit('user_joined', {"user": user_info}, room="public")

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id and user_id in online_users:
        user_name = online_users[user_id]['name']
        del online_users[user_id]
        logger.info(f"{user_name} disconnected from SocketIO")
        socketio.emit('user_left', {"user": online_users[user_id]}, room="public")
        socketio.emit('update_users', {"online": list(online_users.values())}, broadcast=True)

@socketio.on('join_room')
def handle_join_room(room):
    user_name = session.get('user_name', 'Guest')
    join_room(room)
    emit('chat_message', {
        "sender": "System",
        "message": f"{user_name} has joined the {room} room.",
        "system": True,
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }, room=room)
    logger.info(f"{user_name} joined room {room}")

@socketio.on('chat_message')
def handle_chat(data):
    sender = session.get('user_name', 'Guest')
    room = data.get('room', 'general')
    message = data.get('message')
    private = data.get('private', False)
    sender_photo = session.get('avatar', 'default-profile.png')
    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    if not message:
        logger.warning(f"Empty message from {sender}")
        return

    try:
        cur = mysql.connection.cursor()
        cur.execute(
            "INSERT INTO messages (sender, sender_photo, message, private) VALUES (%s, %s, %s, %s)",
            (sender, sender_photo, message, private)
        )
        mysql.connection.commit()
        cur.close()
    except Exception as e:
        logger.error(f"Error saving message: {e}")

    emit('chat_message', {
        "sender": sender,
        "sender_photo": sender_photo,
        "message": message,
        "created_at": created_at,
        "private": private,
        "system": data.get('system', False)
    }, room=room)
    logger.info(f"Message from {sender} in {room}: {message}")

# ===================== 🧪 Debugging Session Data =====================
@app.route('/debug-session', methods=['GET'])
def debug_session():
    return jsonify(dict(session))

# ===================== 🚨 Global Error Handler =====================
@app.errorhandler(Exception)
def handle_error(error):
    logger.error(f"Unexpected error: {error}")
    return jsonify({"error": "An unexpected error occurred"}), 500

# ===================== 🔁 Run the App =====================
if __name__ == '__main__':
    socketio.run(app, debug=True, host="127.0.0.1", port=5001)