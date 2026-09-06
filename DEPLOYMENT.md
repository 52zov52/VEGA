=== RENDER DEPLOYMENT INSTRUCTIONS ===

1. PUSH CODE TO GITHUB
   git add .
   git commit -m "prepare render deployment"
   git push origin main

2. DEPLOY TO RENDER
   - Go to render.com and create a new account
   - Click "New +" → "Web Service"
   - Select "Docker" as the environment
   - Connect your GitHub repository
   - Render will auto-detect render.yaml

3. SERVICES DEPLOYED:
   - vega-api: FastAPI on port 8000 (Dockerfile: docker/api.Dockerfile)
   - vega-db: PostgreSQL with PostGIS (free plan)
   - vega-redis: Redis cache (free plan)
   - vega-web: Next.js frontend on port 3000 (Dockerfile: docker/web.Dockerfile)

4. ENVIRONMENT VARIABLES
   - Render auto-injects from render.yaml .env file
   - DATABASE_URL and REDIS_URL auto-injected by Render
   - Set additional vars in dashboard if needed:
     * SENTINEL_API_URL, SENTINEL_API_KEY
     * WEATHER_API_KEY (optional, defaults to open-meteo)
     * OVERPASS_API_URL

5. ACCESS YOUR APP
   - API: https://vega-api.onrender.com
   - Docs: https://vega-api.onrender.com/docs
   - Frontend: https://vega-web.onrender.com

6. FREE PLAN NOTES
   - Services sleep after 15 mins of inactivity
   - First cold start takes 30-60 seconds
   - Database persists storage (preserveStorage: true)