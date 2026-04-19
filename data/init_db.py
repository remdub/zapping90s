#!/usr/bin/env python3
"""
Script d'initialisation manuelle de la base de données SQLite.

Utilisation :
    python data/init_db.py

Ce script peut être relancé sans risque : INSERT OR IGNORE évite les doublons.
Pour forcer un reset complet (remettre toutes les vidéos à played=0) :
    python data/init_db.py --reset

Variables d'environnement :
    DB_PATH     Chemin vers le fichier SQLite (défaut : data/jukebox.db)
    VIDEOS_DIR  Dossier contenant les fichiers .mp4 (défaut : static/videos)

Convention de nommage des vidéos :
    {categorie}__{titre}.mp4
    Exemples : pop_90s__spice_girls_wannabe.mp4
               geek_pc__windows_95_startup.mp4
               rnb_90s__mariah_carey_hero.mp4
               techno__daft_punk_around_the_world.mp4
"""
import argparse
import os
import sqlite3
from pathlib import Path


# ── Chemins par défaut (relatifs à la racine du projet) ──────────────────────
ROOT_DIR   = Path(__file__).parent.parent
DB_PATH    = Path(os.environ.get("DB_PATH",    str(ROOT_DIR / "data" / "jukebox.db")))
VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", str(ROOT_DIR / "static" / "videos")))


def derive_category(filename: str) -> str:
    """Extrait la catégorie depuis le nom de fichier via la convention __ ."""
    stem = Path(filename).stem  # supprime l'extension
    if "__" in stem:
        return stem.split("__")[0]
    return "unknown"


def init_db(reset: bool = False) -> None:
    """
    Initialise la base de données et scanne le dossier vidéos.

    Args:
        reset: Si True, remet toutes les vidéos à played=0.
    """
    # Crée le dossier parent si nécessaire (premier démarrage sur PVC vide)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # Création de la table (idempotente)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT    NOT NULL UNIQUE,
                category TEXT    NOT NULL,
                played   INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Reset optionnel
        if reset:
            conn.execute("UPDATE videos SET played = 0")
            print("[RESET] Toutes les vidéos remises à played=0.")

        # Scan du dossier vidéos
        inserted = 0
        if VIDEOS_DIR.is_dir():
            for mp4 in sorted(VIDEOS_DIR.glob("*.mp4")):
                category = derive_category(mp4.name)
                conn.execute(
                    "INSERT OR IGNORE INTO videos (filename, category) VALUES (?, ?)",
                    (mp4.name, category),
                )
                inserted += conn.execute(
                    "SELECT changes()"
                ).fetchone()[0]
        else:
            print(f"[AVERTISSEMENT] Dossier vidéos introuvable : {VIDEOS_DIR}")

        conn.commit()

        # Résumé
        total   = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        unplayed = conn.execute("SELECT COUNT(*) FROM videos WHERE played=0").fetchone()[0]
        print(f"[OK] Base initialisée : {DB_PATH}")
        print(f"     {inserted} nouvelle(s) vidéo(s) ajoutée(s)")
        print(f"     {total} vidéo(s) au total — {unplayed} non jouée(s)")

        # Affiche la répartition par catégorie
        rows = conn.execute(
            "SELECT category, COUNT(*) as n, SUM(played) as p FROM videos GROUP BY category ORDER BY category"
        ).fetchall()
        if rows:
            print("\n  Catégorie            Total  Jouées")
            print("  " + "-" * 36)
            for r in rows:
                print(f"  {r['category']:<20} {r['n']:>5}  {r['p']:>6}")

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialise la base jukebox.db")
    parser.add_argument(
        "--reset", action="store_true",
        help="Remet toutes les vidéos à played=0 avant de scanner"
    )
    args = parser.parse_args()
    init_db(reset=args.reset)
