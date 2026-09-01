# House Premiere League (HPL) — Professional Cricket Scoring & Tournament Platform

A modern, production-ready cricket platform and live scoring engine built for college, club, and professional tournaments. Features full multi-league tournament management, flexible match formats (including T6, T10, T20 with custom player counts), authoritative ball-by-ball scoring, real-time Server-Sent Events (SSE), comprehensive scorecards, and live points tables with Net Run Rate (NRR) synchronization.

---

## 🚀 Key Features

- **Authoritative Cricket Scoring Engine**:
  - Full delivery lifecycle: normal balls, strike rotation, overs, wides, no-balls, byes, leg-byes.
  - Multi-wicket tracking: bowled, caught, run out, stumped, LBW, hit wicket with fielder tracking and bowler attribution rules.
  - Dynamic Playing XI sizing (e.g. 8 players / 7 wickets all-out, standard 11 players / 10 wickets all-out).
  - Operational Live Scorer workspace with fast run keypad, Undo, and Edit Last Ball capabilities.
  - 2nd innings automatic target calculation, required run rate (RRR), and chase completion.
- **Tournament & Fixture Management**:
  - Multi-league isolation (Leagues 1 & 2 with independent points tables and statistics).
  - Fixture scheduling with format presets (T6, T10, T20, custom overs & squad sizes).
  - Match Setup modal: Playing XI selector with live headcount validation, captain/keeper tags, and toss configuration.
- **Match Center & Live Fan Experience**:
  - Live Pitch view with active striker, non-striker, bowler economy, ball-by-ball over strip, and CRR/RRR indicators.
  - Complete Batting & Bowling scorecards with dismissal details and Fall of Wickets.
  - Timeline commentary and over-by-over analysis.
  - Squad rosters, team profiles, player career statistics, and tournament leaderboards.
- **Real-Time Synchronization**:
  - Server-Sent Events (SSE) live updates streaming directly from the database to fans.
- **Security & Administration**:
  - Role-based admin authentication with rate-limiting, session protection, and secured mutation APIs.

---

## 🛠️ Technology Stack

- **Backend**: Python 3.10+, Flask, SQLite3 (with thread-safe row factories and foreign keys enabled)
- **Frontend**: HTML5, Vanilla JavaScript (ES6+), Vanilla CSS with sports design token system
- **Typography**: Google Fonts (`Outfit` for scoreboards & figures, `Inter` for metadata)
- **Icons**: Font Awesome 6.5
- **Real-Time**: Server-Sent Events (`EventSource`)

---

## ⚙️ Environment Configuration

Copy `.env.example` to `.env` and configure environment variables:

```bash
cp .env.example .env
```

| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | Environment mode (`production`, `development`, `testing`) | `production` |
| `PORT` | HTTP Server port | `8080` |
| `SECRET_KEY` | Flask session cryptographic key | Random string |
| `CRICKET_DB_PATH` | Path to SQLite database file | `data/cricket.db` |
| `MONGODB_URI` | Optional MongoDB Atlas URI for secondary backup | None |

---

## 💻 Local Development

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   # or: pip install flask flask-cors pymongo certifi python-dotenv
   ```

2. **Start the Development Server**:
   ```bash
   python server.py
   ```

3. **Access the Platform**:
   - Public Home: [http://localhost:8080](http://localhost:8080)
   - Live Match Center: [http://localhost:8080/match/1](http://localhost:8080/match/1)
   - Admin Control Center: [http://localhost:8080/admin](http://localhost:8080/admin) (Default Login: `gowthamkrishna18v@gmail.com` / `0724`)

---

## 🧪 Running Automated Tests

Run the complete isolated integration test suite:

```bash
python -m unittest test_integration.py
```

*Note: Automated tests execute against an isolated temporary test database (`data/test_cricket.db`) and never alter or pollute production tournament data.*

---

## 🌐 Production Deployment

For the complete step-by-step production deployment guide covering Linux Systemd, Nginx SSL reverse proxies, Docker Compose, Cloud PaaS (Render, Railway, Fly.io), and Windows Server, refer to the [Deployment Guide](DEPLOYMENT.md).

### Quick Start: Production WSGI (Gunicorn / Linux)
```bash
gunicorn --workers 1 --threads 16 --worker-class gthread --bind 0.0.0.0:8080 server:app
```

### Quick Start: Docker Compose
```bash
docker compose up -d --build
```

### Quick Start: Production WSGI (Waitress / Windows)
```bash
waitress-serve --listen=0.0.0.0:8080 --threads=16 server:app
```

---

## 🔒 Security Best Practices

- Change default administrator credentials immediately via **Admin → Settings** or `/api/admin/admins/change-password`.
- Set `app.config["SESSION_COOKIE_SECURE"] = True` when serving behind HTTPS/TLS reverse proxy.
- All match mutation endpoints (`/api/admin/*`) require active admin session authorization.

---

## 📄 License
Released under the MIT License.
