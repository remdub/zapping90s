"""
Zapping Interactif 90s — Backend FastAPI
=========================================
Architecture :
  - Endpoints REST  : /api/quiz, /api/quiz/result, /api/play, /api/status, /api/reset, /api/categories
  - WebSocket       : /ws  (display + mobile se connectent ici)
  - Fichiers statiques : /static/*
  - Redirection     : / → /static/display.html
                      /mobile → static/mobile.html

Algorithme d'épuisement :
  Pour une catégorie donnée, tire au sort une vidéo non jouée (played=0).
  Si toutes les vidéos de la catégorie ont été jouées, les remet à 0
  puis refait le tirage (reset transparent pour l'utilisateur).

État serveur :
  Singleton en mémoire (ServerState). Nécessite replicas=1 en Kubernetes.
"""

import io
import json
import os
import random
import sqlite3
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import qrcode
import qrcode.image.svg

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# ── Chemins ───────────────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
VIDEOS_DIR = STATIC_DIR / "videos"
DATA_DIR   = BASE_DIR / "data"
DB_PATH    = Path(os.environ.get("DB_PATH", str(DATA_DIR / "zapping.db")))


# ── Banque de questions du quiz ───────────────────────────────────────────────
# Trois pools ; au moment de la requête, une question est tirée aléatoirement
# dans chaque pool. Chaque réponse pointe vers une catégorie vidéo.

