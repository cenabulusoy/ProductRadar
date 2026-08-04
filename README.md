# ProductRadar

ProductRadar helpt ondernemers producten beoordelen vóórdat zij inkopen. Deze eerste GitHub-klare versie bevat een Next.js-dashboard, een FastAPI-backend, een lokale SQLite-database, vijf testproducten en een transparante Opportunity Score.

## Snel starten op Windows 11

### Backend
1. Open deze map in Visual Studio Code.
2. Open **Terminal > New Terminal**.
3. Voer uit:

```powershell
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
Open een tweede terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open daarna http://localhost:3000.

## Eerste functies
- Dashboard
- Product Hunter
- Productdetails
- Market, Profit, Risk en Opportunity Score
- Winstberekening
- Waarom kopen / waarom niet kopen
- SQLite-opslag
- API-documentatie op http://localhost:8000/docs

Zie `docs/ROADMAP.md` en `docs/VISION.md`.
