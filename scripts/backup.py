"""Backup diário do banco SQLite, para rodar no serviço `backup` do Docker Compose.

Faz uma cópia ao iniciar e outra por dia no horário BACKUP_HOUR_UTC, usando a API de
backup do SQLite (cópia consistente mesmo com o app gravando). Cada cópia é conferida
com `PRAGMA integrity_check`, comprimida e guardada em BACKUP_DIR como
`livros-AAAA-MM-DD-HHMMSS.db.gz` (data em UTC). Ficam as BACKUP_KEEP mais recentes.

Os arquivos contêm dados pessoais: são criados só com permissão do dono (umask 077).

Uso manual: python scripts/backup.py --once
"""

import datetime as dt
import gzip
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "/data/livros.db"))
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))
BACKUP_HOUR_UTC = int(os.environ.get("BACKUP_HOUR_UTC", "6"))
BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "14"))
RETRY_SECONDS = 10 * 60
RETRIES = 3
PREFIX = "livros-"
SUFFIX = ".db.gz"


def log(message: str) -> None:
    print(f"[backup] {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M:%S}Z {message}", flush=True)


def backup_once() -> Path:
    """Cria, confere e comprime uma cópia do banco. Devolve o arquivo criado."""
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(f"banco não encontrado em {DATABASE_PATH}")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    final = BACKUP_DIR / f"{PREFIX}{stamp}{SUFFIX}"
    raw = BACKUP_DIR / f".{PREFIX}{stamp}.db.tmp"
    packed = BACKUP_DIR / f".{PREFIX}{stamp}{SUFFIX}.tmp"
    try:
        source = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True, timeout=30)
        destination = sqlite3.connect(raw)
        try:
            source.backup(destination)
            result = destination.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"cópia com problema: {result}")
        finally:
            destination.close()
            source.close()
        with open(raw, "rb") as plain, gzip.open(packed, "wb") as compressed:
            shutil.copyfileobj(plain, compressed)
        packed.replace(final)
        return final
    finally:
        raw.unlink(missing_ok=True)
        packed.unlink(missing_ok=True)


def prune() -> list[Path]:
    """Apaga as cópias mais antigas, deixando as BACKUP_KEEP mais recentes."""
    backups = sorted(BACKUP_DIR.glob(f"{PREFIX}*{SUFFIX}"))
    old = backups[:-BACKUP_KEEP] if BACKUP_KEEP > 0 else []
    for path in old:
        path.unlink(missing_ok=True)
    return old


def run() -> bool:
    for attempt in range(1, RETRIES + 1):
        try:
            created = backup_once()
            removed = prune()
            log(f"cópia criada: {created.name} ({created.stat().st_size} bytes); apagadas: {len(removed)}")
            return True
        except Exception as error:  # noqa: BLE001 - qualquer falha vira log e nova tentativa
            log(f"falha na tentativa {attempt}/{RETRIES}: {error}")
            if attempt < RETRIES:
                time.sleep(RETRY_SECONDS)
    return False


def seconds_until_next(now: dt.datetime) -> float:
    target = now.replace(hour=BACKUP_HOUR_UTC, minute=0, second=0, microsecond=0)
    if target <= now:
        target += dt.timedelta(days=1)
    return (target - now).total_seconds()


def main() -> int:
    os.umask(0o077)
    if "--once" in sys.argv:
        return 0 if run() else 1
    log(f"iniciado: todo dia às {BACKUP_HOUR_UTC:02d}:00 UTC, guardando {BACKUP_KEEP} cópias em {BACKUP_DIR}")
    run()
    while True:
        time.sleep(seconds_until_next(dt.datetime.now(dt.timezone.utc)))
        run()


if __name__ == "__main__":
    sys.exit(main())