QUIZ_POOLS: dict[str, list[dict]] = {
    "q1_vibes": [
        {
            "id": "q1_1",
            "question": "C'est vendredi soir en 1998, quel est ton plan ?",
            "answers": [
                {"text": "Louer un blockbuster en grosse VHS au vidéoclub.",              "category": "cinema"},
                {"text": "Zapper frénétiquement devant les Minikeums ou les Simpson.",    "category": "tv"},
                {"text": "Écouter le Hit des Clubs en boucle à la radio.",                "category": "musique"},
                {"text": "Nettoyer la boule de la souris pour une nuit sur Age of Empires.", "category": "geek"},
            ],
        },
        {
            "id": "q1_2",
            "question": "Samedi après-midi, tu as 500 Francs Belges en poche, tu files :",
            "answers": [
                {"text": "Acheter un magazine PC avec son CD-ROM de démos jouables.",     "category": "geek"},
                {"text": "Chez le disquaire pour acheter le single 'Freed From Desire'.", "category": "musique"},
                {"text": "Dans la friterie du coin en épluchant le journal du jour.",     "category": "actu"},
                {"text": "T'acheter le maillot fluo de ton équipe de foot préférée.",     "category": "sport"},
            ],
        },
        {
            "id": "q1_3",
            "question": "C'est ton anniversaire en 1996, le programme idéal :",
            "answers": [
                {"text": "Une boum avec stroboscope et le CD de Gala à fond.",            "category": "musique"},
                {"text": "Un marathon Star Wars au Kinepolis avec pop-corn géant.",       "category": "cinema"},
                {"text": "Une LAN party sur Duke Nukem 3D (et ses câbles BNC).",          "category": "geek"},
                {"text": "Regarder Fort Boyard en mangeant des chips Smiths Flippos.",    "category": "tv"},
            ],
        },
        {
            "id": "q1_4",
            "question": "Dans la cour de récré (ou à la machine à café), tu étais le boss en :",
            "answers": [
                {"text": "Débats passionnés sur le penalty non sifflé contre l'Allemagne.", "category": "sport"},
                {"text": "Récitation des répliques cultes des Visiteurs.",                "category": "cinema"},
                {"text": "Échanges clandestins de disquettes piratées.",                  "category": "geek"},
                {"text": "Chorégraphie parfaite sur la Macarena.",                        "category": "musique"},
            ],
        },
        {
            "id": "q1_5",
            "question": "Ta chambre d'ado était tapissée de posters de :",
            "answers": [
                {"text": "Héros grunge ou boys bands découpés dans le magazine Joepie.",  "category": "musique"},
                {"text": "Michael Jordan s'étirant le bras ou Jean-Michel Saive.",        "category": "sport"},
                {"text": "Pamela Anderson ou David Hasselhoff en maillot rouge.",         "category": "tv"},
                {"text": "Titre choc de journal télévisé collé au mur.",                  "category": "actu"},
            ],
        },
        {
            "id": "q1_6",
            "question": "Que faisais-tu principalement pendant l'été 98 ?",
            "answers": [
                {"text": "Chanter 'I Will Survive' avec du maquillage sur les joues.",   "category": "sport"},
                {"text": "Regarder les infos en boucle pour suivre le scandale Clinton.", "category": "actu"},
                {"text": "Jouer à Snake sur un Nokia 3210 indestructible.",               "category": "geek"},
                {"text": "Capter la chaîne cryptée avec une passoire le samedi soir.",   "category": "tv"},
            ],
        },
        {
            "id": "q1_7",
            "question": "Ton style vestimentaire de l'époque était dicté par :",
            "answers": [
                {"text": "Kurt Cobain (chemise à carreaux) ou les Spice Girls (Buffalos).", "category": "musique"},
                {"text": "Neo dans Matrix (lunettes noires et trench-coat).",             "category": "cinema"},
                {"text": "Les présentateurs météo ringards avec leurs vestes fluo.",      "category": "tv"},
                {"text": "Le survêtement peau de pêche (Tacchini ou Kappa).",             "category": "sport"},
            ],
        },
        {
            "id": "q1_8",
            "question": "Le dimanche soir, c'était l'angoisse de l'école, tu te consolais avec :",
            "answers": [
                {"text": "La Trilogie du Samedi ou le film du dimanche soir sur RTL.",    "category": "tv"},
                {"text": "Un résumé des matchs de foot du week-end.",                     "category": "sport"},
                {"text": "Une dernière connexion à Internet (avant de bloquer le téléphone).", "category": "geek"},
                {"text": "Le son de ta chaîne Hi-Fi programmée pour s'éteindre toute seule.", "category": "musique"},
            ],
        },
        {
            "id": "q1_9",
            "question": "Ta plus grosse dépense au début des années 90 ?",
            "answers": [
                {"text": "Un ordinateur multimédia 486 DX2 avec lecteur CD-ROM.",         "category": "geek"},
                {"text": "Une paire de Nike Air Max avec bulle d'air apparente.",         "category": "sport"},
                {"text": "Un discman anti-chocs qui sautait quand même.",                  "category": "musique"},
                {"text": "Une place pour voir Titanic au cinéma (3 fois de suite).",      "category": "cinema"},
            ],
        },
        {
            "id": "q1_10",
            "question": "Ta soirée télé idéale, c'était :",
            "answers": [
                {"text": "Un JT suivi d'une émission de Strip-Tease bien glauque.",       "category": "actu"},
                {"text": "Le Hit Machine avec Charly et Lulu.",                            "category": "musique"},
                {"text": "Le grand film d'action américain avec doublage VF excessif.",   "category": "cinema"},
                {"text": "Un zap sur MTV pour voir Beavis et Butt-Head.",                 "category": "tv"},
            ],
        },
    ],
    "q2_dramas": [
        {
            "id": "q2_1",
            "question": "Ton plus grand drame technologique de la décennie ?",
            "answers": [
                {"text": "Quelqu'un décroche le téléphone à 99% de ton téléchargement.", "category": "geek"},
                {"text": "La bande de la cassette s'emmêle dans l'autoradio.",            "category": "musique"},
                {"text": "Rater le début du JT et ne pas savoir s'il y a grève des bus.", "category": "actu"},
                {"text": "Quelqu'un a enregistré par-dessus l'épisode final de ta série.", "category": "tv"},
            ],
        },
        {
            "id": "q2_2",
            "question": "La phrase qui te faisait transpirer à l'époque :",
            "answers": [
                {"text": "« Veuillez insérer la disquette 14 sur 15 » (Erreur de lecture).", "category": "geek"},
                {"text": "« Soyez sympa, rembobinez » (Sinon le vidéoclub te donne une amende).", "category": "cinema"},
                {"text": "« Tu as pensé à nourrir ton Tamagotchi ? ».",                    "category": "tv"},
                {"text": "« Il n'y a plus de piles dans ton Walkman ».",                   "category": "musique"},
            ],
        },
        {
            "id": "q2_3",
            "question": "L'objet que tu as dû réparer en urgence façon MacGyver :",
            "answers": [
                {"text": "Souffler dans une cartouche de GameBoy qui freeze.",             "category": "geek"},
                {"text": "Rembobiner une cassette audio avec un crayon Bic.",              "category": "musique"},
                {"text": "Taper sur le flanc de la télé à tube cathodique pour retrouver l'image.", "category": "tv"},
                {"text": "Mettre du scotch sur la languette d'une VHS pour réenregistrer.", "category": "cinema"},
            ],
        },
        {
            "id": "q2_4",
            "question": "La rumeur qui t'a le plus fait paniquer :",
            "answers": [
                {"text": "Le Bug de l'an 2000 allait crasher tous les avions du monde.",  "category": "actu"},
                {"text": "Marilyn Manson s'est fait enlever une côte.",                    "category": "musique"},
                {"text": "Mew est caché sous le camion dans Pokémon Bleu.",                "category": "geek"},
                {"text": "Ne mangez pas ce poulet, c'est la crise de la dioxine !",       "category": "actu"},
            ],
        },
        {
            "id": "q2_5",
            "question": "La pire frustration de ton enfance / adolescence :",
            "answers": [
                {"text": "Ton équipe encaisse un but en or à la dernière minute.",        "category": "sport"},
                {"text": "Tu as loupé le flash info spécial à la radio.",                  "category": "actu"},
                {"text": "Internet facturé à la minute (ta mère hurle pour la facture).", "category": "geek"},
                {"text": "La pub qui coupe ton film juste au moment fatidique.",           "category": "tv"},
            ],
        },
        {
            "id": "q2_6",
            "question": "Le cauchemar absolu du dimanche matin :",
            "answers": [
                {"text": "Te lever à 6h pour un match dans le froid et la boue.",         "category": "sport"},
                {"text": "Devoir démêler les fils des manettes de console.",               "category": "geek"},
                {"text": "Ne plus avoir de place sur le CD vierge à graver.",              "category": "musique"},
                {"text": "Tomber sur une rediffusion politique interminable à la télé.",  "category": "actu"},
            ],
        },
        {
            "id": "q2_7",
            "question": "Le pire fashion faux-pas de la décennie selon toi ?",
            "answers": [
                {"text": "La coupe mulet de certains footballeurs belges.",                "category": "sport"},
                {"text": "Les lunettes noires minuscules à la Matrix.",                    "category": "cinema"},
                {"text": "Les pinces papillon et les mèches péroxydées.",                 "category": "musique"},
                {"text": "Les pulls bariolés des animateurs du Bigdil.",                   "category": "tv"},
            ],
        },
        {
            "id": "q2_8",
            "question": "L'endroit où tu as perdu le plus de temps :",
            "answers": [
                {"text": "Dans les rayons d'un vidéoclub sans savoir quoi choisir.",      "category": "cinema"},
                {"text": "Devant l'écran de chargement de Windows 95.",                   "category": "geek"},
                {"text": "À attendre qu'un clip passe ENFIN sur MTV pour l'enregistrer.", "category": "musique"},
                {"text": "À vérifier le télétexte page par page pour les résultats du foot.", "category": "sport"},
            ],
        },
        {
            "id": "q2_9",
            "question": "Ton drame social avant les réseaux sociaux :",
            "answers": [
                {"text": "Rater le journal télévisé et être le seul à ne pas connaître l'info.", "category": "actu"},
                {"text": "Ne pas avoir le bon pog pour jouer à la récré.",                 "category": "tv"},
                {"text": "Arriver le dernier pour prendre le joystick Player 1.",          "category": "geek"},
                {"text": "Spoilier la fin de Sixième Sens à tout le monde.",               "category": "cinema"},
            ],
        },
        {
            "id": "q2_10",
            "question": "Le pire supplice sonore des années 90 :",
            "answers": [
                {"text": "Le cri déchirant du modem 56k à la connexion.",                 "category": "geek"},
                {"text": "Une cassette audio lue à l'envers ou qui déraille.",            "category": "musique"},
                {"text": "Les vuvuzelas ou les cornes de brume dans le stade.",           "category": "sport"},
                {"text": "Le jingle d'Alerte Enlèvement ou du flash info.",               "category": "actu"},
            ],
        },
    ],
    "q3_pride": [
        {
            "id": "q3_1",
            "question": "La citation / l'image belge qui te donne des frissons :",
            "answers": [
                {"text": "L'attaque de Vandenbroucke à La Redoute en 99.",                "category": "sport"},
                {"text": "« Je crois aux forces de l'esprit » (ou les larmes du JT).",   "category": "actu"},
                {"text": "« Gamin ! Reviens gamin ! » (C'est arrivé près de chez vous).", "category": "cinema"},
                {"text": "« Contrat de confiance ! » (Vanden Borre).",                    "category": "tv"},
            ],
        },
        {
            "id": "q3_2",
            "question": "L'événement historique dont tu te souviendras toujours :",
            "answers": [
                {"text": "La finale de la Coupe du Monde 98 (Et un, et deux...).",        "category": "sport"},
                {"text": "L'annonce de la chute du mur ou la libération de Mandela au JT.", "category": "actu"},
                {"text": "Le clonage de la brebis Dolly (la science-fiction devient réalité).", "category": "geek"},
                {"text": "L'Oscar remporté par Titanic en direct à la télé.",             "category": "cinema"},
            ],
        },
        {
            "id": "q3_3",
            "question": "Ton \"Je me souviens exactement où j'étais quand...\" :",
            "answers": [
                {"text": "J'ai appris le décès du Roi Baudouin ou de Lady Di.",           "category": "actu"},
                {"text": "J'ai vu le T-Rex sortir de son enclos pour la première fois.",  "category": "cinema"},
                {"text": "J'ai entendu l'arbitre refuser le penalty contre l'Allemagne en 94.", "category": "sport"},
                {"text": "J'ai envoyé mon premier e-mail avec Netscape.",                  "category": "geek"},
            ],
        },
        {
            "id": "q3_4",
            "question": "L'invention des années 90 qui t'a le plus fasciné :",
            "answers": [
                {"text": "Les effets spéciaux numériques (Bullet Time dans Matrix).",     "category": "cinema"},
                {"text": "Le passage à la monnaie unique, l'Euro (sur papier du moins).", "category": "actu"},
                {"text": "Le téléphone portable GSM qui rentre (presque) dans la poche.", "category": "geek"},
                {"text": "La GameBoy Color (enfin de la couleur !).",                     "category": "geek"},
            ],
        },
        {
            "id": "q3_5",
            "question": "Le générique culte que tu connais encore par cœur :",
            "answers": [
                {"text": "Le Prince de Bel-Air (en VF évidemment).",                      "category": "tv"},
                {"text": "La musique d'entrée des Chicago Bulls.",                         "category": "sport"},
                {"text": "Le jingle d'ouverture de Windows 95 par Brian Eno.",            "category": "geek"},
                {"text": "Wannabe des Spice Girls (Dites moi ce que vous voulez !).",     "category": "musique"},
            ],
        },
        {
            "id": "q3_6",
            "question": "La personnalité francophone de la décennie :",
            "answers": [
                {"text": "Zinédine Zidane embrassant le trophée.",                        "category": "sport"},
                {"text": "Benoît Poelvoorde avec son pull marin.",                        "category": "cinema"},
                {"text": "Un présentateur star du JT (PPDA ou Georges Moucheron).",       "category": "actu"},
                {"text": "Jean-Michel Saive faisant le show au ping-pong.",               "category": "sport"},
            ],
        },
        {
            "id": "q3_7",
            "question": "Ce qui te manque le plus de cette époque :",
            "answers": [
                {"text": "Le suspense d'attendre une semaine pour le prochain épisode.",  "category": "tv"},
                {"text": "L'ambiance des magasins de disques pour dénicher un album.",    "category": "musique"},
                {"text": "Découvrir la 3D baveuse pour la première fois sur PlayStation.", "category": "geek"},
                {"text": "Aller dans une salle de cinéma remplie sans téléphones allumés.", "category": "cinema"},
            ],
        },
        {
            "id": "q3_8",
            "question": "L'image choc de la télé des 90s pour toi, c'est :",
            "answers": [
                {"text": "La course-poursuite du Ford Bronco de O.J. Simpson.",           "category": "actu"},
                {"text": "L'oreille arrachée par Mike Tyson en plein combat.",            "category": "sport"},
                {"text": "Le générique flippant de X-Files tard le soir.",                "category": "tv"},
                {"text": "Le clip sulfureux de Mylène Farmer ou Madonna.",                "category": "musique"},
            ],
        },
        {
            "id": "q3_9",
            "question": "Le \"Hacker\" ultime de l'époque selon toi :",
            "answers": [
                {"text": "Neo qui découvre que son monde n'est que du code vert.",        "category": "cinema"},
                {"text": "Toi, en train de graver des CD pour tes potes.",                "category": "geek"},
                {"text": "Jean-Marc Bosman, qui a mis le système du foot à genoux.",      "category": "sport"},
                {"text": "Les Daft Punk qui se cachent derrière leurs casques.",          "category": "musique"},
            ],
        },
        {
            "id": "q3_10",
            "question": "Le cri de ralliement qui marchera toujours avec toi :",
            "answers": [
                {"text": "« Wasssssuuuup ! » (Pub Budweiser).",                           "category": "tv"},
                {"text": "« Wololo ! » (Age of Empires).",                                "category": "geek"},
                {"text": "« I'm the king of the world ! » (Titanic).",                   "category": "cinema"},
                {"text": "« Et le but de Philippe Albert ! » (RTBF 1994).",               "category": "sport"},
            ],
        },
    ],
}


