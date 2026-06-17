import json
import sqlite3
from contextvars import ContextVar
from pathlib import Path

from voicerhub_bot.models import (
    CONTENT_STATUSES,
    CONTENT_STATUS_TRANSITIONS,
    BatchRecord,
    Draft,
    GenerationJob,
)
from voicerhub_bot.text_utils import strip_emoji


TENANT_TABLES = (
    "drafts",
    "generation_jobs",
    "reference_assets",
    "content_ideas",
    "custom_visual_templates",
    "content_rubrics",
    "social_variants",
    "batch_runs",
    "usage_events",
    "content_plans",
    "content_series",
)

GENERATION_PROGRESS = {
    "queued_text": (12, "Готуємо запит до AI"),
    "text_batch": (35, "AI генерує текст"),
    "queued_image": (68, "Текст готовий. Готуємо візуал"),
    "image_batch": (86, "AI генерує зображення"),
    "ready": (100, "Матеріал готовий"),
    "failed": (100, "Генерація зупинилася"),
    "cancelled": (100, "Генерацію скасовано"),
}


def generation_progress(status: str) -> dict:
    percent, label = GENERATION_PROGRESS.get(status, (0, "Очікуємо на генерацію"))
    return {"progress": percent, "progress_label": label}


class DraftRepository:
    def __init__(self, database_path: Path, organization_id: int = 1) -> None:
        self.database_path = database_path
        self.organization_id = organization_id
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            connection.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    product TEXT NOT NULL,
                    title TEXT NOT NULL,
                    caption_html TEXT NOT NULL,
                    image_prompt TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    published_at TEXT
                )
                """
            )
            self._ensure_column(connection, "drafts", "scheduled_at", "TEXT")
            self._ensure_column(connection, "drafts", "telegram_message_id", "INTEGER")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    product TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued_text',
                    text_batch_id TEXT,
                    image_batch_id TEXT,
                    draft_id INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column(connection, "generation_jobs", "text_model", "TEXT")
            self._ensure_column(connection, "generation_jobs", "image_model", "TEXT")
            self._ensure_column(
                connection, "generation_jobs", "reference_ids", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                connection,
                "generation_jobs",
                "template_id",
                "TEXT NOT NULL DEFAULT 'editorial-dark'",
            )
            self._ensure_column(
                connection, "generation_jobs", "logo_reference_id", "INTEGER"
            )
            self._ensure_column(
                connection, "generation_jobs", "company_logo_reference_id", "INTEGER"
            )
            self._ensure_column(
                connection, "generation_jobs", "link_url", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(connection, "generation_jobs", "idea_id", "INTEGER")
            self._ensure_column(
                connection, "drafts", "link_url", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(
                connection, "drafts", "visual_title", "TEXT NOT NULL DEFAULT ''"
            )
            self._ensure_column(
                connection, "drafts", "title_options", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                connection, "drafts", "cta_options", "TEXT NOT NULL DEFAULT '[]'"
            )
            self._ensure_column(
                connection, "drafts", "tone", "TEXT NOT NULL DEFAULT 'expert'"
            )
            self._ensure_column(
                connection, "drafts", "is_favorite", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                connection, "generation_jobs", "tone", "TEXT NOT NULL DEFAULT 'expert'"
            )
            self._ensure_column(
                connection, "generation_jobs", "created_by_user_id", "INTEGER"
            )
            self._ensure_column(
                connection,
                "generation_jobs",
                "generation_mode",
                "TEXT NOT NULL DEFAULT 'batch'",
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reference_assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for column, definition in (
                ("material_type", "TEXT NOT NULL DEFAULT 'reference_image'"),
                ("description", "TEXT NOT NULL DEFAULT ''"),
                ("source_url", "TEXT NOT NULL DEFAULT ''"),
                ("active", "INTEGER NOT NULL DEFAULT 1"),
                ("created_by_user_id", "INTEGER"),
                ("updated_at", "TEXT"),
            ):
                self._ensure_column(
                    connection,
                    "reference_assets",
                    column,
                    definition,
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS content_ideas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product TEXT NOT NULL,
                    title TEXT NOT NULL,
                    angle TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'suggested',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for column, definition in (
                ("planned_for", "TEXT"),
                ("tone", "TEXT NOT NULL DEFAULT 'expert'"),
                ("series_id", "TEXT"),
                ("series_title", "TEXT NOT NULL DEFAULT ''"),
                ("series_part", "INTEGER NOT NULL DEFAULT 0"),
                ("source_url", "TEXT NOT NULL DEFAULT ''"),
                ("duplicate_score", "REAL NOT NULL DEFAULT 0"),
                ("duplicate_of", "INTEGER"),
                ("plan_id", "TEXT"),
            ):
                self._ensure_column(connection, "content_ideas", column, definition)
            connection.execute(
                """
                UPDATE generation_jobs
                SET idea_id = (
                    SELECT id
                    FROM content_ideas
                    WHERE generation_jobs.topic = content_ideas.title || '. ' || content_ideas.angle
                    ORDER BY id DESC
                    LIMIT 1
                )
                WHERE idea_id IS NULL
                  AND EXISTS (
                    SELECT 1
                    FROM content_ideas
                    WHERE generation_jobs.topic = content_ideas.title || '. ' || content_ideas.angle
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS custom_visual_templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    layout TEXT NOT NULL DEFAULT 'top_left',
                    accent TEXT NOT NULL DEFAULT '#18ecd6',
                    preview_path TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for column, definition in (
                ("mood", "TEXT NOT NULL DEFAULT ''"),
                ("use_rules", "TEXT NOT NULL DEFAULT ''"),
                ("avoid_rules", "TEXT NOT NULL DEFAULT ''"),
                ("prompt_examples", "TEXT NOT NULL DEFAULT ''"),
                ("active", "INTEGER NOT NULL DEFAULT 1"),
                ("updated_at", "TEXT"),
            ):
                self._ensure_column(
                    connection,
                    "custom_visual_templates",
                    column,
                    definition,
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS content_rubrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    default_link TEXT NOT NULL DEFAULT '',
                    fixed_cover_path TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            for column, definition in (
                ("goal", "TEXT NOT NULL DEFAULT ''"),
                ("tone", "TEXT NOT NULL DEFAULT ''"),
                ("example_topic", "TEXT NOT NULL DEFAULT ''"),
            ):
                self._ensure_column(
                    connection,
                    "content_rubrics",
                    column,
                    definition,
                )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS social_variants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    draft_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text_content TEXT NOT NULL,
                    hashtags TEXT NOT NULL DEFAULT '[]',
                    image_prompt TEXT NOT NULL,
                    image_path TEXT NOT NULL,
                    text_model TEXT NOT NULL,
                    image_model TEXT NOT NULL,
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(draft_id, platform),
                    FOREIGN KEY(draft_id) REFERENCES drafts(id)
                )
                """
            )
            self._ensure_column(
                connection,
                "social_variants",
                "visual_title",
                "TEXT NOT NULL DEFAULT ''",
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_runs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER,
                    kind TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    units INTEGER NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS content_plans (
                    id TEXT PRIMARY KEY,
                    period TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    posts INTEGER NOT NULL,
                    objective TEXT NOT NULL DEFAULT '',
                    create_as TEXT NOT NULL DEFAULT 'ideas',
                    rubric_slugs TEXT NOT NULL DEFAULT '[]',
                    channel_ids TEXT NOT NULL DEFAULT '[]',
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS content_series (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    parts INTEGER NOT NULL,
                    rubric_slug TEXT NOT NULL DEFAULT '',
                    created_by_user_id INTEGER,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            self._ensure_column(connection, "usage_events", "user_id", "INTEGER")
            for table in TENANT_TABLES:
                self._ensure_column(
                    connection,
                    table,
                    "organization_id",
                    "INTEGER NOT NULL DEFAULT 0",
                )
                connection.execute(
                    f"UPDATE {table} SET organization_id = ? "
                    "WHERE organization_id IS NULL OR organization_id = 0",
                    (self.organization_id,),
                )
                connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{table}_organization_id "
                    f"ON {table}(organization_id)"
                )
                connection.execute(f"DROP TRIGGER IF EXISTS trg_{table}_organization_id")
                connection.execute(
                    f"""
                    CREATE TRIGGER trg_{table}_organization_id
                    AFTER INSERT ON {table}
                    WHEN NEW.organization_id = 0
                    BEGIN
                        UPDATE {table}
                        SET organization_id = {int(self.organization_id)}
                        WHERE rowid = NEW.rowid;
                    END
                    """
                )
                if (
                    self.organization_id != 1
                    and self.database_path.parent.name == str(self.organization_id)
                ):
                    connection.execute(
                        f"UPDATE {table} SET organization_id = ? "
                        "WHERE organization_id != ?",
                        (self.organization_id, self.organization_id),
                    )
            connection.execute(
                """
                UPDATE content_ideas SET status = 'idea'
                WHERE status IN ('suggested', 'selected')
                """
            )
            draft_titles = connection.execute(
                """
                SELECT id, title FROM drafts
                WHERE visual_title IS NULL OR visual_title = ''
                """
            ).fetchall()
            for row in draft_titles:
                connection.execute(
                    "UPDATE drafts SET visual_title = ? WHERE id = ?",
                    (strip_emoji(row["title"]) or "Заголовок", row["id"]),
                )
            social_titles = connection.execute(
                """
                SELECT id, title FROM social_variants
                WHERE visual_title IS NULL OR visual_title = ''
                """
            ).fetchall()
            for row in social_titles:
                connection.execute(
                    "UPDATE social_variants SET visual_title = ? WHERE id = ?",
                    (strip_emoji(row["title"]) or "Заголовок", row["id"]),
                )
            connection.execute(
                """
                UPDATE usage_events
                SET user_id = (
                    SELECT created_by_user_id
                    FROM generation_jobs
                    WHERE generation_jobs.id = usage_events.job_id
                )
                WHERE user_id IS NULL
                  AND job_id > 0
                """
            )

    def _ensure_owned(
        self,
        connection: sqlite3.Connection,
        table: str,
        object_id: object,
    ) -> sqlite3.Row:
        row = connection.execute(
            f"SELECT * FROM {table} WHERE id = ? AND organization_id = ?",
            (object_id, self.organization_id),
        ).fetchone()
        if row is None:
            raise KeyError(f"{table} object not found")
        return row

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            try:
                connection.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                )
            except sqlite3.OperationalError as exc:
                # Admin and worker can initialize the same tenant database together.
                if "duplicate column name" not in str(exc).lower():
                    raise

    def create(
        self,
        *,
        topic: str,
        product: str,
        title: str,
        visual_title: str | None = None,
        caption_html: str,
        image_prompt: str,
        image_path: str,
        link_url: str = "",
        title_options: list[str] | None = None,
        cta_options: list[str] | None = None,
        tone: str = "expert",
    ) -> Draft:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO drafts (
                    topic, product, title, visual_title, caption_html, image_prompt, image_path,
                    link_url, title_options, cta_options, tone, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic,
                    product,
                    title,
                    strip_emoji(visual_title or title) or "Заголовок",
                    caption_html,
                    image_prompt,
                    image_path,
                    link_url,
                    json.dumps(title_options or [], ensure_ascii=False),
                    json.dumps(cta_options or [], ensure_ascii=False),
                    tone,
                    self.organization_id,
                ),
            )
            draft_id = int(cursor.lastrowid)
        return self.get(draft_id)

    def get(self, draft_id: int) -> Draft:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "drafts", draft_id)
        return Draft(
            id=row["id"],
            topic=row["topic"],
            product=row["product"],
            title=row["title"],
            visual_title=row["visual_title"] or strip_emoji(row["title"]),
            caption_html=row["caption_html"],
            image_prompt=row["image_prompt"],
            image_path=row["image_path"],
            status=row["status"],
            link_url=row["link_url"] or "",
        )

    def mark_published(self, draft_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET status = 'published',
                    published_at = STRFTIME('%Y-%m-%dT%H:%M:%SZ', 'now'),
                    scheduled_at = NULL
                WHERE id = ? AND organization_id = ?
                """,
                (draft_id, self.organization_id),
            )

    def set_telegram_message_id(self, draft_id: int, message_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE drafts SET telegram_message_id = ? WHERE id = ? AND organization_id = ?",
                (message_id, draft_id, self.organization_id),
            )

    def set_draft_image(self, draft_id: int, image_path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE drafts SET image_path = ? WHERE id = ? AND organization_id = ?",
                (image_path, draft_id, self.organization_id),
            )

    def update_draft(
        self,
        draft_id: int,
        *,
        title: str,
        visual_title: str | None = None,
        caption_html: str,
        link_url: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET title = ?, visual_title = ?, caption_html = ?, link_url = ?
                WHERE id = ? AND organization_id = ? AND status != 'published'
                """,
                (
                    title,
                    strip_emoji(visual_title or title) or "Заголовок",
                    caption_html,
                    link_url,
                    draft_id,
                    self.organization_id,
                ),
            )

    def set_draft_favorite(self, draft_id: int, favorite: bool) -> dict:
        with self._connect() as connection:
            connection.execute(
                "UPDATE drafts SET is_favorite = ? WHERE id = ? AND organization_id = ?",
                (int(favorite), draft_id, self.organization_id),
            )
        return self.draft_record(draft_id)

    def favorite_posts(self, limit: int = 8) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, product, title, caption_html, tone
                FROM drafts
                WHERE is_favorite = 1 AND organization_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (self.organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def schedule_draft(self, draft_id: int, scheduled_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET status = 'scheduled', scheduled_at = ?
                WHERE id = ? AND organization_id = ? AND image_path != ''
                """,
                (scheduled_at, draft_id, self.organization_id),
            )

    def transition_draft(self, draft_id: int, status: str) -> dict:
        if status not in CONTENT_STATUSES - {"idea"}:
            raise ValueError("Unsupported content status")
        draft = self.draft_record(draft_id)
        current = draft["status"]
        if current == status:
            return draft
        if status not in CONTENT_STATUS_TRANSITIONS.get(current, set()):
            raise ValueError(f"Invalid content transition: {current} -> {status}")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts SET status = ?
                WHERE id = ? AND organization_id = ?
                """,
                (status, draft_id, self.organization_id),
            )
        return self.draft_record(draft_id)

    def cancel_schedule(self, draft_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET status = 'ready', scheduled_at = NULL
                WHERE id = ? AND organization_id = ? AND status = 'scheduled'
                """,
                (draft_id, self.organization_id),
            )

    def due_scheduled_drafts(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM drafts
                WHERE organization_id = ?
                  AND status = 'scheduled'
                  AND scheduled_at <= STRFTIME('%Y-%m-%dT%H:%M:%SZ', 'now')
                ORDER BY scheduled_at
                """,
                (self.organization_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_drafts(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM drafts WHERE organization_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (self.organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_drafts_page(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        status: str = "",
        rubric: str = "",
        date_from: str = "",
        date_to: str = "",
        sort: str = "created_at",
        direction: str = "desc",
    ) -> dict:
        sort_columns = {
            "created_at": "created_at",
            "title": "title COLLATE NOCASE",
            "status": "status",
            "scheduled_at": "scheduled_at",
        }
        clauses = ["organization_id = ?"]
        params: list[object] = [self.organization_id]
        if search.strip():
            clauses.append("(title LIKE ? OR caption_html LIKE ?)")
            needle = f"%{search.strip()}%"
            params.extend([needle, needle])
        if status:
            clauses.append("status = ?")
            params.append(status)
        if rubric:
            clauses.append("product = ?")
            params.append(rubric)
        if date_from:
            clauses.append("DATE(COALESCE(scheduled_at, created_at)) >= DATE(?)")
            params.append(date_from)
        if date_to:
            clauses.append("DATE(COALESCE(scheduled_at, created_at)) <= DATE(?)")
            params.append(date_to)
        return self._paginate_table(
            "drafts",
            where=" AND ".join(clauses),
            params=params,
            page=page,
            per_page=per_page,
            order_by=sort_columns.get(sort, "created_at"),
            direction=direction,
        )

    def draft_record(self, draft_id: int) -> dict:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "drafts", draft_id)
        return dict(row)

    def delete_draft(self, draft_id: int) -> dict:
        draft = self.draft_record(draft_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM social_variants WHERE draft_id = ? AND organization_id = ?",
                (draft_id, self.organization_id),
            )
            connection.execute(
                "DELETE FROM drafts WHERE id = ? AND organization_id = ?",
                (draft_id, self.organization_id),
            )
        return draft

    def assign_drafts_rubric(self, draft_ids: list[int], rubric_slug: str) -> int:
        self.get_rubric(rubric_slug)
        if not draft_ids:
            return 0
        placeholders = ",".join("?" for _ in draft_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE drafts SET product = ?
                WHERE id IN ({placeholders}) AND organization_id = ?
                """,
                (rubric_slug, *draft_ids, self.organization_id),
            )
        return int(cursor.rowcount)

    def recent_titles(self, limit: int = 20) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT title FROM drafts WHERE organization_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (self.organization_id, limit),
            ).fetchall()
        return [row["title"] for row in rows]

    def repair_draft_markup(self) -> int:
        from voicerhub_bot.rendering import canonicalize_draft_caption, plain_text

        repaired = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, caption_html, link_url,
                    title_options, cta_options
                FROM drafts
                WHERE organization_id = ?
                """,
                (self.organization_id,),
            ).fetchall()
            for row in rows:
                title = plain_text(row["title"])
                caption = canonicalize_draft_caption(
                    row["caption_html"],
                    title,
                    row["link_url"] or "",
                )
                try:
                    title_options = [
                        plain_text(item)
                        for item in json.loads(row["title_options"] or "[]")
                    ]
                except (TypeError, ValueError):
                    title_options = []
                try:
                    cta_options = [
                        plain_text(item)
                        for item in json.loads(row["cta_options"] or "[]")
                    ]
                except (TypeError, ValueError):
                    cta_options = []
                values = (
                    title,
                    caption,
                    json.dumps(title_options, ensure_ascii=False),
                    json.dumps(cta_options, ensure_ascii=False),
                )
                current = (
                    row["title"],
                    row["caption_html"],
                    row["title_options"],
                    row["cta_options"],
                )
                if values == current:
                    continue
                connection.execute(
                    """
                    UPDATE drafts
                    SET title = ?, caption_html = ?,
                        title_options = ?, cta_options = ?
                    WHERE id = ? AND organization_id = ?
                    """,
                    (*values, row["id"], self.organization_id),
                )
                repaired += 1
        return repaired

    def ensure_legacy_rubrics(self, wave_cover_path: str = "") -> None:
        from voicerhub_bot.knowledge import (
            EDITORIAL_RULES,
            PRODUCT_FACTS,
            WAVE_EDITORIAL_RULES,
        )

        defaults = (
            (
                "tony",
                "TONY",
                PRODUCT_FACTS["tony"],
                EDITORIAL_RULES,
                "https://voicerhub.com/ua/products/tony",
                "",
            ),
            (
                "voicer",
                "Voicer",
                PRODUCT_FACTS["voicer"],
                EDITORIAL_RULES,
                "https://voicerhub.com/ua/products/voicer",
                "",
            ),
            (
                "wave",
                "Voicer Wave",
                "Короткі evergreen-факти та спостереження про штучний інтелект.",
                WAVE_EDITORIAL_RULES,
                "",
                wave_cover_path,
            ),
        )
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO content_rubrics (
                    slug, name, description, instructions, default_link,
                    fixed_cover_path, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    instructions = excluded.instructions,
                    default_link = excluded.default_link,
                    fixed_cover_path = CASE
                        WHEN content_rubrics.fixed_cover_path IS NULL
                          OR content_rubrics.fixed_cover_path = ''
                        THEN excluded.fixed_cover_path
                        ELSE content_rubrics.fixed_cover_path
                    END
                """,
                [(*item, self.organization_id) for item in defaults],
            )

    def add_rubric(
        self,
        *,
        slug: str,
        name: str,
        description: str,
        instructions: str = "",
        default_link: str = "",
        goal: str = "",
        tone: str = "",
        example_topic: str = "",
        active: bool = True,
    ) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO content_rubrics (
                    slug, name, description, instructions, default_link,
                    goal, tone, example_topic, active, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug,
                    name,
                    description,
                    instructions,
                    default_link,
                    goal,
                    tone,
                    example_topic,
                    int(active),
                    self.organization_id,
                ),
            )
            rubric_id = int(cursor.lastrowid)
        return self.get_rubric_by_id(rubric_id)

    def update_rubric(
        self,
        rubric_id: int,
        *,
        name: str,
        description: str,
        instructions: str,
        default_link: str,
        active: bool,
        goal: str = "",
        tone: str = "",
        example_topic: str = "",
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE content_rubrics
                SET name = ?, description = ?, instructions = ?,
                    default_link = ?, active = ?, goal = ?, tone = ?,
                    example_topic = ?
                WHERE id = ? AND organization_id = ?
                """,
                (
                    name,
                    description,
                    instructions,
                    default_link,
                    int(active),
                    goal,
                    tone,
                    example_topic,
                    rubric_id,
                    self.organization_id,
                ),
            )
        return self.get_rubric_by_id(rubric_id)

    def get_rubric_by_id(self, rubric_id: int) -> dict:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "content_rubrics", rubric_id)
        return dict(row)

    def get_rubric(self, slug: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM content_rubrics
                WHERE slug = ? AND active = 1 AND organization_id = ?
                """,
                (slug, self.organization_id),
            ).fetchone()
        if row is None:
            raise KeyError(f"Rubric {slug} not found")
        return dict(row)

    def fallback_rubric_slug(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT slug FROM content_rubrics
                WHERE active = 1 AND organization_id = ?
                ORDER BY name COLLATE NOCASE, id
                LIMIT 1
                """,
                (self.organization_id,),
            ).fetchone()
        if row is None:
            raise KeyError("No active rubric found")
        return str(row["slug"])

    def list_rubrics(self, *, include_inactive: bool = False) -> list[dict]:
        query = "SELECT * FROM content_rubrics WHERE organization_id = ?"
        if not include_inactive:
            query += " AND active = 1"
        query += " ORDER BY name COLLATE NOCASE"
        with self._connect() as connection:
            rows = connection.execute(query, (self.organization_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_rubrics_page(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        active: str = "",
        sort: str = "name",
        direction: str = "asc",
    ) -> dict:
        clauses = ["organization_id = ?"]
        params: list[object] = [self.organization_id]
        if search.strip():
            clauses.append("(name LIKE ? OR description LIKE ?)")
            needle = f"%{search.strip()}%"
            params.extend([needle, needle])
        if active in {"yes", "no"}:
            clauses.append("active = ?")
            params.append(1 if active == "yes" else 0)
        return self._paginate_table(
            "content_rubrics",
            where=" AND ".join(clauses),
            params=params,
            page=page,
            per_page=per_page,
            order_by={"name": "name COLLATE NOCASE", "created_at": "created_at"}.get(
                sort,
                "name COLLATE NOCASE",
            ),
            direction=direction,
        )

    def set_rubrics_active(self, rubric_ids: list[int], active: bool) -> int:
        if not rubric_ids:
            return 0
        placeholders = ",".join("?" for _ in rubric_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE content_rubrics SET active = ?
                WHERE id IN ({placeholders}) AND organization_id = ?
                """,
                (int(active), *rubric_ids, self.organization_id),
            )
        return int(cursor.rowcount)

    def delete_rubrics(self, rubric_ids: list[int]) -> int:
        if not rubric_ids:
            return 0
        placeholders = ",".join("?" for _ in rubric_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM content_rubrics
                WHERE id IN ({placeholders}) AND organization_id = ?
                """,
                (*rubric_ids, self.organization_id),
            )
        return int(cursor.rowcount)

    def save_social_variant(
        self,
        *,
        draft_id: int,
        platform: str,
        title: str,
        visual_title: str | None = None,
        text_content: str,
        hashtags: list[str],
        image_prompt: str,
        image_path: str,
        text_model: str,
        image_model: str,
        created_by_user_id: int | None,
    ) -> dict:
        self.draft_record(draft_id)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO social_variants (
                    draft_id, platform, title, visual_title, text_content, hashtags,
                    image_prompt, image_path, text_model, image_model,
                    created_by_user_id, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id, platform) DO UPDATE SET
                    title = excluded.title,
                    visual_title = excluded.visual_title,
                    text_content = excluded.text_content,
                    hashtags = excluded.hashtags,
                    image_prompt = excluded.image_prompt,
                    image_path = excluded.image_path,
                    text_model = excluded.text_model,
                    image_model = excluded.image_model,
                    created_by_user_id = excluded.created_by_user_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    draft_id,
                    platform,
                    title,
                    strip_emoji(visual_title or title) or "Заголовок",
                    text_content,
                    json.dumps(hashtags, ensure_ascii=False),
                    image_prompt,
                    image_path,
                    text_model,
                    image_model,
                    created_by_user_id,
                    self.organization_id,
                ),
            )
        return self.get_social_variant(draft_id, platform)

    def get_social_variant(self, draft_id: int, platform: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM social_variants
                WHERE draft_id = ? AND platform = ?
                """,
                (draft_id, platform),
            ).fetchone()
        if row is None:
            raise KeyError(f"Social variant {platform} not found")
        result = dict(row)
        result["hashtags"] = json.loads(result["hashtags"] or "[]")
        return result

    def list_social_variants(self, draft_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM social_variants
                WHERE draft_id = ?
                ORDER BY platform
                """,
                (draft_id,),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["hashtags"] = json.loads(item["hashtags"] or "[]")
            results.append(item)
        return results

    def create_job(
        self,
        topic: str,
        product: str,
        chat_id: int,
        *,
        text_model: str = "gpt-5.4-mini",
        image_model: str = "gpt-image-2",
        reference_ids: list[int] | None = None,
        template_id: str = "editorial-dark",
        logo_reference_id: int | None = None,
        company_logo_reference_id: int | None = None,
        link_url: str = "",
        idea_id: int | None = None,
        tone: str = "expert",
        created_by_user_id: int | None = None,
        generation_mode: str = "batch",
    ) -> GenerationJob:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO generation_jobs (
                    topic, product, chat_id, text_model, image_model, reference_ids,
                    template_id, logo_reference_id, company_logo_reference_id,
                    link_url, idea_id, tone, created_by_user_id, generation_mode,
                    organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic,
                    product,
                    chat_id,
                    text_model,
                    image_model,
                    json.dumps(reference_ids or []),
                    template_id,
                    logo_reference_id,
                    company_logo_reference_id,
                    link_url,
                    idea_id,
                    tone,
                    created_by_user_id,
                    generation_mode,
                    self.organization_id,
                ),
            )
            job_id = int(cursor.lastrowid)
        return self.get_job(job_id)

    def create_image_job(
        self,
        draft_id: int,
        *,
        image_model: str = "gpt-image-2",
        reference_ids: list[int] | None = None,
        template_id: str = "editorial-dark",
        logo_reference_id: int | None = None,
        company_logo_reference_id: int | None = None,
        created_by_user_id: int | None = None,
        generation_mode: str = "batch",
    ) -> GenerationJob:
        draft = self.get(draft_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET status = 'draft', scheduled_at = NULL
                WHERE id = ?
                """,
                (draft_id,),
            )
            cursor = connection.execute(
                """
                INSERT INTO generation_jobs (
                    topic, product, chat_id, status, draft_id,
                    text_model, image_model, reference_ids, template_id,
                    logo_reference_id, company_logo_reference_id, link_url,
                    created_by_user_id, generation_mode, organization_id
                ) VALUES (?, ?, 0, 'queued_image', ?, '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.topic,
                    draft.product,
                    draft_id,
                    image_model,
                    json.dumps(reference_ids or []),
                    template_id,
                    logo_reference_id,
                    company_logo_reference_id,
                    draft.link_url,
                    created_by_user_id,
                    generation_mode,
                    self.organization_id,
                ),
            )
            job_id = int(cursor.lastrowid)
        return self.get_job(job_id)

    def add_ideas(self, ideas: list[dict]) -> list[dict]:
        ids: list[int] = []
        with self._connect() as connection:
            for idea in ideas:
                cursor = connection.execute(
                    """
                    INSERT INTO content_ideas (
                        product, title, angle, status, planned_for, tone, series_id,
                        series_title, series_part, source_url, duplicate_score,
                        duplicate_of, plan_id, organization_id
                    ) VALUES (?, ?, ?, 'idea', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idea["product"],
                        idea["title"],
                        idea["angle"],
                        idea.get("planned_for") or None,
                        idea.get("tone", "expert"),
                        idea.get("series_id"),
                        idea.get("series_title", ""),
                        idea.get("series_part", 0),
                        idea.get("source_url", ""),
                        idea.get("duplicate_score", 0),
                        idea.get("duplicate_of"),
                        idea.get("plan_id"),
                        self.organization_id,
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return [self.get_idea(idea_id) for idea_id in ids]

    def create_content_plan(
        self,
        *,
        plan_id: str,
        period: str,
        start_date: str,
        posts: int,
        objective: str,
        create_as: str,
        rubric_slugs: list[str],
        channel_ids: list[str],
        created_by_user_id: int | None,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO content_plans (
                    id, period, start_date, posts, objective, create_as,
                    rubric_slugs, channel_ids, created_by_user_id, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    period,
                    start_date,
                    posts,
                    objective,
                    create_as,
                    json.dumps(rubric_slugs, ensure_ascii=False),
                    json.dumps(channel_ids, ensure_ascii=False),
                    created_by_user_id,
                    self.organization_id,
                ),
            )
        return self.get_content_plan(plan_id)

    def get_content_plan(self, plan_id: str) -> dict:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "content_plans", plan_id)
        return dict(row)

    def list_content_plans(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM content_plans WHERE organization_id = ?
                ORDER BY created_at DESC
                """,
                (self.organization_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_content_series(
        self,
        *,
        series_id: str,
        title: str,
        parts: int,
        rubric_slug: str,
        created_by_user_id: int | None,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO content_series (
                    id, title, parts, rubric_slug, created_by_user_id, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    series_id,
                    title,
                    parts,
                    rubric_slug,
                    created_by_user_id,
                    self.organization_id,
                ),
            )
            row = self._ensure_owned(connection, "content_series", series_id)
        return dict(row)

    def get_idea(self, idea_id: int) -> dict:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "content_ideas", idea_id)
        return dict(row)

    def list_ideas(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM content_ideas WHERE organization_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (self.organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_ideas_page(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        rubric: str = "",
        plan_only: bool = False,
        date_from: str = "",
        date_to: str = "",
        sort: str = "created_at",
        direction: str = "desc",
    ) -> dict:
        clauses = ["organization_id = ?"]
        params: list[object] = [self.organization_id]
        if search.strip():
            clauses.append("(title LIKE ? OR angle LIKE ?)")
            needle = f"%{search.strip()}%"
            params.extend([needle, needle])
        if rubric and rubric != "all":
            clauses.append("product = ?")
            params.append(rubric)
        if plan_only:
            clauses.append("plan_id IS NOT NULL")
        if date_from:
            clauses.append("DATE(COALESCE(planned_for, created_at)) >= DATE(?)")
            params.append(date_from)
        if date_to:
            clauses.append("DATE(COALESCE(planned_for, created_at)) <= DATE(?)")
            params.append(date_to)
        return self._paginate_table(
            "content_ideas",
            where=" AND ".join(clauses),
            params=params,
            page=page,
            per_page=per_page,
            order_by={
                "created_at": "created_at",
                "title": "title COLLATE NOCASE",
                "planned_for": "planned_for",
                "status": "status",
            }.get(sort, "created_at"),
            direction=direction,
        )

    def all_idea_signatures(self, limit: int = 1000) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, angle
                FROM content_ideas
                WHERE organization_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (self.organization_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def select_idea(
        self,
        idea_id: int,
        *,
        text_model: str = "gpt-5.4-mini",
        image_model: str = "gpt-image-2",
        reference_ids: list[int] | None = None,
        template_id: str = "editorial-dark",
        logo_reference_id: int | None = None,
        company_logo_reference_id: int | None = None,
        link_url: str = "",
        tone: str | None = None,
        created_by_user_id: int | None = None,
        generation_mode: str = "batch",
    ) -> GenerationJob:
        idea = self.get_idea(idea_id)
        product = str(idea["product"] or "")
        try:
            self.get_rubric(product)
        except KeyError:
            product = self.fallback_rubric_slug()
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE content_ideas
                    SET product = ?
                    WHERE id = ? AND organization_id = ?
                    """,
                    (product, idea_id, self.organization_id),
                )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE content_ideas SET status = 'idea'
                WHERE id = ? AND organization_id = ?
                """,
                (idea_id, self.organization_id),
            )
        topic = f"{idea['title']}. {idea['angle']}"
        return self.create_job(
            topic,
            product,
            0,
            text_model=text_model,
            image_model=image_model,
            reference_ids=reference_ids,
            template_id=template_id,
            logo_reference_id=logo_reference_id,
            company_logo_reference_id=company_logo_reference_id,
            link_url=link_url,
            idea_id=idea_id,
            tone=tone or idea.get("tone") or "expert",
            created_by_user_id=created_by_user_id,
            generation_mode=generation_mode,
        )

    def delete_idea(self, idea_id: int) -> None:
        self.get_idea(idea_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM content_ideas WHERE id = ? AND organization_id = ?",
                (idea_id, self.organization_id),
            )

    def delete_ideas(self, idea_ids: list[int]) -> int:
        if not idea_ids:
            return 0
        placeholders = ",".join("?" for _ in idea_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                DELETE FROM content_ideas
                WHERE id IN ({placeholders}) AND organization_id = ?
                """,
                (*idea_ids, self.organization_id),
            )
        return int(cursor.rowcount)

    def assign_ideas_rubric(self, idea_ids: list[int], rubric_slug: str) -> int:
        self.get_rubric(rubric_slug)
        if not idea_ids:
            return 0
        placeholders = ",".join("?" for _ in idea_ids)
        with self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE content_ideas SET product = ?
                WHERE id IN ({placeholders}) AND organization_id = ?
                """,
                (rubric_slug, *idea_ids, self.organization_id),
            )
        return int(cursor.rowcount)

    def add_custom_template(
        self,
        *,
        template_id: str,
        name: str,
        description: str,
        prompt: str,
        layout: str,
        accent: str,
        mood: str = "",
        use_rules: str = "",
        avoid_rules: str = "",
        prompt_examples: str = "",
        active: bool = True,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO custom_visual_templates (
                    id, name, description, prompt, layout, accent, mood,
                    use_rules, avoid_rules, prompt_examples, active, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_id,
                    name,
                    description,
                    prompt,
                    layout,
                    accent,
                    mood,
                    use_rules,
                    avoid_rules,
                    prompt_examples,
                    int(active),
                    self.organization_id,
                ),
            )
        return self.get_custom_template(template_id)

    def get_custom_template(self, template_id: str) -> dict:
        with self._connect() as connection:
            row = self._ensure_owned(
                connection,
                "custom_visual_templates",
                template_id,
            )
        return dict(row)

    def list_custom_templates(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM custom_visual_templates WHERE organization_id = ?
                ORDER BY created_at DESC
                """,
                (self.organization_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_custom_template(self, template_id: str, **values: object) -> dict:
        self.get_custom_template(template_id)
        allowed = {
            "name",
            "description",
            "prompt",
            "layout",
            "accent",
            "mood",
            "use_rules",
            "avoid_rules",
            "prompt_examples",
            "active",
        }
        values = {key: value for key, value in values.items() if key in allowed}
        if "active" in values:
            values["active"] = int(bool(values["active"]))
        if values:
            assignments = ", ".join(f"{key} = ?" for key in values)
            with self._connect() as connection:
                connection.execute(
                    f"""
                    UPDATE custom_visual_templates
                    SET {assignments}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND organization_id = ?
                    """,
                    (*values.values(), template_id, self.organization_id),
                )
        return self.get_custom_template(template_id)

    def list_custom_templates_page(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        active: str = "",
    ) -> dict:
        clauses = ["organization_id = ?"]
        params: list[object] = [self.organization_id]
        if search.strip():
            clauses.append("(name LIKE ? OR description LIKE ?)")
            needle = f"%{search.strip()}%"
            params.extend([needle, needle])
        if active in {"yes", "no"}:
            clauses.append("active = ?")
            params.append(1 if active == "yes" else 0)
        return self._paginate_table(
            "custom_visual_templates",
            where=" AND ".join(clauses),
            params=params,
            page=page,
            per_page=per_page,
            order_by="created_at",
            direction="desc",
        )

    def set_template_preview(self, template_id: str, preview_path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE custom_visual_templates SET preview_path = ? WHERE id = ? AND organization_id = ?",
                (preview_path, template_id, self.organization_id),
            )

    def delete_custom_template(self, template_id: str) -> dict:
        template = self.get_custom_template(template_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM custom_visual_templates WHERE id = ? AND organization_id = ?",
                (template_id, self.organization_id),
            )
        return template

    def add_reference(
        self,
        *,
        name: str,
        filename: str,
        path: str,
        media_type: str,
        material_type: str = "reference_image",
        description: str = "",
        source_url: str = "",
        active: bool = True,
        created_by_user_id: int | None = None,
    ) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reference_assets (
                    name, filename, path, media_type, material_type,
                    description, source_url, active, created_by_user_id,
                    updated_at, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    name,
                    filename,
                    path,
                    media_type,
                    material_type,
                    description,
                    source_url,
                    int(active),
                    created_by_user_id,
                    self.organization_id,
                ),
            )
            reference_id = int(cursor.lastrowid)
        return self.get_reference(reference_id)

    def get_reference(self, reference_id: int) -> dict:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "reference_assets", reference_id)
        return dict(row)

    def list_references(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM reference_assets WHERE organization_id = ?
                ORDER BY id DESC
                """,
                (self.organization_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_references_page(
        self,
        *,
        page: int = 1,
        per_page: int = 25,
        search: str = "",
        material_type: str = "",
        active: str = "",
    ) -> dict:
        clauses = ["organization_id = ?"]
        params: list[object] = [self.organization_id]
        if search.strip():
            clauses.append("(name LIKE ? OR description LIKE ?)")
            needle = f"%{search.strip()}%"
            params.extend([needle, needle])
        if material_type:
            clauses.append("material_type = ?")
            params.append(material_type)
        if active in {"yes", "no"}:
            clauses.append("active = ?")
            params.append(1 if active == "yes" else 0)
        return self._paginate_table(
            "reference_assets",
            where=" AND ".join(clauses),
            params=params,
            page=page,
            per_page=per_page,
            order_by="created_at",
            direction="desc",
        )

    def update_reference(self, reference_id: int, **values: object) -> dict:
        self.get_reference(reference_id)
        allowed = {"name", "description", "material_type", "source_url", "active"}
        values = {key: value for key, value in values.items() if key in allowed}
        if "active" in values:
            values["active"] = int(bool(values["active"]))
        if values:
            assignments = ", ".join(f"{key} = ?" for key in values)
            with self._connect() as connection:
                connection.execute(
                    f"""
                    UPDATE reference_assets
                    SET {assignments}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND organization_id = ?
                    """,
                    (*values.values(), reference_id, self.organization_id),
                )
        return self.get_reference(reference_id)

    def references_by_ids(self, reference_ids: list[int]) -> list[dict]:
        if not reference_ids:
            return []
        placeholders = ",".join("?" for _ in reference_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM reference_assets
                WHERE id IN ({placeholders}) AND organization_id = ?
                ORDER BY id
                """,
                (*reference_ids, self.organization_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_reference(self, reference_id: int) -> dict:
        reference = self.get_reference(reference_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM reference_assets WHERE id = ? AND organization_id = ?",
                (reference_id, self.organization_id),
            )
        return reference

    def delete_job(self, job_id: int) -> dict:
        job = self.get_job(job_id)
        if job.status not in {"failed", "cancelled"}:
            raise ValueError("Видалити можна лише помилкове або скасоване завдання")
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM generation_jobs
                WHERE id = ? AND organization_id = ?
                """,
                (job_id, self.organization_id),
            )
        return {"id": job.id, "status": job.status}

    def _paginate_table(
        self,
        table: str,
        *,
        where: str,
        params: list[object],
        page: int,
        per_page: int,
        order_by: str,
        direction: str,
    ) -> dict:
        page = max(1, int(page))
        per_page = min(100, max(1, int(per_page)))
        direction = "ASC" if direction.lower() == "asc" else "DESC"
        with self._connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {where}",
                    params,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM {table}
                WHERE {where}
                ORDER BY {order_by} {direction}
                LIMIT ? OFFSET ?
                """,
                (*params, per_page, (page - 1) * per_page),
            ).fetchall()
        total_pages = max(1, (total + per_page - 1) // per_page)
        return {
            "items": [dict(row) for row in rows],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }

    def get_job(self, job_id: int) -> GenerationJob:
        with self._connect() as connection:
            row = self._ensure_owned(connection, "generation_jobs", job_id)
        return self._job_from_row(row)

    def jobs_with_status(self, *statuses: str) -> list[GenerationJob]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM generation_jobs
                WHERE status IN ({placeholders}) AND organization_id = ?
                ORDER BY id
                """,
                (*statuses, self.organization_id),
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def update_job(self, job_id: int, *, status: str, **fields: object) -> None:
        allowed = {
            "text_batch_id",
            "image_batch_id",
            "draft_id",
            "error",
            "generation_mode",
        }
        assignments = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: list[object] = [status]
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported job field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.extend([job_id, self.organization_id])
        with self._connect() as connection:
            connection.execute(
                f"UPDATE generation_jobs SET {', '.join(assignments)} "
                "WHERE id = ? AND organization_id = ?",
                values,
            )

    def upsert_batch(self, batch: BatchRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_runs (
                    id, kind, status, total, completed, failed,
                    input_tokens, output_tokens, estimated_cost, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    total = excluded.total,
                    completed = excluded.completed,
                    failed = excluded.failed,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    estimated_cost = excluded.estimated_cost,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    batch.id,
                    batch.kind,
                    batch.status,
                    batch.total,
                    batch.completed,
                    batch.failed,
                    batch.input_tokens,
                    batch.output_tokens,
                    batch.estimated_cost,
                    self.organization_id,
                ),
            )

    def add_usage(
        self,
        *,
        job_id: int,
        kind: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        units: int = 0,
        cost: float,
        user_id: int | None = None,
    ) -> None:
        with self._connect() as connection:
            if user_id is None and job_id > 0:
                row = connection.execute(
                    "SELECT created_by_user_id FROM generation_jobs "
                    "WHERE id = ? AND organization_id = ?",
                    (job_id, self.organization_id),
                ).fetchone()
                user_id = row["created_by_user_id"] if row else None
            connection.execute(
                """
                INSERT INTO usage_events (
                    job_id, kind, model, input_tokens, output_tokens, units, cost,
                    user_id, organization_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    kind,
                    model,
                    input_tokens,
                    output_tokens,
                    units,
                    cost,
                    user_id,
                    self.organization_id,
                ),
            )

    def has_usage(self, job_id: int, kind: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM usage_events
                WHERE job_id = ? AND kind = ? AND organization_id = ?
                LIMIT 1
                """,
                (job_id, kind, self.organization_id),
            ).fetchone()
        return row is not None

    def usage_summary(self, *, since: str | None = None) -> dict:
        where = "WHERE organization_id = ?"
        params: tuple[object, ...] = (self.organization_id,)
        if since:
            where += " AND created_at >= ?"
            params += (since,)
        with self._connect() as connection:
            totals = connection.execute(
                f"""
                SELECT
                    COUNT(*) operations,
                    COALESCE(SUM(input_tokens), 0) input_tokens,
                    COALESCE(SUM(output_tokens), 0) output_tokens,
                    COALESCE(SUM(CASE WHEN kind = 'text' THEN 1 ELSE 0 END), 0)
                        text_generations,
                    COALESCE(SUM(CASE WHEN kind = 'image' THEN units ELSE 0 END), 0)
                        image_generations,
                    COALESCE(SUM(cost), 0) cost
                FROM usage_events
                {where}
                """,
                params,
            ).fetchone()
            users = connection.execute(
                f"""
                SELECT
                    user_id,
                    COUNT(*) operations,
                    COALESCE(SUM(input_tokens), 0) input_tokens,
                    COALESCE(SUM(output_tokens), 0) output_tokens,
                    COALESCE(SUM(CASE WHEN kind = 'text' THEN 1 ELSE 0 END), 0)
                        text_generations,
                    COALESCE(SUM(CASE WHEN kind = 'image' THEN units ELSE 0 END), 0)
                        image_generations,
                    COALESCE(SUM(cost), 0) cost
                FROM usage_events
                {where}
                GROUP BY user_id
                ORDER BY cost DESC, operations DESC
                """,
                params,
            ).fetchall()
            models = connection.execute(
                f"""
                SELECT
                    model,
                    kind,
                    COUNT(*) operations,
                    COALESCE(SUM(input_tokens), 0) input_tokens,
                    COALESCE(SUM(output_tokens), 0) output_tokens,
                    COALESCE(SUM(units), 0) units,
                    COALESCE(SUM(cost), 0) cost
                FROM usage_events
                {where}
                GROUP BY model, kind
                ORDER BY cost DESC, operations DESC
                """,
                params,
            ).fetchall()
        return {
            "totals": dict(totals),
            "users": [dict(row) for row in users],
            "models": [dict(row) for row in models],
        }

    def usage_by_rubric(self, *, since: str | None = None) -> list[dict]:
        conditions = [
            "u.job_id = j.id",
            "u.organization_id = ?",
            "j.organization_id = ?",
        ]
        params: list[object] = [self.organization_id, self.organization_id]
        if since:
            conditions.append("u.created_at >= ?")
            params.append(since)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT j.product rubric_slug,
                    COUNT(u.id) operations,
                    COALESCE(SUM(u.cost), 0) cost
                FROM usage_events u
                JOIN generation_jobs j ON {' AND '.join(conditions)}
                GROUP BY j.product
                ORDER BY cost DESC, operations DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def current_month_cost(self) -> float:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(cost), 0)
                FROM usage_events
                WHERE organization_id = ?
                  AND STRFTIME('%Y-%m', created_at) =
                    STRFTIME('%Y-%m', 'now')
                """,
                (self.organization_id,),
            ).fetchone()
        return float(row[0] or 0)

    def current_month_publications(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM drafts
                WHERE organization_id = ?
                  AND status = 'published'
                  AND STRFTIME('%Y-%m', published_at) =
                    STRFTIME('%Y-%m', 'now')
                """,
                (self.organization_id,),
            ).fetchone()
        return int(row[0] or 0)

    def dashboard(self) -> dict:
        with self._connect() as connection:
            job_counts = connection.execute(
                "SELECT status, COUNT(*) count FROM generation_jobs "
                "WHERE organization_id = ? GROUP BY status",
                (self.organization_id,),
            ).fetchall()
            batches = connection.execute(
                "SELECT * FROM batch_runs WHERE organization_id = ? "
                "ORDER BY created_at DESC LIMIT 50",
                (self.organization_id,),
            ).fetchall()
            jobs = connection.execute(
                "SELECT * FROM generation_jobs WHERE organization_id = ? "
                "ORDER BY id DESC LIMIT 500",
                (self.organization_id,),
            ).fetchall()
            drafts = connection.execute(
                "SELECT * FROM drafts WHERE organization_id = ? "
                "ORDER BY id DESC LIMIT 500",
                (self.organization_id,),
            ).fetchall()
            ideas = connection.execute(
                """
                SELECT i.*,
                    CASE
                        WHEN j.status IN (
                            'queued_text', 'text_batch', 'queued_image',
                            'image_batch', 'failed'
                        ) THEN j.status
                        WHEN d.id IS NOT NULL THEN d.status
                        ELSE COALESCE(j.status, i.status)
                    END effective_status,
                    j.id job_id,
                    j.draft_id,
                    j.error
                FROM content_ideas i
                LEFT JOIN generation_jobs j ON j.id = (
                    SELECT MAX(latest.id)
                    FROM generation_jobs latest
                    WHERE latest.idea_id = i.id
                      AND latest.organization_id = i.organization_id
                )
                LEFT JOIN drafts d ON d.id = j.draft_id
                    AND d.organization_id = i.organization_id
                WHERE i.organization_id = ?
                ORDER BY i.id DESC LIMIT 500
                """,
                (self.organization_id,),
            ).fetchall()
            totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(cost), 0) total_cost,
                    COALESCE(SUM(CASE WHEN kind = 'text' THEN cost ELSE 0 END), 0) text_cost,
                    COALESCE(SUM(CASE WHEN kind = 'image' THEN cost ELSE 0 END), 0) image_cost
                FROM usage_events
                WHERE organization_id = ?
                """,
                (self.organization_id,),
            ).fetchone()
            daily = connection.execute(
                """
                SELECT DATE(created_at) day, SUM(cost) cost
                FROM usage_events
                WHERE organization_id = ?
                GROUP BY DATE(created_at)
                ORDER BY day DESC LIMIT 30
                """,
                (self.organization_id,),
            ).fetchall()
        return {
            "job_counts": {row["status"]: row["count"] for row in job_counts},
            "batches": [dict(row) for row in batches],
            "jobs": [
                {
                    **dict(row),
                    **generation_progress(row["status"]),
                }
                for row in jobs
            ],
            "drafts": [dict(row) for row in drafts],
            "ideas": [
                {
                    **dict(row),
                    "status": row["effective_status"],
                    **generation_progress(row["effective_status"]),
                }
                for row in ideas
            ],
            "references": self.list_references(),
            "totals": dict(totals),
            "daily": [dict(row) for row in daily],
        }

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> GenerationJob:
        return GenerationJob(
            id=row["id"],
            topic=row["topic"],
            product=row["product"],
            chat_id=row["chat_id"],
            status=row["status"],
            text_batch_id=row["text_batch_id"],
            image_batch_id=row["image_batch_id"],
            draft_id=row["draft_id"],
            error=row["error"],
            text_model=row["text_model"] or "gpt-5.4-mini",
            image_model=row["image_model"] or "gpt-image-2",
            reference_ids=row["reference_ids"] or "[]",
            template_id=row["template_id"] or "editorial-dark",
            logo_reference_id=row["logo_reference_id"],
            company_logo_reference_id=row["company_logo_reference_id"],
            link_url=row["link_url"] or "",
            tone=row["tone"] or "expert",
            created_by_user_id=row["created_by_user_id"],
            generation_mode=row["generation_mode"] or "batch",
        )


class TenantRepository:
    def __init__(self, legacy_database_path: Path, organizations_dir: Path) -> None:
        self.legacy_database_path = legacy_database_path
        self.organizations_dir = organizations_dir
        self._organization_id: ContextVar[int] = ContextVar(
            "content_studio_organization_id",
            default=1,
        )
        self._repositories: dict[int, DraftRepository] = {
            1: DraftRepository(legacy_database_path, organization_id=1)
        }

    @property
    def organization_id(self) -> int:
        return self._organization_id.get()

    def use(self, organization_id: int) -> DraftRepository:
        self._organization_id.set(organization_id)
        return self.for_organization(organization_id)

    def for_organization(self, organization_id: int) -> DraftRepository:
        if organization_id not in self._repositories:
            directory = self.organizations_dir / str(organization_id)
            directory.mkdir(parents=True, exist_ok=True)
            self._repositories[organization_id] = DraftRepository(
                directory / "content.sqlite3",
                organization_id=organization_id,
            )
        return self._repositories[organization_id]

    def forget(self, organization_id: int) -> None:
        if organization_id == 1:
            return
        self._repositories.pop(organization_id, None)

    def __getattr__(self, name: str):
        return getattr(self.for_organization(self.organization_id), name)
