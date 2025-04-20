from flask import Flask, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, send, emit
from flask_mysqldb import MySQL
import bcrypt
import MySQLdb.cursors
from flask_cors import CORS

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['session_type']='filesystem'


# MySQL Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'Devi@123'
app.config['MYSQL_DB'] = 'tamil_chat'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'
app.config['MYSQL_PORT'] = 3306

mysql = MySQL(app)
socketio = SocketIO(app, cors_allowed_origins="*",manage_session=False)

# Serve Static Files
@app.route("/")
def home():
    return send_from_directory(".", "main.html")

@app.route("/chat.html")
def chat():
    return send_from_directory(".", "chat.html")

@app.route("/script.js")
def script():
    return send_from_directory(".", "script.js")


# ===================== 🔐 Registration =====================
@app.route('/add_user', methods=['POST'])
def add_user():
    data = request.json
    print("Received data for registration:", data)  # Debugging
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    gender = data.get('gender')
    age = data.get('age')

    # Check for missing fields
    if not name or not email or not password or not gender or not age:
        print("Validation failed: Missing fields")  # Debugging
        return jsonify({"error": "All fields are required!"}), 400

    cur = mysql.connection.cursor()

    # Check if email already exists
    cur.execute("SELECT id FROM users WHERE email = %s", (email,))
    existing_user = cur.fetchone()

    if existing_user:
        cur.close()
        print("Validation failed: Email already registered")  # Debugging
        return jsonify({"error": "Email already registered!"}), 400

    # Hash the password
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    # Insert new user
    try:
        cur.execute("INSERT INTO users (name, email, password, gender, age) VALUES (%s, %s, %s, %s, %s)",
                    (name, email, hashed_password.decode('utf-8'), gender, age))
        mysql.connection.commit()
        print("User added successfully")  # Debugging
    except Exception as e:
        print("Database error:", e)  # Debugging
        return jsonify({"error": "Database error occurred!"}), 500
    finally:
        cur.close()

    return jsonify({"message": "User added successfully!"}), 201

# ===================== 🔓 Login (using username) =====================
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        # Query the database for the user
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT id, name, password FROM users WHERE name = %s", (username,))
        user = cursor.fetchone()
        cursor.close()

        if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({"error": "Invalid username or password!"}), 400

        # Store user information in the session
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        print("Session after login:", session)  # Debugging

        return jsonify({"message": "Login successful!", "user": user['name']}), 200
    except Exception as e:
        print("Error during login:", e)
        return jsonify({"error": "An error occurred during login"}), 500
# ===================== 👤 Get Logged-in User =====================
@app.route('/get_user', methods=['GET'])
def get_user():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401

    return jsonify({
        "message": "User is logged in",
        "user_id": session['user_id'],
        "user_name": session['user_name']
    })


# ===================== 🚪 Logout =====================
@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    print("User logged out.")
    return jsonify({"message": "Logged out successfully!"}), 200


# ===================== 💬 SocketIO Chat =====================
@socketio.on("chat_message")
def handle_chat(data):
    print(f"\U0001f4e8 New message: {data}")
    emit("chat_message", data, broadcast=True)

@socketio.on('send_message')
def handle_message(msg):
    sender = session.get('user_name', 'Guest')
    print(f"Message from {sender}: {msg}")
    send({"sender": sender, "message": msg}, broadcast=True)
# ===================== 🟢 Online/Offline User Status =====================

# Store online users
online_users = {}

@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    user_name = session.get('user_name', 'Guest')
    user_avatar = session.get('avatar', 'default-profile.png')  # Default avatar
    user_level = session.get('level', 1)  # Default level

    if user_id:
        online_users[user_id] = {
            "name": user_name,
            "avatar": user_avatar,
            "level": user_level
        }
        emit('update_users', {"online": list(online_users.values())}, broadcast=True)
          # 🔥 Send a system join message
        emit('chat_message', {
            "sender": "System",
            "message": f"{user_name} has joined the chat room.",
            "system": True
        }, broadcast=True)
        print(f"{user_name} connected. Online users: {online_users}")

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id and user_id in online_users:
        user_name = online_users[user_id]["name"]
        online_users.pop(user_id)
        emit('update_users', {"online": list(online_users.values())}, broadcast=True)
        print(f"{user_name} disconnected. Online users: {online_users}")
# ===================== 🧑 Get Username via API =====================
@app.route('/api/get-username', methods=['GET'])
def get_username():
    if 'user_name' not in session:
        return jsonify({"error": "User not logged in"}), 401
    return jsonify({"username": session['user_name']}), 200

# ===================== 🧪 Debugging Session Data =====================
@app.route('/debug-session', methods=['GET'])
def debug_session():
    return jsonify(dict(session))
# ===================== 🔁 Run the App =====================
if __name__ == '__main__':
    socketio.run(app, debug=True, host="127.0.0.1", port=5001)