# ── Base de données ───────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    """Retourne une connexion SQLite avec row_factory activé."""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def startup_init_db() -> None:
    """
    Initialisation au démarrage :
      1. Crée le dossier data/ et la table videos si inexistants.
      2. Scanne static/videos/ et insère les .mp4 manquants (INSERT OR IGNORE).
      3. Supprime les entrées DB dont le fichier n'existe plus sur disque.

    Convention nommage : {categorie}__{titre}.mp4
    La catégorie est extraite du préfixe avant __ ; "unknown" en cas d'absence.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT    NOT NULL UNIQUE,
                category TEXT    NOT NULL,
                played   INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Fichiers présents sur disque
        on_disk = {mp4.name for mp4 in VIDEOS_DIR.glob("*.mp4")}

        # Insère les nouveaux fichiers
        for filename in on_disk:
            stem     = Path(filename).stem
            category = stem.split("__")[0] if "__" in stem else "unknown"
            conn.execute(
                "INSERT OR IGNORE INTO videos (filename, category) VALUES (?, ?)",
                (filename, category),
            )

        # Supprime les entrées dont le fichier a disparu ou a été renommé
        in_db = {row[0] for row in conn.execute("SELECT filename FROM videos").fetchall()}
        orphans = in_db - on_disk
        if orphans:
            conn.executemany(
                "DELETE FROM videos WHERE filename = ?",
                [(f,) for f in orphans],
            )

        conn.commit()
    finally:
        conn.close()


# ── Helpers vidéo ─────────────────────────────────────────────────────────────

def _filename_to_title(filename: str) -> str:
    """'cinema__mon_film.mp4' → 'Mon Film'"""
    stem = Path(filename).stem
    part = stem.split("__", 1)[1] if "__" in stem else stem
    return part.replace("_", " ").strip().title()


# ── Algorithme d'épuisement ───────────────────────────────────────────────────

def pick_video(category: str) -> dict | None:
    """
    Tire au sort une vidéo non jouée pour la catégorie donnée et la marque jouée.

    Returns:
        dict {"id", "filename", "category"} ou None si aucune vidéo disponible.
    """
    conn = get_conn()
    try:
        for attempt in range(2):
            rows = conn.execute(
                "SELECT id, filename, category FROM videos WHERE category = ? AND played = 0",
                (category,),
            ).fetchall()

            if rows:
                chosen = random.choice(rows)
                conn.execute("UPDATE videos SET played = 1 WHERE id = ?", (chosen["id"],))
                conn.commit()
                return dict(chosen)

            if attempt == 0:
                conn.execute(
                    "UPDATE videos SET played = 0 WHERE category = ?",
                    (category,),
                )
                conn.commit()

        return None
    finally:
        conn.close()


def pick_video_choices(category: str, n: int = 3) -> list[dict]:
    """
    Retourne n vidéos aléatoires non jouées SANS les marquer comme jouées.
    Utilisé pour proposer des choix à l'utilisateur avant qu'il sélectionne.
    Si moins de n disponibles, remet la catégorie à zéro et réessaie.

    Returns:
        list de {"filename", "title"}
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT filename FROM videos WHERE category = ? AND played = 0 ORDER BY RANDOM() LIMIT ?",
            (category, n),
        ).fetchall()

        if len(rows) < n:
            conn.execute("UPDATE videos SET played = 0 WHERE category = ?", (category,))
            conn.commit()
            rows = conn.execute(
                "SELECT filename FROM videos WHERE category = ? ORDER BY RANDOM() LIMIT ?",
                (category, n),
            ).fetchall()

        return [{"filename": r["filename"], "title": _filename_to_title(r["filename"])} for r in rows]
    finally:
        conn.close()


