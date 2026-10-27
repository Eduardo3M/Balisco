"""
Balisco Companion Engine (companion.py)
--------------------------------------
Motor de autonomía, memoria estocástica y estados emocionales para el Companion.
Base de datos: companion.db (completamente separada de biblioteca.db).
"""

import sqlite3
import random
import json
from pathlib import Path
from datetime import datetime

from .database import DATA_DIR

DB_PATH = DATA_DIR / "companion.db"

def init_companion_db(db_path=None):
    """Inicializa las tablas de memoria, estado y bitácora episódica."""
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        # Estado psicológico actual (tolerancia dinámica, inercia, humor)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companion_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                tolerancia REAL DEFAULT 0.75,          -- Nivel de paciencia actual (0.0 a 1.0)
                energia REAL DEFAULT 0.85,             -- Nivel de energía para tareas (0.0 a 1.0)
                humor TEXT DEFAULT 'curioso',           -- 'sarcasmo', 'curioso', 'dormida', 'fastidiada', 'lectura'
                racha_ordenes INTEGER DEFAULT 0,       -- Cuántas órdenes consecutivas ha recibido
                ultimo_sprite TEXT DEFAULT 'sitting_reading.png',
                ultimo_contacto TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Insertar estado por defecto si no existe
        conn.execute("INSERT OR IGNORE INTO companion_state (id) VALUES (1)")

        # Memoria episódica a largo plazo (juicios, momentos memorables)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memoria_episodica (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                categoria TEXT,                        -- 'habito_usuario', 'libro_comentado', 'desacuerdo'
                clave TEXT,
                contenido TEXT,
                impacto_emocional REAL DEFAULT 0.0     -- -1.0 a 1.0
            )
        """)

        # Historial de chat / interacciones recientes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historial_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                emisor TEXT,                           -- 'usuario' o 'companion'
                mensaje TEXT,
                sprite_usado TEXT,
                humor_momento TEXT
            )
        """)
    conn.close()

class CompanionEngine:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path or DB_PATH)
        init_companion_db(self.db_path)

    def get_state(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM companion_state WHERE id = 1").fetchone()
        conn.close()
        return dict(row) if row else {}

    def update_interaction(self, tipo="charla"):
        """
        Modela la tolerancia psicológica estocástica:
        - Si el usuario le pide muchas cosas seguidas, la tolerancia baja.
        - Hay un factor de aleatoriedad para evitar números rígidos.
        """
        conn = sqlite3.connect(self.db_path)
        state = self.get_state()
        racha = state.get("racha_ordenes", 0) + 1
        tolerancia = state.get("tolerancia", 0.75)
        energia = state.get("energia", 0.85)

        # Factor estocástico no lineal
        degradacion = random.uniform(0.04, 0.12)
        nueva_tolerancia = max(0.05, tolerancia - degradacion)
        nueva_energia = max(0.1, energia - random.uniform(0.02, 0.08))

        # Determinar humor emergente según umbrales estocásticos
        if nueva_tolerancia < 0.25:
            humor = "fastidiada"
            sprite = "emote_annoyed.png"
        elif nueva_tolerancia < 0.50 and random.random() < 0.4:
            humor = "sarcasmo"
            sprite = "emote_smirk.png"
        elif nueva_energia < 0.3:
            humor = "lectura"
            sprite = "sitting_reading.png"
        else:
            humor = "curioso"
            sprite = "idle_standing.png"

        with conn:
            conn.execute("""
                UPDATE companion_state
                SET tolerancia = ?, energia = ?, humor = ?, racha_ordenes = ?, ultimo_sprite = ?, ultimo_contacto = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (nueva_tolerancia, nueva_energia, humor, racha, sprite))

        conn.close()
        return {
            "tolerancia": round(nueva_tolerancia, 2),
            "energia": round(nueva_energia, 2),
            "humor": humor,
            "sprite": sprite,
            "racha": racha
        }

    def registrar_mensaje(self, emisor, texto, sprite=None, humor=None):
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("""
                INSERT INTO historial_chat (emisor, mensaje, sprite_usado, humor_momento)
                VALUES (?, ?, ?, ?)
            """, (emisor, texto, sprite, humor))
        conn.close()

    def descansar(self):
        """Restaura la paciencia cuando pasa el tiempo sin atosigarla."""
        conn = sqlite3.connect(self.db_path)
        with conn:
            conn.execute("""
                UPDATE companion_state
                SET tolerancia = MIN(1.0, tolerancia + 0.35),
                    energia = MIN(1.0, energia + 0.40),
                    racha_ordenes = 0,
                    humor = 'curioso',
                    ultimo_sprite = 'sitting_reading.png'
                WHERE id = 1
            """)
        conn.close()

if __name__ == "__main__":
    engine = CompanionEngine()
    print("Estado inicial:", engine.get_state())
    res = engine.update_interaction()
    print("Tras interacción:", res)
