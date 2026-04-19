# ── Image de base : uv officiel avec Python 3.12 ─────────────────────────────
# https://github.com/astral-sh/uv-docker-example
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# ── Utilisateur non-root (bonne pratique Kubernetes) ─────────────────────────
# uid/gid 1001 évite les conflits avec les comptes système courants (1000)
RUN groupadd --gid 1001 appuser && \
    useradd  --uid 1001 --gid 1001 --no-create-home --shell /bin/bash appuser

# ── Répertoire de travail ──────────────────────────────────────────────────
WORKDIR /app

# Donne d'emblée la propriété de /app à appuser
RUN chown appuser:appuser /app

# ── Copie des fichiers de dépendances (avant le code source) ─────────────────
# Le glob uv.lock* permet de builder même sans lockfile committé,
# mais il est fortement recommandé de committer uv.lock pour des builds reproductibles.
COPY pyproject.toml uv.lock* ./
RUN chown -R appuser:appuser /app

# ── Installation des dépendances en tant qu'appuser ──────────────────────────
# uv sync crée un .venv dans /app/.venv, owned par appuser
USER appuser
RUN uv sync --frozen --no-dev

# ── Création des dossiers persistants ────────────────────────────────────────
# Ces dossiers seront montés comme PersistentVolumes en Kubernetes.
# On les crée ici pour garantir leur existence si aucun PVC n'est monté
# (ex: développement local sans volume).
RUN mkdir -p /app/data /app/static/videos

# ── Copie du code source ──────────────────────────────────────────────────────
# Après l'installation des dépendances pour maximiser l'utilisation du cache Docker.
COPY --chown=appuser:appuser main.py          ./
COPY --chown=appuser:appuser data/users.json  ./data/
COPY --chown=appuser:appuser static/          ./static/

# ── Configuration ─────────────────────────────────────────────────────────────
EXPOSE 8000

# Chemin de la base SQLite — peut être surchargé via variable d'environnement
# pour pointer vers un volume PVC monté sur un chemin différent.
ENV DB_PATH=/app/data/jukebox.db

# ── Commande de démarrage ────────────────────────────────────────────────────
# uv run utilise le .venv créé par uv sync
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