# ── Gestionnaire WebSocket ─────────────────────────────────────────────────────

class ConnectionManager:
    """Gère l'ensemble des connexions WebSocket actives."""

    def __init__(self) -> None:
        self._active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        """Envoie payload (JSON) à tous les clients connectés."""
        dead: set[WebSocket] = set()
        for ws in self._active.copy():
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._active -= dead


manager = ConnectionManager()


# ── État serveur ──────────────────────────────────────────────────────────────

@dataclass
class ServerState:
    """État global de l'application (singleton, in-process).
    ⚠️  Nécessite replicas: 1 en Kubernetes."""
    status:           Literal["IDLE", "PLAYING"] = "IDLE"
    current_user:     str | None = None
    current_video:    str | None = None
    current_category: str | None = None
    video_queue:      list[str] = field(default_factory=list)


state = ServerState()


# ── Application FastAPI ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise la DB au démarrage, libère les ressources à l'arrêt."""
    startup_init_db()
    yield


app = FastAPI(
    title="Zapping 90s",
    description="Zapping interactif pour teambuilding",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Modèles Pydantic ──────────────────────────────────────────────────────────

class QuizResultRequest(BaseModel):
    name:    str
    answers: list[str]   # 3 valeurs de category (ex: ["cinema", "geek", "cinema"])


class PlayRequest(BaseModel):
    name:     str
    category: str
    video:    str        # filename sélectionné par l'utilisateur


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/static/display.html")


@app.get("/mobile", include_in_schema=False)
async def mobile() -> FileResponse:
    return FileResponse(STATIC_DIR / "mobile.html")


@app.get("/api/quiz", summary="Questions du quiz")
async def api_quiz() -> dict:
    """
    Retourne 3 questions aléatoires (une par pool).
    L'ordre des pools est toujours q1_vibes → q2_dramas → q3_pride.
    """
    questions = [random.choice(pool) for pool in QUIZ_POOLS.values()]
    return {"questions": questions}


@app.post("/api/quiz/result", summary="Résultat du quiz → catégorie + choix vidéos")
async def api_quiz_result(req: QuizResultRequest) -> dict:
    """
    Calcule la catégorie gagnante (majorité des réponses ; première réponse
    en cas d'égalité) et propose jusqu'à 3 vidéos de cette catégorie.

    Returns:
        {"category": "...", "label": "...", "videos": [{"filename", "title"}, ...]}
    Raises:
        404 si aucune vidéo disponible pour la catégorie gagnante.
        422 si answers ne contient pas exactement 3 éléments.
    """
    if len(req.answers) != 3:
        raise HTTPException(status_code=422, detail="Le quiz doit contenir exactement 3 réponses.")

    counts   = Counter(req.answers)
    category = max(req.answers, key=lambda a: counts[a])   # 1ère occurrence gagne les égalités
    videos   = pick_video_choices(category, 3)

    if not videos:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune vidéo disponible pour la catégorie '{category}'.",
        )

    label = category.replace("_", " ").strip().upper()
    return {"category": category, "label": label, "videos": videos}


