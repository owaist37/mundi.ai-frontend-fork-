# Mundi Frontend

<h4 align="center">
  <a href="https://github.com/BuntingLabs/mundi.ai/actions/workflows/cicd.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/BuntingLabs/mundi.ai/cicd.yml?label=CI" alt="GitHub Actions Workflow Status" />
  </a>
  <a href="https://github.com/BuntingLabs/mundi.ai/actions/workflows/lint.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/BuntingLabs/mundi.ai/lint.yml?label=lint" alt="GitHub Actions Lint Status" />
  </a>
  <a href="https://discord.gg/V63VbgH8dT">
    <img src="https://dcbadge.limes.pink/api/server/V63VbgH8dT?style=plastic" alt="Discord" />
  </a>
  <a href="https://github.com/BuntingLabs/mundi.ai/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/BuntingLabs/mundi.ai" alt="GitHub License" />
  </a>
</h4>

![Mundi](./docs/src/assets/social.png)

## Frontend-Only Version

This is a **frontend-only** version of Mundi.ai that has been separated from the full-stack GIS application. It contains:

- **React Frontend**: Complete TypeScript/React application in `frontendts/`
- **Minimal FastAPI Server**: Basic server that serves the React SPA with mock authentication
- **Documentation**: Frontend documentation and guides

### What's Included
- ✅ Complete React TypeScript application
- ✅ UI components and design system
- ✅ Basic FastAPI server for SPA serving
- ✅ Mock authentication for development
- ✅ Frontend documentation

### What's Removed
- ❌ Database layer (PostgreSQL, PostGIS)
- ❌ Geospatial processing (GDAL, QGIS integration)
- ❌ API routes for maps, layers, projects
- ❌ Real-time collaboration (DriftDB)
- ❌ File upload and storage (S3)
- ❌ LLM integration and chat features
- ❌ Docker services and full deployment stack

## Quick Start

### Prerequisites
- Python 3.8+
- Node.js 18+

### Running the Frontend

1. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Build the React application**:
   ```bash
   cd frontendts
   npm install
   npm run build
   cd ..
   ```

3. **Start the server**:
   ```bash
   python run-frontend.py
   ```

4. **Open your browser** to `http://localhost:8000`

### Development Mode

For frontend development with hot reload:

```bash
# Terminal 1: Start the Python server
python run-frontend.py

# Terminal 2: Start the Vite dev server
cd frontendts
npm run dev
```

Then open `http://localhost:5173` for the Vite dev server with hot reload.

## Configuration

The frontend is designed to connect to a separate backend API. Update the Vite configuration in `frontendts/vite.config.ts` to point to your backend:

```typescript
server: {
  proxy: {
    '/api': {
      target: 'http://your-backend-api:8000',
      changeOrigin: true,
    },
  }
}
```

## Architecture

This frontend-only version maintains the original hybrid architecture:
- FastAPI serves the built React application as static files
- SPA fallback handler routes all non-API requests to `index.html`
- Mock authentication endpoint for SuperTokens compatibility
- Frontend remains unchanged and can connect to any compatible backend

## Documentation

Frontend-specific documentation is available in:
- `dev_docs/frontendts/` - Technical documentation
- `docs/` - User guides and deployment docs

For the complete GIS functionality, see the main [Mundi.ai repository](https://github.com/BuntingLabs/mundi.ai).

## License

Mundi is licensed as [AGPLv3](./LICENSE).