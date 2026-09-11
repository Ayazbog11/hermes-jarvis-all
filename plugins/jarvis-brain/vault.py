"""
JARVIS Vault — хранилище файлов и проектов пользователя с полнотекстовым индексом.

Идея: одна папка (по умолчанию ~/JARVIS), куда пользователь просто кладёт что угодно — документы, заметки,
целые проекты — или подключает существующие папки (`jarvis vault add ~/Projects/foo` → символическая ссылка
в ~/JARVIS/projects/foo). JARVIS:
  * индексирует текстовое содержимое (md/txt/код/csv/json/yaml/html, PDF через pdftotext, docx/rtf/pages через textutil)
    в ту же базу brain.db (таблицы files + files_fts) — поиск по смыслу слов, а не по имени файла;
  * подмешивает релевантные файлы в контекст каждого хода (см. __init__.build_memory_context);
  * имеет к файлам полный доступ: чтение через vault_read (в т.ч. PDF/DOCX), запись/выполнение — штатными
    инструментами Hermes (write_file, terminal, …), пути ему известны из поиска.

Безопасность: не индексируем секреты (.env, ключи, сертификаты), служебные каталоги (node_modules, .git, venv…)
и бинарники; из текста вырезаются похожие на пароли/токены фрагменты (db.redact). Файлы > MAX_FILE_BYTES пропускаются.

Модуль работает и как библиотека (из плагина), и как скрипт:  python3 vault.py [status|reindex|list|search|add|remove|tree]
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    from . import embeddings as emb
    from .db import Brain, redact  # внутри плагина
except ImportError:  # запуск как скрипт: python3 vault.py …
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import embeddings as emb  # type: ignore
    from db import Brain, redact  # type: ignore

# На Windows stdout/stderr при перенаправлении в файл/пайп (не TTY) используют системную
# кодировку консоли (обычно cp1252), а не UTF-8 — любой print() с кириллицей тогда падает
# с UnicodeEncodeError вместо того, чтобы просто напечататься. На Linux/macOS это не нужно
# (там локаль почти всегда UTF-8), поэтому ограничиваемся Windows.
if sys.platform == "win32":  # pragma: no cover — покрыто CI на windows-latest
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

TEXT_EXT = {
    ".md", ".markdown", ".txt", ".text", ".rst", ".org", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".scss", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".py",
    ".rb", ".go", ".rs", ".java", ".kt", ".swift", ".m", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".sh", ".zsh",
    ".bash", ".fish", ".sql", ".r", ".jl", ".lua", ".pl", ".ps1", ".bat", ".dockerfile", ".env.example", ".log",
    ".tex", ".bib", ".srt", ".vtt", ".ics", ".vcf", ".plist", ".gradle", ".make", ".mk", ".cmake", ".proto", ".graphql",
}
CONVERT_EXT = {".pdf": "pdftotext", ".docx": "textutil", ".doc": "textutil", ".rtf": "textutil", ".rtfd": "textutil",
               ".odt": "textutil", ".pages": "textutil", ".webarchive": "textutil", ".pptx": "zip-xml", ".xlsx": "zip-xml"}
SPECIAL_NAMES = {"Makefile", "Dockerfile", "README", "LICENSE", "CHANGELOG", "TODO", "NOTES", "Procfile", "Gemfile", "Rakefile"}
SKIP_DIRS = {"node_modules", ".git", ".hg", ".svn", "venv", ".venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache",
             ".ruff_cache", "dist", "build", "target", ".next", ".nuxt", ".cache", ".idea", ".vscode", "Pods", "DerivedData",
             ".DS_Store", ".Trash", "coverage", ".tox", ".gradle", "vendor", "bower_components"}
SKIP_NAME_RE = re.compile(r"(^\.env($|\.)|\.pem$|\.key$|\.p12$|\.pfx$|\.keystore$|^id_(rsa|ed25519|ecdsa)|\.crt$|\.der$|"
                          r"credentials|secrets?\.(json|ya?ml|toml)$|\.sqlite3?$|\.db$|\.lock$|-lock\.json$|\.min\.(js|css)$|\.map$)",
                          re.I)
MAX_FILE_BYTES = 5 * 1024 * 1024
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_FILE = 400
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
    id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, rel TEXT NOT NULL, name TEXT NOT NULL, ext TEXT DEFAULT '',
    source TEXT DEFAULT 'vault', size INTEGER DEFAULT 0, mtime REAL DEFAULT 0, sha1 TEXT DEFAULT '',
    chunks INTEGER DEFAULT 0, chars INTEGER DEFAULT 0, kind TEXT DEFAULT 'text', status TEXT DEFAULT 'ok',
    note TEXT DEFAULT '', summary TEXT DEFAULT '', indexed_at TEXT, seen_at TEXT,
    summarized_at TEXT, summary_note INTEGER);
CREATE INDEX IF NOT EXISTS files_rel ON files(rel);
CREATE TABLE IF NOT EXISTS file_chunks(
    id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL, no INTEGER NOT NULL, line_from INTEGER DEFAULT 1, content TEXT NOT NULL,
    name TEXT DEFAULT '', rel TEXT DEFAULT '');   -- name/rel дублируются: внешняя content-таблица FTS5 требует те же колонки
CREATE INDEX IF NOT EXISTS file_chunks_file ON file_chunks(file_id);
CREATE TABLE IF NOT EXISTS vault_sources(
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, path TEXT NOT NULL, added_at TEXT, note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS file_embeddings(
    chunk_id INTEGER PRIMARY KEY, model TEXT NOT NULL, vector BLOB NOT NULL, created_at TEXT);
CREATE TRIGGER IF NOT EXISTS file_chunks_embed_cleanup AFTER DELETE ON file_chunks BEGIN
    DELETE FROM file_embeddings WHERE chunk_id = old.id; END;
"""
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    content, name, rel, content='file_chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS file_chunks_ai AFTER INSERT ON file_chunks BEGIN
    INSERT INTO files_fts(rowid, content, name, rel) VALUES (new.id, new.content, new.name, new.rel); END;
CREATE TRIGGER IF NOT EXISTS file_chunks_ad AFTER DELETE ON file_chunks BEGIN
    INSERT INTO files_fts(files_fts, rowid, content, name, rel) VALUES ('delete', old.id, old.content, old.name, old.rel); END;
"""

README_TEXT = """# JARVIS Vault — ваше хранилище