@app.get("/api/categories", summary="Catégories disponibles (pour le slot machine)")
async def api_categories() -> list[str]:
    """
    Retourne la liste des catégories présentes dans la DB,
    en excluant les catégories système ('pub', 'unknown').
    Utilisé par display.js pour alimenter le slot machine REVEAL.
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT category FROM videos "
            "WHERE category NOT IN ('pub', 'unknown') ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]
    finally:
        conn.close()


@app.get("/api/status", summary="État courant du serveur")
async def api_status() -> dict:
    """Retourne l'état courant. Utilisé aussi comme healthcheck Kubernetes."""
    return {
        "status":   state.status,
        "user":     state.current_user,
        "video":    state.current_video,
        "category": state.current_category,
    }


@app.post("/api/play", summary="Déclenche la lecture de la vidéo sélectionnée")
async def api_play(req: PlayRequest) -> dict:
    """
    Logique principale :
      1. Refuse (409) si une lecture est déjà en cours.
      2. Vérifie que la vidéo existe en base et la marque comme jouée.
      3. Construit la file pub + vidéo principale.
      4. Met à jour l'état serveur et diffuse l'événement via WebSocket.

    Returns:
        {"status": "ok", "video": "...", "category": "..."}
    Raises:
        404 si la vidéo est introuvable en base.
        409 si une vidéo est déjà en cours de lecture.
    """
    if state.status == "PLAYING":
        raise HTTPException(status_code=409, detail="Une vidéo est déjà en cours de lecture.")

    # Marque la vidéo choisie comme jouée
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM videos WHERE filename = ?", (req.video,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Vidéo '{req.video}' introuvable.")
        conn.execute("UPDATE videos SET played = 1 WHERE id = ?", (row["id"],))
        conn.commit()
    finally:
        conn.close()

    # ── Construction de la file complète ─────────────────────────────────────
    pub_before = pick_video("pub")
    pub_after  = pick_video("pub")

    queue: list[str] = []
    queue.append("pub-intro.mp4")
    if pub_before:
        queue.append(pub_before["filename"])
    queue.append("pub-fermeture.mp4")
    queue.append(req.video)
    queue.append("pub-intro.mp4")
    if pub_after:
        queue.append(pub_after["filename"])
    queue.append("pub-fermeture.mp4")

    state.status           = "PLAYING"
    state.current_user     = req.name
    state.current_video    = queue[0]
    state.current_category = req.category
    state.video_queue      = queue[1:]

    await manager.broadcast({
        "type":     "play",
        "user":     req.name,
        "category": req.category,
        "video":    queue[0],
    })

    return {"status": "ok", "video": req.video, "category": req.category}


