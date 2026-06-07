import json
import sqlite3
from contextvars import ContextVar
from pathlib import Path

from voicerhub_bot.models import BatchRecord, Draft, GenerationJob


class DraftRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
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
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

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
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def create(
        self,
        *,
        topic: str,
        product: str,
        title: str,
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
                    topic, product, title, caption_html, image_prompt, image_path,
                    link_url, title_options, cta_options, tone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic,
                    product,
                    title,
                    caption_html,
                    image_prompt,
                    image_path,
                    link_url,
                    json.dumps(title_options or [], ensure_ascii=False),
                    json.dumps(cta_options or [], ensure_ascii=False),
                    tone,
                ),
            )
            draft_id = int(cursor.lastrowid)
        return self.get(draft_id)

    def get(self, draft_id: int) -> Draft:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(f"Draft {draft_id} not found")
        return Draft(
            id=row["id"],
            topic=row["topic"],
            product=row["product"],
            title=row["title"],
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
                WHERE id = ?
                """,
                (draft_id,),
            )

    def set_telegram_message_id(self, draft_id: int, message_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE drafts SET telegram_message_id = ? WHERE id = ?",
                (message_id, draft_id),
            )

    def set_draft_image(self, draft_id: int, image_path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE drafts SET image_path = ? WHERE id = ?",
                (image_path, draft_id),
            )

    def update_draft(
        self,
        draft_id: int,
        *,
        title: str,
        caption_html: str,
        link_url: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET title = ?, caption_html = ?, link_url = ?
                WHERE id = ? AND status != 'published'
                """,
                (title, caption_html, link_url, draft_id),
            )

    def set_draft_favorite(self, draft_id: int, favorite: bool) -> dict:
        with self._connect() as connection:
            connection.execute(
                "UPDATE drafts SET is_favorite = ? WHERE id = ?",
                (int(favorite), draft_id),
            )
        return self.draft_record(draft_id)

    def favorite_posts(self, limit: int = 8) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, product, title, caption_html, tone
                FROM drafts
                WHERE is_favorite = 1
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def schedule_draft(self, draft_id: int, scheduled_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET status = 'scheduled', scheduled_at = ?
                WHERE id = ? AND image_path != ''
                """,
                (scheduled_at, draft_id),
            )

    def cancel_schedule(self, draft_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE drafts
                SET status = 'draft', scheduled_at = NULL
                WHERE id = ? AND status = 'scheduled'
                """,
                (draft_id,),
            )

    def due_scheduled_drafts(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM drafts
                WHERE status = 'scheduled'
                  AND scheduled_at <= STRFTIME('%Y-%m-%dT%H:%M:%SZ', 'now')
                ORDER BY scheduled_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_drafts(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM drafts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def draft_record(self, draft_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM drafts WHERE id = ?",
                (draft_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Draft {draft_id} not found")
        return dict(row)

    def recent_titles(self, limit: int = 20) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT title FROM drafts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [row["title"] for row in rows]

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
    ) -> GenerationJob:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO generation_jobs (
                    topic, product, chat_id, text_model, image_model, reference_ids,
                    template_id, logo_reference_id, company_logo_reference_id,
                    link_url, idea_id, tone
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    logo_reference_id, company_logo_reference_id, link_url
                ) VALUES (?, ?, 0, 'queued_image', ?, '', ?, ?, ?, ?, ?, ?)
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
                        product, title, angle, planned_for, tone, series_id,
                        series_title, series_part, source_url, duplicate_score,
                        duplicate_of, plan_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return [self.get_idea(idea_id) for idea_id in ids]

    def get_idea(self, idea_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM content_ideas WHERE id = ?",
                (idea_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Idea {idea_id} not found")
        return dict(row)

    def list_ideas(self, limit: int = 100) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM content_ideas ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_idea_signatures(self, limit: int = 1000) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, angle
                FROM content_ideas
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
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
    ) -> GenerationJob:
        idea = self.get_idea(idea_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_ideas SET status = 'selected' WHERE id = ?",
                (idea_id,),
            )
        topic = f"{idea['title']}. {idea['angle']}"
        return self.create_job(
            topic,
            idea["product"],
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
        )

    def delete_idea(self, idea_id: int) -> None:
        self.get_idea(idea_id)
        with self._connect() as connection:
            connection.execute("DELETE FROM content_ideas WHERE id = ?", (idea_id,))

    def add_custom_template(
        self,
        *,
        template_id: str,
        name: str,
        description: str,
        prompt: str,
        layout: str,
        accent: str,
    ) -> dict:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO custom_visual_templates (
                    id, name, description, prompt, layout, accent
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (template_id, name, description, prompt, layout, accent),
            )
        return self.get_custom_template(template_id)

    def get_custom_template(self, template_id: str) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM custom_visual_templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Template {template_id} not found")
        return dict(row)

    def list_custom_templates(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM custom_visual_templates ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_template_preview(self, template_id: str, preview_path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE custom_visual_templates SET preview_path = ? WHERE id = ?",
                (preview_path, template_id),
            )

    def delete_custom_template(self, template_id: str) -> dict:
        template = self.get_custom_template(template_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM custom_visual_templates WHERE id = ?",
                (template_id,),
            )
        return template

    def add_reference(
        self, *, name: str, filename: str, path: str, media_type: str
    ) -> dict:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO reference_assets (name, filename, path, media_type)
                VALUES (?, ?, ?, ?)
                """,
                (name, filename, path, media_type),
            )
            reference_id = int(cursor.lastrowid)
        return self.get_reference(reference_id)

    def get_reference(self, reference_id: int) -> dict:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM reference_assets WHERE id = ?", (reference_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Reference {reference_id} not found")
        return dict(row)

    def list_references(self) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM reference_assets ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def references_by_ids(self, reference_ids: list[int]) -> list[dict]:
        if not reference_ids:
            return []
        placeholders = ",".join("?" for _ in reference_ids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM reference_assets WHERE id IN ({placeholders}) ORDER BY id",
                reference_ids,
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_reference(self, reference_id: int) -> dict:
        reference = self.get_reference(reference_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM reference_assets WHERE id = ?", (reference_id,)
            )
        return reference

    def get_job(self, job_id: int) -> GenerationJob:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"Job {job_id} not found")
        return self._job_from_row(row)

    def jobs_with_status(self, *statuses: str) -> list[GenerationJob]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_jobs WHERE status IN ({placeholders}) ORDER BY id",
                statuses,
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def update_job(self, job_id: int, *, status: str, **fields: object) -> None:
        allowed = {"text_batch_id", "image_batch_id", "draft_id", "error"}
        assignments = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: list[object] = [status]
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported job field: {key}")
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE generation_jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def upsert_batch(self, batch: BatchRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO batch_runs (
                    id, kind, status, total, completed, failed,
                    input_tokens, output_tokens, estimated_cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO usage_events (
                    job_id, kind, model, input_tokens, output_tokens, units, cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (job_id, kind, model, input_tokens, output_tokens, units, cost),
            )

    def current_month_cost(self) -> float:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(cost), 0)
                FROM usage_events
                WHERE STRFTIME('%Y-%m', created_at) =
                    STRFTIME('%Y-%m', 'now')
                """
            ).fetchone()
        return float(row[0] or 0)

    def current_month_publications(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM drafts
                WHERE status = 'published'
                  AND STRFTIME('%Y-%m', published_at) =
                    STRFTIME('%Y-%m', 'now')
                """
            ).fetchone()
        return int(row[0] or 0)

    def dashboard(self) -> dict:
        with self._connect() as connection:
            job_counts = connection.execute(
                "SELECT status, COUNT(*) count FROM generation_jobs GROUP BY status"
            ).fetchall()
            batches = connection.execute(
                "SELECT * FROM batch_runs ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            jobs = connection.execute(
                "SELECT * FROM generation_jobs ORDER BY id DESC LIMIT 500"
            ).fetchall()
            drafts = connection.execute(
                "SELECT * FROM drafts ORDER BY id DESC LIMIT 500"
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
                    j.draft_id
                FROM content_ideas i
                LEFT JOIN generation_jobs j ON j.idea_id = i.id
                LEFT JOIN drafts d ON d.id = j.draft_id
                ORDER BY i.id DESC LIMIT 500
                """
            ).fetchall()
            totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(cost), 0) total_cost,
                    COALESCE(SUM(CASE WHEN kind = 'text' THEN cost ELSE 0 END), 0) text_cost,
                    COALESCE(SUM(CASE WHEN kind = 'image' THEN cost ELSE 0 END), 0) image_cost
                FROM usage_events
                """
            ).fetchone()
            daily = connection.execute(
                """
                SELECT DATE(created_at) day, SUM(cost) cost
                FROM usage_events
                GROUP BY DATE(created_at)
                ORDER BY day DESC LIMIT 30
                """
            ).fetchall()
        return {
            "job_counts": {row["status"]: row["count"] for row in job_counts},
            "batches": [dict(row) for row in batches],
            "jobs": [dict(row) for row in jobs],
            "drafts": [dict(row) for row in drafts],
            "ideas": [
                {
                    **dict(row),
                    "status": row["effective_status"],
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
            1: DraftRepository(legacy_database_path)
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
                directory / "content.sqlite3"
            )
        return self._repositories[organization_id]

    def __getattr__(self, name: str):
        return getattr(self.for_organization(self.organization_id), name)
