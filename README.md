# Zapping 90s

Application de teambuilding interactive sur le thème des années 90.

Chaque participant répond à un quiz de 3 questions nostalgiques sur son smartphone. Ses réponses déterminent une catégorie (cinéma, musique, geek, sport…), puis il choisit une vidéo parmi 3 suggestions. La vidéo est lancée sur un grand écran commun, encadrée de coupures pub rétro.

## Prérequis

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- ffmpeg (uniquement pour `scripts/normalize_videos.py`)

## Démarrage rapide

```bash
uv sync
uv run uvicorn main:app --reload
```

Ouvrir `http://localhost:8000` sur l'écran géant, puis `http://localhost:8000/mobile` sur les smartphones (ou scanner le QR code affiché à l'écran).

## Ajouter des vidéos

Les fichiers `.mp4` doivent être placés dans `static/videos/` en respectant la convention de nommage :

```
{categorie}__{titre}.mp4
```

Exemples : `cinema__Pulp_Fiction_bande_annonce.mp4`, `geek__Windows_95_startup.mp4`

Catégories reconnues par le quiz : `actu`, `cinema`, `geek`, `musique`, `pub`, `sport`, `tv`.

Les fichiers `pub-intro.mp4` et `pub-fermeture.mp4` sont des vidéos système (jingles encadrant chaque séquence) — ils ne sont pas catégorisés.

La base de données est mise à jour automatiquement au démarrage de l'application. Pour forcer une mise à jour manuelle ou remettre toutes les vidéos à « non jouées » :

```bash
python data/init_db.py
python data/init_db.py --reset
```

Pour normaliser le volume audio de toutes les vidéos (EBU R128, -23 LUFS) :

```bash
python scripts/normalize_videos.py
```

## Docker

```bash
docker build -t zapping90s .
docker run -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/static/videos:/app/static/videos \
  zapping90s
```

## Kubernetes

Le manifeste `k8s-deployment.yaml` crée un namespace `zapping` avec deux PersistentVolumeClaims (base de données et vidéos) et un Deployment.

```bash
kubectl apply -f k8s-deployment.yaml
kubectl rollout status deployment/zapping -n zapping
```

Copier les vidéos sur le PVC une fois le pod démarré :

```bash
kubectl cp video.mp4 zapping/<pod-name>:/app/static/videos/
kubectl rollout restart deployment/zapping -n zapping
```

> **Important** : le déploiement doit rester à `replicas: 1`. L'état de lecture est stocké en mémoire dans le processus ; plusieurs réplicas provoqueraient des états incohérents.

## API

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/api/quiz` | 3 questions aléatoires (une par pool) |
| `POST` | `/api/quiz/result` | Catégorie gagnante + 3 suggestions vidéo |
| `POST` | `/api/play` | Lance la séquence vidéo sur l'écran géant |
| `GET` | `/api/status` | État courant (aussi utilisé comme healthcheck) |
| `POST` | `/api/reset` | Réinitialisation d'urgence |
| `GET` | `/api/categories` | Liste des catégories disponibles |
| `GET` | `/api/qrcode` | QR code SVG vers `/mobile` |

La documentation interactive est disponible sur `http://localhost:8000/docs`.