@app.post("/api/reset", summary="Réinitialisation d'urgence (admin)")
async def api_reset() -> dict:
    """Remet le serveur en état IDLE et diffuse l'événement aux clients."""
    state.status           = "IDLE"
    state.current_user     = None
    state.current_video    = None
    state.current_category = None
    state.video_queue      = []

    await manager.broadcast({"type": "idle"})

    return {"status": "reset"}


# ── QR Code ──────────────────────────────────────────────────────────────────

@app.get("/api/qrcode", summary="QR code SVG vers /mobile", include_in_schema=False)
async def api_qrcode(request: Request) -> Response:
    """Génère un QR code SVG pointant vers /mobile, colorisé en vert 90s."""
    mobile_url = str(request.base_url).rstrip("/") + "/mobile"

    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(mobile_url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathFillImage)

    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode("utf-8")

    svg = svg.replace('fill="#000000"', 'fill="#00ff00"')
    svg = svg.replace("fill='#000000'", "fill='#00ff00'")
    svg = svg.replace("<svg ", '<svg style="background:#000000;display:block;" ', 1)

    return Response(content=svg, media_type="image/svg+xml")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """
    Point d'entrée WebSocket commun à l'écran géant et aux mobiles.

    Messages reçus du client :
      {"type": "video_ended"}  → dépile la file ou retourne en IDLE

    Messages envoyés par le serveur (via broadcast) :
      {"type": "play", "user": "...", "category": "...", "video": "..."}
      {"type": "next_video", "video": "..."}
      {"type": "idle"}
    """
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "video_ended":
                if state.video_queue:
                    next_video          = state.video_queue.pop(0)
                    state.current_video = next_video
                    await manager.broadcast({"type": "next_video", "video": next_video})
                else:
                    state.status           = "IDLE"
                    state.current_user     = None
                    state.current_video    = None
                    state.current_category = None
                    state.video_queue      = []
                    await manager.broadcast({"type": "idle"})
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ── Fichiers statiques ────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
