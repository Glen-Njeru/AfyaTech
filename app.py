from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import os
import requests
import json
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'mindjournal-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/mindjournal.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def ask_groq(prompt):
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.4,
            "max_tokens": 300
        }
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=10)
        data = resp.json()
        return data['choices'][0]['message']['content'].strip()
    except Exception:
        return None

def get_ai_reflection(name, mood, content, avg_mood=None):
    mood_context = ""
    if avg_mood:
        diff = mood - avg_mood
        if diff <= -2:
            mood_context = "This is notably lower than their usual mood."
        elif diff >= 2:
            mood_context = "This is notably higher than their usual mood."
    prompt = f"""You are Afya, a warm and culturally aware mental wellness guide for AfyaTech, a Kenyan mental health journaling platform.

A user named {name} just wrote a journal entry. Their mood today is {mood}/10. {mood_context}

Their journal entry:
"{content}"

Write a short, warm, personal reflection (3 sentences maximum) that:
1. Validates their specific feelings using warm, relatable language (not clinical)
2. Offers one simple grounding thought connected to what they wrote
3. Ends with one gentle, open question to help them reflect deeper

Rules:
- Be warm like a trusted friend, not a therapist
- 3 sentences maximum
- No clinical terms
- No paid service suggestions
- If mood is 3 or below, end with: You are not alone.
- Respond in English only"""
    return ask_groq(prompt)

def get_ai_weekly_insight(entries):
    if not entries:
        return None
    moods = [e.mood for e in entries]
    avg = sum(moods) / len(moods)
    themes = " | ".join([e.content[:80] for e in entries[:5]])
    prompt = f"""You are Afya, a compassionate AI wellness guide for AfyaTech Kenya.

A user has journaled {len(entries)} times recently. Their average mood is {avg:.1f}/10.
Recent entry themes: {themes}

Write a warm weekly insight (4 sentences maximum) that:
1. Celebrates something positive you notice
2. Identifies one emotional pattern across their entries
3. Offers one simple free self-care tip
4. Ends with an encouraging sentence

Be warm, brief, and grounded. No clinical language."""
    return ask_groq(prompt)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access your journal.'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    entries = db.relationship('Entry', backref='user', lazy=True, cascade='all, delete-orphan')

class Entry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mood = db.Column(db.Integer, nullable=False)
    content = db.Column(db.Text, nullable=False)
    ai_reflection = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    entry_date = db.Column(db.Date, default=date.today)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('landing.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not name or not email or not password:
            flash('All fields are required.', 'error')
            return render_template('signup.html')
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.', 'error')
            return render_template('signup.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'error')
            return render_template('signup.html')
        user = User(name=name, email=email, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash(f'Welcome, {name}! Your journal is ready.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    entries = Entry.query.filter_by(user_id=current_user.id)\
                         .order_by(Entry.created_at.desc()).limit(30).all()
    total = Entry.query.filter_by(user_id=current_user.id).count()
    avg_mood = db.session.query(db.func.avg(Entry.mood))\
                         .filter_by(user_id=current_user.id).scalar()
    avg_mood = round(avg_mood, 1) if avg_mood else None
    streak = 0
    today = date.today()
    check = today
    while True:
        has = Entry.query.filter_by(user_id=current_user.id, entry_date=check).first()
        if has:
            streak += 1
            check = date.fromordinal(check.toordinal() - 1)
        else:
            break
    chart_entries = Entry.query.filter_by(user_id=current_user.id)\
                               .order_by(Entry.created_at.asc()).limit(14).all()
    chart_labels = [e.created_at.strftime('%b %d') for e in chart_entries]
    chart_moods = [e.mood for e in chart_entries]
    recent = Entry.query.filter_by(user_id=current_user.id)\
                        .order_by(Entry.created_at.desc()).limit(7).all()
    weekly_insight = get_ai_weekly_insight(recent) if recent else None
    return render_template('dashboard.html', entries=entries, total=total,
                           avg_mood=avg_mood, streak=streak,
                           chart_labels=chart_labels, chart_moods=chart_moods,
                           weekly_insight=weekly_insight,
                           now_hour=datetime.now().hour)

@app.route('/journal', methods=['GET', 'POST'])
@login_required
def journal():
    if request.method == 'POST':
        mood = request.form.get('mood')
        content = request.form.get('content', '').strip()
        if not mood or not content:
            flash('Please fill in both your mood and your journal entry.', 'error')
            return render_template('journal.html', today=date.today().strftime('%B %d, %Y'))
        avg_mood = db.session.query(db.func.avg(Entry.mood))\
                             .filter_by(user_id=current_user.id).scalar()
        ai_reflection = get_ai_reflection(
            current_user.name.split()[0], int(mood), content, avg_mood)
        entry = Entry(user_id=current_user.id, mood=int(mood),
                      content=content, ai_reflection=ai_reflection,
                      entry_date=date.today())
        db.session.add(entry)
        db.session.commit()
        return redirect(url_for('entry_result', entry_id=entry.id))
    return render_template('journal.html', today=date.today().strftime('%B %d, %Y'))

@app.route('/entry/<int:entry_id>')
@login_required
def entry_result(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id:
        return redirect(url_for('dashboard'))
    return render_template('entry_result.html', entry=entry)

@app.route('/history')
@login_required
def history():
    page = request.args.get('page', 1, type=int)
    entries = Entry.query.filter_by(user_id=current_user.id)\
                         .order_by(Entry.created_at.desc())\
                         .paginate(page=page, per_page=10, error_out=False)
    return render_template('history.html', entries=entries)

@app.route('/entry/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    entry = Entry.query.get_or_404(entry_id)
    if entry.user_id != current_user.id:
        flash('Not allowed.', 'error')
        return redirect(url_for('history'))
    db.session.delete(entry)
    db.session.commit()
    flash('Entry deleted.', 'success')
    return redirect(url_for('history'))

@app.route('/breathe')
@login_required
def breathe():
    return render_template('breathe.html')

@app.route('/chat-page')
@login_required
def chat_page():
    return render_template('chat.html')

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.get_json()
    user_message = data.get('message', '')
    history = data.get('history', [])
    system = f"""You are Afya, a warm and emotionally intelligent AI wellness companion for AfyaTech, a Kenyan mental health platform. You are talking to {current_user.name.split()[0]}.

Your personality:
- Warm, gentle, and non-judgmental like a trusted friend
- Culturally aware of Kenyan and African realities
- You listen first, then respond thoughtfully
- You never diagnose or prescribe
- You keep responses concise — 2 to 4 sentences maximum
- If someone seems in crisis, gently encourage them to call a helpline
- You never use clinical jargon
- You sometimes ask one gentle follow-up question to keep the conversation going"""

    messages = [{"role": "system", "content": system}]
    for h in history[-10:]:
        messages.append(h)
    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "temperature": 0.5,
            "max_tokens": 200
        }
        resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=10)
        reply = resp.json()['choices'][0]['message']['content'].strip()
    except Exception:
        reply = "I'm here with you. Sometimes words are hard to find — take your time. What's on your heart right now?"
    return jsonify({"reply": reply})

if __name__ == '__main__':
    if __name__ == '__main__':
        db.create_all()
    app.run(debug=True)