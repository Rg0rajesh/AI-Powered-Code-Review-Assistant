# 🔍 LintVertex — AI-Powered Code Review SaaS
#### Disclaimer: **email servies and otp services**not work  due to for **Render new polices**
Premium code review platform powered by **Gemini AI**, **ML models**, and **real-time team collaboration** via SSE.

---

## ✨ Features

| Feature | Details |
|---|---|
| 🤖 AI Analysis | Gemini 2.5 Flash primary · Ollama local fallback |
| 🧠 ML Scoring | Random Forest + rule-based quality scoring (0–100, A–F) |
| 🔍 Auto-Detect | Python · Java · C · C++ — rule-based + ML hybrid |
| 💬 Discussion Rooms | SSE real-time · Human-only · Room key sharing |
| 🛡️ Security | JWT · bcrypt · RLS · API keys server-side only |
| 🎨 Premium UI | Ivory/Olive (light) · Black/White (dark) · Glassmorphism |
| 📊 Admin Panel | Users · Analyses · Rooms · Feedback · Activity logs |

---

## 🚀 Quick Start

### 1. Clone & Setup Backend

```bash
cd backend
cp .env.example .env
# Fill in your .env values (see Configuration below)
pip install -r requirements.txt
python app.py
```

### 2. Setup Database

1. Go to your [Supabase](https://supabase.com) project → SQL Editor
2. Copy and run the contents of `backend/supabase_schema.sql`
3. Copy your `SUPABASE_URL` and both keys into `.env`

### 3. Get Gemini API Key

1. Visit [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create an API key
3. Add to `.env` as `GEMINI_API_KEY=your_key`

### 4. Start the App

```bash
# Development
cd backend && python app.py

# Production (Gunicorn)
gunicorn --bind 0.0.0.0:5000 --workers 2 app:app
```

Open `http://localhost:5000` in your browser.

---

## ⚙️ Configuration

Edit `backend/.env`:

```env
# Supabase
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Gemini AI (NEVER expose this in frontend)
GEMINI_API_KEY=AIza...

# Flask security keys (use long random strings)
FLASK_SECRET_KEY=change_me_to_random_string
JWT_SECRET_KEY=another_random_string

# Ollama (optional local fallback)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=codellama
```

---

## 📁 Project Structure

```
lintvertex/
├── backend/
│   ├── app.py                  # Flask app entry point
│   ├── config.py               # Configuration (reads .env)
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── supabase_schema.sql     # Run this in Supabase SQL Editor
│   ├── routes/
│   │   ├── auth.py             # Signup, login, JWT
│   │   ├── analysis.py         # Code analysis pipeline
│   │   ├── rooms.py            # Discussion rooms + SSE
│   │   └── other.py            # Profile, feedback, admin
│   ├── services/
│   │   ├── supabase_client.py  # All DB operations
│   │   ├── language_detector.py# Auto-detect language
│   │   ├── ml_service.py       # Quality scoring + issue detection
│   │   └── ai_service.py       # Gemini + Ollama pipeline
│   └── utils/
│       └── security.py         # JWT, bcrypt, validation
│
└── frontend/
    ├── index.html              # Landing page
    ├── login.html
    ├── signup.html
    ├── dashboard.html
    ├── analyze.html            # Code analysis + results
    ├── history.html
    ├── rooms.html              # SSE real-time chat
    ├── profile.html
    ├── feedback.html
    ├── admin.html
    ├── css/
    │   └── main.css            # Full design system
    └── js/
        └── app.js              # Auth, API client, utils
```

---

## 🌐 Deployment

### Backend → Render

1. Push `backend/` to a GitHub repo
2. Create a new **Web Service** on [render.com](https://render.com)
3. Set **Docker** as the environment
4. Add all `.env` variables in the Render dashboard
5. Deploy!

### Frontend → Vercel

1. Push `frontend/` to a GitHub repo
2. Import to [vercel.com](https://vercel.com)
3. Set `API_BASE` in `js/app.js` to your Render backend URL
4. Deploy!

### Supabase
- Already cloud-hosted at `your-project.supabase.co`
- Enable RLS (done in schema)
- Enable email auth if needed

---

## 🔒 Security Notes

- **API keys** are stored in `.env` and only accessible by the backend
- **Never** put `GEMINI_API_KEY` in frontend JavaScript
- All AI calls go through Flask backend routes
- JWT tokens expire in 24 hours (configurable)
- Passwords hashed with bcrypt (12 rounds)
- Supabase Row Level Security enabled on all tables
- File uploads validated by type and size (JPG/PNG, max 2MB)

---

## 🛠️ Tech Stack

- **Backend**: Flask (Python), Gunicorn
- **Database**: Supabase (PostgreSQL) + JWT
- **AI**: Google Gemini 1.5 Flash + Ollama fallback
- **ML**: scikit-learn (Random Forest, Gradient Boosting)
- **Real-time**: Server-Sent Events (SSE)
- **Frontend**: HTML5, CSS3, Vanilla JS (no frameworks)
- **Deploy**: Render (backend) + Vercel (frontend)

---