Кладите сюда **что угодно**: документы, заметки, PDF, таблицы, целые проекты. JARVIS индексирует содержимое
(не только имена файлов) и использует его в разговоре: «что написано в договоре с Acme?», «найди в моих заметках
про отпуск», «в проекте foo — где обрабатывается логин?».

* `projects/` — сюда `jarvis vault add ~/Projects/foo` добавляет ссылки на существующие папки (сами файлы не копируются).
* `inbox/` — быстрый сброс: всё, что нужно «показать Джарвису».
* Остальную структуру придумывайте сами — папки, подпапки, любые имена.

Что НЕ индексируется: `.env`, ключи и сертификаты, `node_modules`, `.git`, `venv`, бинарники, файлы больше 5 МБ.
Индекс обновляется автоматически (каждые несколько минут и при старте) или вручную: `jarvis vault reindex`.
Поиск из терминала: `jarvis vault search "слова"`. Статус: `jarvis vault status`.
"""


def now() -> str:
    return dt.datetime.now().replace(microsecond=0).isoformat()


def default_vault_dir() -> Path:
    return Path(os.environ.get("JARVIS_VAULT_DIR") or "~/JARVIS").expanduser()


def _which(name: str) -> str | None:
    return shutil.which(name) or next((p for p in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}")
                                       if os.path.exists(p)), None)


# ──────────────────────────── извлечение текста ────────────────────────────

def file_kind(path: Path) -> str | None:
    """'text' | 'convert' | None (не индексируем)."""
    name = path.name
    if SKIP_NAME_RE.search(name):
        return None
    ext = path.suffix.lower()
    if ext in TEXT_EXT or name in SPECIAL_NAMES or (not ext and name.upper() in SPECIAL_NAMES):
        return "text"
    if ext in CONVERT_EXT:
        return "convert"
    return None


def extract_text(path: Path, max_bytes: int = MAX_FILE_BYTES) -> tuple[str, str]:
    """Текст файла и примечание (пусто = ок). Никогда не бросает."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return "", f"недоступен: {e}"
    if size > max_bytes:
        return "", f"пропущен: {size // 1024 // 1024} МБ > лимита"
    ext = path.suffix.lower()
    kind = file_kind(path)
    try:
        if kind == "text":
            raw = path.read_bytes()
            if b"\x00" in raw[:4096]:
                return "", "бинарный файл"
            for enc in ("utf-8", "utf-16", "cp1251", "latin-1"):
                try:
                    return raw.decode(enc), ""
                except UnicodeDecodeError:
                    continue
            return "", "неизвестная кодировка"
        if kind == "convert":
            tool = CONVERT_EXT[ext]
            if tool == "pdftotext":
                exe = _which("pdftotext")
                if not exe:
                    return "", "для PDF нужен pdftotext: brew install poppler"
                out = subprocess.run([exe, "-layout", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=120)
                return out.stdout.decode("utf-8", errors="ignore"), "" if out.returncode == 0 else "pdftotext: ошибка"
            if tool == "textutil":
                exe = _which("textutil")
                if not exe:
                    return "", "конвертация доступна только на macOS (textutil)"
                out = subprocess.run([exe, "-convert", "txt", "-stdout", str(path)], capture_output=True, timeout=120)
                return out.stdout.decode("utf-8", errors="ignore"), "" if out.returncode == 0 else "textutil: ошибка"
            if tool == "zip-xml":  # pptx/xlsx: вытащить текст из XML внутри zip без зависимостей
                import zipfile
                texts = []
                with zipfile.ZipFile(path) as z:
                    for n in z.namelist():
                        if n.endswith(".xml") and ("slides/slide" in n or "sharedStrings" in n or "worksheets/sheet" in n):
                            xml = z.read(n).decode("utf-8", errors="ignore")
                            texts.append(" ".join(re.findall(r">([^<>]{2,})<", xml)))
                return "\n".join(t for t in texts if t.strip()), ""
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return "", f"ошибка чтения: {str(e)[:80]}"
    return "", "не индексируется"


def chunk_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[tuple[int, str]]:
    """[(строка_начала, кусок)] — режем по абзацам/строкам, чтобы куски были осмысленными."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    chunks: list[tuple[int, str]] = []
    buf: list[str] = []
    buf_len = 0
    start_line = 1
    for i, line in enumerate(lines, 1):
        if buf_len + len(line) + 1 > size and buf:
            chunk = "\n".join(buf).strip()
            if chunk:
                chunks.append((start_line, chunk))
            # перекрытие: оставляем хвост, чтобы не рвать мысль на границе
            tail: list[str] = []
            tl = 0
            for prev in reversed(buf):
                if tl + len(prev) > overlap:
                    break
                tail.insert(0, prev)
                tl += len(prev) + 1
            start_line = i - len(tail)
            buf, buf_len = tail, tl
        buf.append(line)
        buf_len += len(line) + 1
        if len(chunks) >= MAX_CHUNKS_PER_FILE:
            break
    chunk = "\n".join(buf).strip()
    if chunk and len(chunks) < MAX_CHUNKS_PER_FILE:
        chunks.append((start_line, chunk))
    return chunks


# ──────────────────────────────── индекс ───────────────────────────────────

class Vault:
    """Индекс файлов поверх соединения Brain (та же brain.db, те же бэкапы)."""

    def __init__(self, brain: Brain, root: str | os.PathLike | None = None):
        self.brain = brain
        self.root = Path(root).expanduser() if root else default_vault_dir()
        self._conn = brain._conn
        self._lock = brain._lock
        self.has_fts = True
        self._init_schema()

    # служебное ------------------------------------------------------------
    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            try:
                self._conn.executescript(FTS_SCHEMA)
            except sqlite3.OperationalError:
                self.has_fts = False
            # миграция v1 → v2: колонки для авторезюме новых файлов (базы, созданные 1.8.0)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(files)")}
            for col, ddl in (("summarized_at", "TEXT"), ("summary_note", "INTEGER")):
                if col not in cols:
                    self._conn.execute(f"ALTER TABLE files ADD COLUMN {col} {ddl}")
            self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('vault_schema', ?)", (str(SCHEMA_VERSION),))
            self._conn.commit()

    def ensure_layout(self) -> Path:
        """Создать ~/JARVIS с README и стандартными папками (идемпотентно)."""
        for sub in ("", "inbox", "projects"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(README_TEXT, encoding="utf-8")
        return self.root

    def rel(self, path: Path) -> str:
        # Всегда отдаём POSIX-стиль ("/") независимо от ОС: на Windows str(Path) даёт "\\",
        # а этот путь хранится в БД, сравнивается в тестах и уходит наружу через API/skills —
        # межплатформенная стабильность важнее «нативного» вида пути.
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    # источники (подключённые внешние папки) --------------------------------
    def add_source(self, path: str | os.PathLike, name: str | None = None) -> dict:
        src = Path(path).expanduser().resolve()
        if not src.is_dir():
            raise FileNotFoundError(f"папка не найдена: {src}")
        if self.root.resolve() in (src, *src.parents):
            raise ValueError("эта папка уже внутри хранилища")
        name = (name or src.name).strip().replace("/", "-")
        self.ensure_layout()
        link = self.root / "projects" / name
        if link.is_symlink() or link.exists():
            if link.is_symlink() and link.resolve() == src:
                pass  # уже подключено
            else:
                raise FileExistsError(f"в projects/ уже есть «{name}» — укажите другое имя")
        else:
            link.symlink_to(src, target_is_directory=True)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO vault_sources(name, path, added_at) VALUES (?,?,?)", (name, str(src), now()))
            self.brain._log("user", "vault_add", "vault_sources", None, after={"name": name, "path": str(src)})
        return {"name": name, "path": str(src), "link": str(link)}

    def remove_source(self, name: str) -> dict:
        link = self.root / "projects" / name
        removed = False
        if link.is_symlink():
            link.unlink()
            removed = True
        with self._lock:
            n = self._conn.execute("DELETE FROM vault_sources WHERE name=?", (name,)).rowcount
            self._conn.execute("DELETE FROM file_chunks WHERE file_id IN (SELECT id FROM files WHERE rel LIKE ?)", (f"projects/{name}/%",))
            self._conn.execute("DELETE FROM files WHERE rel LIKE ?", (f"projects/{name}/%",))
        return {"name": name, "removed": removed or n > 0}

    def sources(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT name, path, added_at, note FROM vault_sources ORDER BY name")]

    # обход -----------------------------------------------------------------
    def walk(self) -> list[Path]:
        """Все кандидаты на индексацию (следуем по symlink'ам в projects/, защищаемся от циклов)."""
        out: list[Path] = []
        seen_dirs: set[str] = set()
        if not self.root.exists():
            return out
        stack = [self.root]
        while stack:
            d = stack.pop()
            try:
                real = str(d.resolve())
            except OSError:
                continue
            if real in seen_dirs:
                continue
            seen_dirs.add(real)
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                name = e.name
                if name.startswith(".") and name not in (".env.example",):
                    continue
                if e.is_dir(follow_symlinks=True):
                    if name in SKIP_DIRS:
                        continue
                    stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=True):
                    p = Path(e.path)
                    if file_kind(p):
                        out.append(p)
        return out

    def index_file(self, path: Path, source: str = "vault", force: bool = False) -> str:
        """'indexed' | 'unchanged' | 'skipped' | 'error'."""
        try:
            st = path.stat()
        except OSError:
            return "error"
        with self._lock:
            row = self._conn.execute("SELECT id, size, mtime, status FROM files WHERE path=?", (str(path),)).fetchone()
            if row and not force and row["size"] == st.st_size and abs(row["mtime"] - st.st_mtime) < 1e-6:
                self._conn.execute("UPDATE files SET seen_at=? WHERE id=?", (now(), row["id"]))
                return "unchanged"
        text, note = extract_text(path)
        sha1 = hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest() if text else ""
        text, _ = redact(text)
        chunks = chunk_text(text) if text else []
        with self._lock:
            c = self._conn
            c.execute("BEGIN")
            try:
                if row:
                    fid = row["id"]
                    c.execute("DELETE FROM file_chunks WHERE file_id=?", (fid,))
                    c.execute("UPDATE files SET rel=?, name=?, ext=?, source=?, size=?, mtime=?, sha1=?, chunks=?, chars=?, "
                              "kind=?, status=?, note=?, indexed_at=?, seen_at=? WHERE id=?",
                              (self.rel(path), path.name, path.suffix.lower(), source, st.st_size, st.st_mtime, sha1, len(chunks),
                               len(text), file_kind(path) or "", "ok" if text else "skipped", note, now(), now(), fid))
                else:
                    cur = c.execute("INSERT INTO files(path, rel, name, ext, source, size, mtime, sha1, chunks, chars, kind, status, "
                                    "note, indexed_at, seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                    (str(path), self.rel(path), path.name, path.suffix.lower(), source, st.st_size, st.st_mtime,
                                     sha1, len(chunks), len(text), file_kind(path) or "", "ok" if text else "skipped", note, now(), now()))
                    fid = cur.lastrowid
                c.executemany("INSERT INTO file_chunks(file_id, no, line_from, content, name, rel) VALUES (?,?,?,?,?,?)",
                              [(fid, i, ln, ch, path.name, self.rel(path)) for i, (ln, ch) in enumerate(chunks)])
                c.execute("COMMIT")
            except sqlite3.Error:
                c.execute("ROLLBACK")
                return "error"
        return "indexed" if text else "skipped"

    def reindex(self, force: bool = False, max_seconds: float = 300.0) -> dict:
        """Полный проход: новые/изменённые файлы индексируются, исчезнувшие — удаляются."""
        t0 = time.time()
        stats = {"indexed": 0, "unchanged": 0, "skipped": 0, "error": 0, "removed": 0, "seconds": 0.0, "root": str(self.root)}
        present: set[str] = set()
        for p in self.walk():
            present.add(str(p))
            rel = self.rel(p)
            source = "project:" + rel.split("/")[1] if rel.startswith("projects/") and "/" in rel[9:] else "vault"
            stats[self.index_file(p, source=source, force=force)] += 1
            if time.time() - t0 > max_seconds:
                stats["note"] = "прервано по времени — продолжу в следующий проход"
                break
        else:
            with self._lock:
                gone = [r["id"] for r in self._conn.execute("SELECT id, path FROM files") if r["path"] not in present]
                for fid in gone:
                    self._conn.execute("DELETE FROM file_chunks WHERE file_id=?", (fid,))
                    self._conn.execute("DELETE FROM files WHERE id=?", (fid,))
                stats["removed"] = len(gone)
        stats["seconds"] = round(time.time() - t0, 2)
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('vault_last_scan', ?)", (now(),))
            if stats["indexed"] or stats["removed"]:
                self.brain._log("system", "vault_reindex", "files", None, after=stats)
        if self._cfg_semantic_enabled():
            try:
                # небольшими порциями — не блокируем reindex, если файлов много; следующий проход досчитает остальное
                emb_stats = self.ensure_embeddings(batch=100)
                stats["embedded"] = emb_stats.get("embedded", 0)
            except Exception:  # эмбеддинги — best-effort, никогда не должны ронять reindex
                stats["embedded"] = 0
        return stats

    # поиск -----------------------------------------------------------------
    @staticmethod
    def _fts_query(query: str) -> str:
        words = [w for w in re.findall(r"[\w\-\.]{2,}", query.lower()) if not w.isdigit() or len(w) > 3]
        if not words:
            return ""
        # каждое слово с префиксом; OR — чтобы находить документы даже по части слов
        return " OR ".join(f'"{w.replace(chr(34), "")}"*' for w in words[:12])

    def _keyword_rows(self, q: str, prefix: str | None, pool: int) -> list[sqlite3.Row]:
        """BM25 (FTS5) поиск по ключевым словам; LIKE — запасной путь, если FTS недоступен/ничего не нашёл."""
        with self._lock:
            c = self._conn
            rows: list[sqlite3.Row] = []
            if self.has_fts:
                fq = self._fts_query(q)
                if fq:
                    sql = ("SELECT fc.id, fc.file_id, fc.no, fc.line_from, f.path, f.rel, f.name, f.source, "
                           "snippet(files_fts, 0, '«', '»', ' … ', 24) AS snip, bm25(files_fts, 1.0, 3.0, 1.5) AS score "
                           "FROM files_fts JOIN file_chunks fc ON fc.id = files_fts.rowid JOIN files f ON f.id = fc.file_id "
                           "WHERE files_fts MATCH ? AND f.status='ok' ")
                    params: list = [fq]
                    if prefix:
                        sql += "AND f.rel LIKE ? "
                        params.append(prefix.rstrip("/") + "/%")
                    sql += "ORDER BY score LIMIT ?"
                    params.append(pool)
                    try:
                        rows = c.execute(sql, params).fetchall()
                    except sqlite3.OperationalError:
                        rows = []
            if not rows:  # без FTS или ничего не нашлось по префиксам — LIKE по словам
                words = [w for w in re.findall(r"\w{3,}", q.lower())][:5]
                if not words:
                    return []
                cond = " AND ".join("lower(fc.content) LIKE ?" for _ in words)
                sql = (f"SELECT fc.id, fc.file_id, fc.no, fc.line_from, f.path, f.rel, f.name, f.source, "
                       f"substr(fc.content, 1, 240) AS snip, 0 AS score FROM file_chunks fc JOIN files f ON f.id=fc.file_id "
                       f"WHERE f.status='ok' AND {cond} ")
                params = [f"%{w}%" for w in words]
                if prefix:
                    sql += "AND f.rel LIKE ? "
                    params.append(prefix.rstrip("/") + "/%")
                sql += "LIMIT ?"
                params.append(pool)
                rows = c.execute(sql, params).fetchall()
        return rows

    def _semantic_rows(self, q: str, prefix: str | None, pool: int) -> list[sqlite3.Row]:
        """Куски, ранжированные по косинусной близости эмбеддинга запроса (best-effort, требует Ollama).

        Линейный перебор по чистому Python — сознательный выбор для личного хранилища (см. embeddings.py):
        никаких C-расширений/дополнительных зависимостей, которые могут не собраться на части платформ.
        """
        if not emb.is_available():
            return []
        qvec_list = emb.embed([q])
        if not qvec_list:
            return []
        qvec = qvec_list[0]
        with self._lock:
            sql = ("SELECT fc.id, fc.file_id, fc.no, fc.line_from, fc.content, f.path, f.rel, f.name, f.source, "
                   "fe.vector AS vector FROM file_embeddings fe JOIN file_chunks fc ON fc.id = fe.chunk_id "
                   "JOIN files f ON f.id = fc.file_id WHERE f.status='ok' ")
            params: list = []
            if prefix:
                sql += "AND f.rel LIKE ? "
                params.append(prefix.rstrip("/") + "/%")
            try:
                candidates = self._conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []
        scored = []
        for r in candidates:
            try:
                sim = emb.cosine(qvec, emb.unpack(r["vector"]))
            except (struct.error, ValueError):
                continue
            if sim > 0.35:  # ниже — почти всегда шум для nomic-embed-text
                scored.append((sim, r))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [r for _, r in scored[:pool]]

    def search(self, query: str, limit: int = 8, prefix: str | None = None) -> list[dict]:
        """Куски файлов, релевантные запросу: гибрид BM25 (точные слова) + локальные эмбеддинги через Ollama
        (смысл/перефразировки), если Ollama доступна — объединено через Reciprocal Rank Fusion. Возвращает
        path, rel, line, snippet, score. Без Ollama — как раньше, чистый BM25/FTS5."""
        q = (query or "").strip()
        if not q:
            return []
        pool = max(limit * 3, 20)
        kw_rows = self._keyword_rows(q, prefix, pool)
        sem_rows = self._semantic_rows(q, prefix, pool) if self._cfg_semantic_enabled() else []
        by_id: dict[int, sqlite3.Row] = {}
        rankings: list[list[int]] = []
        for rows in (kw_rows, sem_rows):
            order = []
            for r in rows:
                by_id.setdefault(r["id"], r)
                order.append(r["id"])
            if order:
                rankings.append(order)
        if not rankings:
            return []
        fused = rankings[0] if len(rankings) == 1 else [cid for cid, _ in emb.rrf_fuse(rankings)]
        # не больше 2 кусков на файл — иначе один большой файл вытесняет остальные
        out: list[dict] = []
        per_file: dict[int, int] = {}
        for cid in fused:
            r = by_id[cid]
            if per_file.get(r["file_id"], 0) >= 2:
                continue
            per_file[r["file_id"]] = per_file.get(r["file_id"], 0) + 1
            snip = r["snip"] if "snip" in r.keys() else re.sub(r"\s+", " ", r["content"])[:240]
            score = -float(r["score"]) if ("score" in r.keys() and r["score"]) else 0.0
            out.append({"file_id": r["file_id"], "path": r["path"], "rel": r["rel"], "name": r["name"], "source": r["source"],
                        "line": r["line_from"], "chunk": r["no"], "snippet": re.sub(r"\s+", " ", snip).strip()[:300],
                        "score": round(score, 2)})
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _cfg_semantic_enabled() -> bool:
        return os.environ.get("JARVIS_VAULT_SEMANTIC", "1") != "0"

    # ── семантический индекс (эмбеддинги через Ollama, best-effort) ────────
    def ensure_embeddings(self, batch: int = 50) -> dict:
        """Досчитать эмбеддинги для кусков, у которых их ещё нет. Ничего не делает, если Ollama недоступна
        или модель эмбеддингов не скачана — вызывается периодически из фонового сканирования, не блокирует
        обычную индексацию текста."""
        if not emb.is_available():
            return {"embedded": 0, "available": False}
        with self._lock:
            rows = self._conn.execute(
                "SELECT fc.id, fc.content FROM file_chunks fc LEFT JOIN file_embeddings fe ON fe.chunk_id = fc.id "
                "JOIN files f ON f.id = fc.file_id WHERE fe.chunk_id IS NULL AND f.status='ok' LIMIT ?", (batch,)
            ).fetchall()
        if not rows:
            return {"embedded": 0, "available": True}
        vecs = emb.embed([r["content"] for r in rows])
        if not vecs:
            return {"embedded": 0, "available": True, "note": "модель эмбеддингов не ответила"}
        with self._lock:
            self._conn.executemany(
                "INSERT OR REPLACE INTO file_embeddings(chunk_id, model, vector, created_at) VALUES (?,?,?,?)",
                [(r["id"], emb.EMBED_MODEL, emb.pack(v), now()) for r, v in zip(rows, vecs, strict=True)])
            self._conn.commit()
        return {"embedded": len(rows), "available": True}

    def read(self, path: str, offset: int = 0, limit: int = 6000) -> dict:
        """Текст файла (с конвертацией PDF/DOCX), кусками по limit символов. Путь — абсолютный или относительно хранилища."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.root / p
        if not p.exists():
            return {"error": f"файл не найден: {p}"}
        if p.is_dir():
            return {"path": str(p), "dir": True, "entries": self.tree(p, depth=1)}
        text, note = extract_text(p)
        if not text:
            return {"path": str(p), "error": note or "пустой файл или не текст"}
        total = len(text)
        piece = text[offset: offset + limit]
        return {"path": str(p), "offset": offset, "chars": len(piece), "total": total,
                "next_offset": offset + limit if offset + limit < total else None, "content": piece}

    # ── запись и наведение порядка ─────────────────────────────────────────
    def resolve_inside(self, path: str) -> Path:
        """Абсолютный путь, гарантированно внутри хранилища или подключённого проекта (symlink разрешается)."""
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.root / p
        real = p.resolve() if p.exists() else p.parent.resolve() / p.name
        roots = [self.root.resolve()] + [Path(r["path"]).resolve() for r in self.sources()]
        if not any(real == r or r in real.parents for r in roots):
            raise PermissionError(f"путь вне хранилища и подключённых проектов: {p}")
        return real

    def write(self, path: str, content: str, mode: str = "overwrite") -> dict:
        """Создать/перезаписать/дописать текстовый файл внутри хранилища; индекс обновляется сразу."""
        p = self.resolve_inside(path)
        if p.is_dir():
            raise IsADirectoryError(f"это папка: {p}")
        if SKIP_NAME_RE.search(p.name):
            raise PermissionError("файлы с секретами (.env, ключи, сертификаты) через vault не пишутся")
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        with open(p, "a" if mode == "append" else "w", encoding="utf-8") as f:
            f.write(content if not (mode == "append" and existed and content and not content.startswith("\n")) else "\n" + content)
        status = self.index_file(p, source=self._source_for(p), force=True)
        self.brain._log("agent", "vault_write", "files", None, after={"path": str(p), "mode": mode, "chars": len(content)})
        return {"path": str(p), "rel": self.rel(p), "created": not existed, "indexed": status == "indexed"}

    def mkdir(self, path: str) -> dict:
        p = self.resolve_inside(path)
        p.mkdir(parents=True, exist_ok=True)
        return {"path": str(p), "rel": self.rel(p)}

    def move(self, src: str, dst: str) -> dict:
        """Переместить/переименовать внутри хранилища (dst — папка или новое имя). Существующее не перезаписываем."""
        s_ = self.resolve_inside(src)
        if not s_.exists():
            raise FileNotFoundError(f"нет такого файла: {s_}")
        d = self.resolve_inside(dst)
        if d.is_dir():
            d = d / s_.name
        if d.exists():
            raise FileExistsError(f"уже существует: {d}")
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s_), str(d))
        with self._lock:
            self._conn.execute("DELETE FROM file_chunks WHERE file_id IN (SELECT id FROM files WHERE path=? OR path LIKE ?)", (str(s_), str(s_) + "/%"))
            self._conn.execute("DELETE FROM files WHERE path=? OR path LIKE ?", (str(s_), str(s_) + "/%"))
            self._conn.commit()
        if d.is_dir():
            self.reindex()
        else:
            self.index_file(d, source=self._source_for(d), force=True)
        self.brain._log("agent", "vault_move", "files", None, after={"from": str(s_), "to": str(d)})
        return {"from": str(s_), "to": str(d), "rel": self.rel(d)}

    def trash(self, path: str) -> dict:
        """Удаление = только в Корзину macOS (или ~/JARVIS/.trash вне macOS). Необратимого rm здесь нет."""
        p = self.resolve_inside(path)
        if not p.exists():
            raise FileNotFoundError(f"нет такого файла: {p}")
        if p == self.root.resolve() or p.parent == self.root.resolve() and p.name in ("inbox", "projects"):
            raise PermissionError("системные папки хранилища не удаляются")
        moved = False
        if sys.platform == "darwin":
            try:
                subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file "{str(p).replace(chr(34), "")}"'],
                               capture_output=True, timeout=10, check=True)
                moved = True
            except (subprocess.SubprocessError, OSError):
                moved = False
        elif sys.platform == "win32":
            try:
                esc = str(p).replace("'", "''")
                kind = "DeleteDirectory" if p.is_dir() else "DeleteFile"
                subprocess.run(
                    ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                     "Add-Type -AssemblyName Microsoft.VisualBasic; "
                     f"[Microsoft.VisualBasic.FileIO.FileSystem]::{kind}('{esc}', 'OnlyErrorDialogs', 'SendToRecycleBin')"],
                    capture_output=True, timeout=10, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                moved = True
            except (subprocess.SubprocessError, OSError):
                moved = False
        if not moved:
            tdir = self.root / ".trash"
            tdir.mkdir(exist_ok=True)
            shutil.move(str(p), str(tdir / f"{int(time.time())}-{p.name}"))
        with self._lock:
            self._conn.execute("DELETE FROM file_chunks WHERE file_id IN (SELECT id FROM files WHERE path=? OR path LIKE ?)", (str(p), str(p) + "/%"))
            self._conn.execute("DELETE FROM files WHERE path=? OR path LIKE ?", (str(p), str(p) + "/%"))
            self._conn.commit()
        self.brain._log("agent", "vault_trash", "files", None, after={"path": str(p), "finder": moved})
        return {"path": str(p), "trashed": True, "where": "Корзина" if moved else str(self.root / ".trash")}

    def _source_for(self, p: Path) -> str:
        for r in self.sources():
            rp = Path(r["path"]).resolve()
            if p == rp or rp in p.parents:
                return r["name"]
        return "vault"

    # ── новые файлы → резюме в базу знаний ──────────────────────────────────
    def pending_summaries(self, limit: int = 5) -> list[dict]:
        """Файлы в хранилище (не в проектах), проиндексированные, но ещё без заметки-резюме в базе знаний."""
        rows = self._conn.execute(
            """SELECT f.id, f.path, f.rel, f.name, f.ext, f.size FROM files f
               WHERE f.status='ok' AND f.source='vault' AND f.summarized_at IS NULL AND f.name NOT IN ('README.md')
               ORDER BY f.mtime DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_summarized(self, file_id: int, note_id: int | None = None) -> None:
        with self._lock:
            self._conn.execute("UPDATE files SET summarized_at=?, summary_note=? WHERE id=?", (now(), note_id, file_id))
            self._conn.commit()

    # ── стандартные внешние папки одной командой ────────────────────────────
    CONNECTORS = {
        "icloud": ("~/Library/Mobile Documents/com~apple~CloudDocs", "iCloud"),
        "desktop": ("~/Desktop", "Desktop"),
        "documents": ("~/Documents", "Documents"),
        "downloads": ("~/Downloads", "Downloads"),
        "notes-obsidian": (None, "Obsidian"),  # ищем vault Obsidian по конфигу приложения
    }

    def connect(self, what: str) -> dict:
        what = what.lower()
        if what not in self.CONNECTORS:
            raise ValueError(f"неизвестный источник {what}; доступно: {', '.join(self.CONNECTORS)}")
        path, name = self.CONNECTORS[what]
        if what == "notes-obsidian":
            path = self._find_obsidian()
            if not path:
                raise FileNotFoundError("Obsidian vault не найден (нет ~/Library/Application Support/obsidian/obsidian.json)")
        return self.add_source(path, name)

    @staticmethod
    def _obsidian_config_candidates() -> list[Path]:
        """Пути к obsidian.json (реестр открытых vault-ов) на macOS/Windows/Linux.

        Формат файла одинаковый на всех платформах — отличается только системная папка
        настроек приложения (см. https://help.obsidian.md, «How Obsidian stores data»).
        """
        candidates: list[Path] = []
        if sys.platform == "darwin":
            candidates.append(Path("~/Library/Application Support/obsidian/obsidian.json"))
        elif sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                candidates.append(Path(appdata) / "obsidian" / "obsidian.json")
            candidates.append(Path("~/AppData/Roaming/obsidian/obsidian.json"))
        else:  # Linux и прочие *nix, включая snap-упаковку
            xdg = os.environ.get("XDG_CONFIG_HOME")
            if xdg:
                candidates.append(Path(xdg) / "obsidian" / "obsidian.json")
            candidates.append(Path("~/.config/obsidian/obsidian.json"))
            candidates.append(Path("~/snap/obsidian/current/.config/obsidian/obsidian.json"))
            candidates.append(Path("~/.var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json"))  # flatpak
        return [c.expanduser() for c in candidates]

    @classmethod
    def _find_obsidian(cls) -> str | None:
        for cfg in cls._obsidian_config_candidates():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                continue
            vaults = data.get("vaults") or {}
            best = max(vaults.values(), key=lambda v: v.get("ts", 0)) if vaults else None
            if best and Path(best["path"]).is_dir():
                return best["path"]
        return None

    @classmethod
    def list_obsidian_vaults(cls) -> list[dict]:
        """Все известные Obsidian-vault-ы (не только самый недавний), для выбора пользователем."""
        out: list[dict] = []
        for cfg in cls._obsidian_config_candidates():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                continue
            for v in (data.get("vaults") or {}).values():
                p = v.get("path")
                if p and Path(p).is_dir():
                    out.append({"path": p, "name": Path(p).name, "ts": v.get("ts", 0)})
            break  # первый найденный файл конфигурации — этого достаточно
        out.sort(key=lambda v: v["ts"], reverse=True)
        return out

    def _obsidian_vault_root(self) -> Path | None:
        """Корень подключённого Obsidian vault-а (projects/Obsidian), если он подключён через connect()."""
        for r in self.sources():
            if r["name"] == "Obsidian":
                return Path(r["path"]).resolve()
        p = self.root / "projects" / "Obsidian"
        return p.resolve() if p.is_dir() else None

    def _daily_notes_settings(self, vault_root: Path) -> dict:
        """Читает .obsidian/daily-notes.json (папка/формат имени/шаблон), best-effort."""
        cfg_path = vault_root / ".obsidian" / "daily-notes.json"
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _moment_like_date(fmt: str, when: dt.date) -> str:
        """Минимальная поддержка Moment.js-формата дат Obsidian (YYYY/MM/DD/dddd и т.п.) без внешних зависимостей."""
        repl = {
            "YYYY": "%Y", "YY": "%y", "MMMM": "%B", "MMM": "%b", "MM": "%m",
            "DD": "%d", "dddd": "%A", "ddd": "%a",
        }
        out = fmt
        for token, strftime_code in repl.items():
            out = out.replace(token, strftime_code)
        try:
            return when.strftime(out)
        except ValueError:
            return when.isoformat()

    def obsidian_note(self, title: str = "", content: str = "", tags: str = "", folder: str | None = None,
                       daily: bool = False) -> dict:
        """Создать/дополнить заметку по конвенциям Obsidian: YAML-frontmatter + место по правилам vault-а.

        - daily=True: дописывает в сегодняшнюю ежедневную заметку — папка/формат имени берутся
          из .obsidian/daily-notes.json, если настроено, иначе YYYY-MM-DD.md в корне vault-а.
        - иначе: обычная заметка `<title>.md`, опционально в указанной folder.
        Заметка создаётся внутри подключённого Obsidian vault-а (`vault_manage connect what=notes-obsidian`);
        если он не подключён — пишет в хранилище JARVIS напрямую (в inbox/).
        """
        vault_root = self._obsidian_vault_root()
        today = dt.date.today()
        tag_list = [t.strip().lstrip("#") for t in tags.split(",") if t.strip()]

        if daily:
            settings = self._daily_notes_settings(vault_root) if vault_root else {}
            name = self._moment_like_date(settings.get("format") or "YYYY-MM-DD", today)
            rel_dir = settings.get("folder") or folder or ""
        else:
            safe = re.sub(r'[\\/:*?"<>|]', "-", title).strip() or f"Заметка {today.isoformat()}"
            name = safe
            rel_dir = folder or ("" if vault_root else "inbox")

        rel_in_vault = f"{rel_dir.rstrip('/')}/{name}.md" if rel_dir else f"{name}.md"
        # write()/resolve_inside работают от корня хранилища self.root — если это отдельный
        # Obsidian vault, подключённый как projects/Obsidian, добавляем этот префикс.
        if vault_root:
            prefix = "projects/Obsidian/"
        else:
            prefix = ""
        rel_from_store = prefix + rel_in_vault

        already_exists = False
        try:
            already_exists = self.resolve_inside(rel_from_store).exists()
        except (PermissionError, ValueError, OSError):
            already_exists = False

        if daily:
            mode = "append"
            stamp = dt.datetime.now().strftime("%H:%M")
            piece = f"\n\n## {stamp}\n{content}\n" if content else ""
            content_out = piece if already_exists else self._frontmatter(tag_list, today) + f"# {title or today.isoformat()}\n" + piece
        else:
            mode = "overwrite"
            content_out = self._frontmatter(tag_list, today) + f"# {name}\n\n{content}\n"

        res = self.write(rel_from_store, content_out, mode=mode)
        res["vault"] = "Obsidian" if vault_root else "JARVIS"
        res["daily"] = daily
        return res

    @staticmethod
    def _frontmatter(tags: list[str], when: dt.date) -> str:
        lines = ["---", f"created: {when.isoformat()}"]
        if tags:
            lines.append("tags:")
            lines.extend(f"  - {t}" for t in tags)
        lines.append("---\n")
        return "\n".join(lines)

    def tree(self, start: Path | None = None, depth: int = 2, limit: int = 200) -> list[str]:
        base = Path(start).expanduser() if start else self.root
        out: list[str] = []
        base_depth = len(base.parts)
        for d, dirs, files in os.walk(base, followlinks=True):
            dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
            level = len(Path(d).parts) - base_depth
            if level >= depth:
                dirs[:] = []
            indent = "  " * level
            if level:
                out.append(f"{indent}{Path(d).name}/")
            for f in sorted(files):
                if f.startswith(".") or SKIP_NAME_RE.search(f):
                    continue
                out.append(f"{indent}  {f}")
                if len(out) >= limit:
                    out.append("  …")
                    return out
        return out

    def list_files(self, prefix: str | None = None, limit: int = 100, recent: bool = False) -> list[dict]:
        with self._lock:
            sql = "SELECT rel, path, name, ext, source, size, chunks, status, note, indexed_at, mtime FROM files "
            params: list = []
            if prefix:
                sql += "WHERE rel LIKE ? "
                params.append(prefix.rstrip("/") + "/%")
            sql += ("ORDER BY mtime DESC " if recent else "ORDER BY rel ") + "LIMIT ?"
            params.append(limit)
            return [dict(r) for r in self._conn.execute(sql, params)]

    def stats(self) -> dict:
        with self._lock:
            c = self._conn
            one = lambda sql: c.execute(sql).fetchone()[0]
            last = c.execute("SELECT value FROM meta WHERE key='vault_last_scan'").fetchone()
            by_source = [dict(r) for r in c.execute(
                "SELECT source, COUNT(*) AS files, SUM(chunks) AS chunks FROM files WHERE status='ok' GROUP BY source ORDER BY files DESC")]
            skipped = [dict(r) for r in c.execute("SELECT rel, note FROM files WHERE status!='ok' ORDER BY rel LIMIT 10")]
            embedded = one("SELECT COUNT(*) FROM file_embeddings")
        return {"root": str(self.root), "exists": self.root.exists(), "files": one("SELECT COUNT(*) FROM files WHERE status='ok'"),
                "chunks": one("SELECT COUNT(*) FROM file_chunks"), "chars": one("SELECT COALESCE(SUM(chars),0) FROM files"),
                "skipped": one("SELECT COUNT(*) FROM files WHERE status!='ok'"), "skipped_examples": skipped,
                "sources": self.sources(), "by_source": by_source, "last_scan": last["value"] if last else None,
                "fts": self.has_fts, "pdf": bool(_which("pdftotext")), "office": bool(_which("textutil")),
                "semantic_search": emb.is_available(), "embedded_chunks": embedded}


# ─────────────────────────── фоновое обновление ────────────────────────────

class VaultWatcher:
    """Периодический пересчёт индекса в фоне (без сторонних зависимостей вроде watchdog/fsevents)."""

    def __init__(self, vault: Vault, interval_min: float = 10.0, on_change=None):
        self.vault = vault
        self.interval = max(1.0, float(interval_min)) * 60
        self.on_change = on_change
        self._stop = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="jarvis-vault", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        # первый проход почти сразу (после старта Hermes), дальше — по интервалу
        if self._stop.wait(20):
            return
        while not self._stop.is_set():
            try:
                st = self.vault.reindex()
                if self.on_change and (st["indexed"] or st["removed"]):
                    self.on_change(st)
            except Exception:  # индекс — вспомогательная вещь, не роняем процесс
                pass
            if self._stop.wait(self.interval):
                return


# ──────────────────────────────── CLI ──────────────────────────────────────

def _main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="jarvis vault", description="Хранилище файлов и проектов JARVIS")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status")
    r = sub.add_parser("reindex"); r.add_argument("--force", action="store_true")
    ls = sub.add_parser("list"); ls.add_argument("prefix", nargs="?"); ls.add_argument("--recent", action="store_true")
    s = sub.add_parser("search"); s.add_argument("query", nargs="+"); s.add_argument("-n", type=int, default=8); s.add_argument("--in", dest="prefix")
    a = sub.add_parser("add"); a.add_argument("path"); a.add_argument("--name")
    rm = sub.add_parser("remove"); rm.add_argument("name")
    t = sub.add_parser("tree"); t.add_argument("path", nargs="?"); t.add_argument("--depth", type=int, default=2)
    rd = sub.add_parser("read"); rd.add_argument("path"); rd.add_argument("--offset", type=int, default=0)
    sub.add_parser("init")
    c = sub.add_parser("connect", help="подключить iCloud / Desktop / Documents / Downloads / Obsidian"); c.add_argument("what", choices=sorted(Vault.CONNECTORS))
    mv = sub.add_parser("move"); mv.add_argument("path"); mv.add_argument("to")
    tr = sub.add_parser("trash"); tr.add_argument("path")
    sub.add_parser("pending", help="новые файлы, ещё не разобранные в базу знаний")
    on = sub.add_parser("note", help="создать заметку Obsidian (или в ~/JARVIS, если vault не подключён)")
    on.add_argument("title", nargs="?", default="")
    on.add_argument("--content", default="")
    on.add_argument("--tags", default="")
    on.add_argument("--folder")
    on.add_argument("--daily", action="store_true", help="дописать в сегодняшнюю ежедневную заметку")
    sub.add_parser("obsidian-list", help="показать все найденные Obsidian-vault-ы")
    for sp in sub.choices.values():
        sp.add_argument("--json", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    v = Vault(Brain())
    try:
        if args.cmd in (None, "status"):
            st = v.stats()
            if args.json:
                print(json.dumps(st, ensure_ascii=False, indent=2)); return 0
            print(f"Хранилище: {st['root']}  {'(есть)' if st['exists'] else '(ещё не создано — jarvis vault init)'}")
            print(f"Файлов в индексе: {st['files']} · кусков: {st['chunks']} · символов: {st['chars']:,} · пропущено: {st['skipped']}")
            print(f"Последний проход: {st['last_scan'] or '—'} · PDF: {'да' if st['pdf'] else 'нет (brew install poppler)'} · Office: {'да' if st['office'] else 'нет'}")
            sem = f"да ({st['embedded_chunks']} кусков)" if st["semantic_search"] else "нет (jarvis ollama pull nomic-embed-text)"
            print(f"Семантический поиск (смысл, не только слова): {sem}")
            for s_ in st["sources"]:
                print(f"  ⤷ проект {s_['name']} → {s_['path']}")
            for b in st["by_source"]:
                print(f"  {b['source']}: {b['files']} файлов, {b['chunks'] or 0} кусков")
            return 0
        if args.cmd == "init":
            print(v.ensure_layout()); return 0
        if args.cmd == "connect":
            res = v.connect(args.what); st = v.reindex()
            print(json.dumps({**res, "indexed": st["indexed"]}, ensure_ascii=False) if args.json else f"✔ {res['name']} → {res['path']} (проиндексировано {st['indexed']})")
            return 0
        if args.cmd == "move":
            print(json.dumps(v.move(args.path, args.to), ensure_ascii=False)); return 0
        if args.cmd == "trash":
            print(json.dumps(v.trash(args.path), ensure_ascii=False)); return 0
        if args.cmd == "pending":
            rows = v.pending_summaries(50)
            print(json.dumps(rows, ensure_ascii=False, indent=1) if args.json else "\n".join(r_["rel"] for r_ in rows) or "всё разобрано")
            return 0
        if args.cmd == "reindex":
            v.ensure_layout()
            st = v.reindex(force=args.force)
            print(json.dumps(st, ensure_ascii=False) if args.json else
                  f"✔ проиндексировано {st['indexed']}, без изменений {st['unchanged']}, пропущено {st['skipped']}, удалено {st['removed']} ({st['seconds']} с)")
            return 0
        if args.cmd == "note":
            if not args.title and not args.daily:
                ap.error("нужен title (или --daily для ежедневной заметки)")
            res = v.obsidian_note(title=args.title, content=args.content, tags=args.tags, folder=args.folder, daily=args.daily)
            print(json.dumps(res, ensure_ascii=False) if args.json else f"✔ {res['vault']}: {res['rel']}")
            return 0
        if args.cmd == "obsidian-list":
            vaults = Vault.list_obsidian_vaults()
            if args.json:
                print(json.dumps(vaults, ensure_ascii=False, indent=1)); return 0
            print("\n".join(f"{v_['name']}  →  {v_['path']}" for v_ in vaults) or "Obsidian-vault-ы не найдены")
            return 0
        if args.cmd == "list":
            rows = v.list_files(args.prefix, recent=args.recent)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1)); return 0
            for r_ in rows:
                flag = "" if r_["status"] == "ok" else f"  [{r_['note']}]"
                print(f"{r_['rel']}  ({r_['size'] // 1024} КБ, {r_['chunks']} кусков){flag}")
            return 0
        if args.cmd == "search":
            hits = v.search(" ".join(args.query), limit=args.n, prefix=args.prefix)
            if args.json:
                print(json.dumps(hits, ensure_ascii=False, indent=1)); return 0
            if not hits:
                print("ничего не найдено"); return 1
            for h in hits:
                print(f"◆ {h['rel']}:{h['line']}  ({h['score']})\n    {h['snippet']}")
            return 0
        if args.cmd == "add":
            res = v.add_source(args.path, args.name)
            print(f"✔ подключено: projects/{res['name']} → {res['path']}")
            st = v.reindex()
            print(f"  проиндексировано {st['indexed']} файлов")
            return 0
        if args.cmd == "remove":
            print(json.dumps(v.remove_source(args.name), ensure_ascii=False)); return 0
        if args.cmd == "tree":
            print("\n".join(v.tree(Path(args.path) if args.path else None, depth=args.depth))); return 0
        if args.cmd == "read":
            res = v.read(args.path, offset=args.offset)
            print(res.get("content") or res.get("error") or json.dumps(res, ensure_ascii=False)); return 0
    except (OSError, ValueError) as e:
        print(f"✖ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
