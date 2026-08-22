"""add searchable built-in targets

Revision ID: b7e2c18d4a91
Revises: ac1234bc49c6
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b7e2c18d4a91"
down_revision: Union[str, None] = "ac1234bc49c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE targets ALTER COLUMN kind TYPE VARCHAR(16)")
    op.execute(
        """
        INSERT INTO targets (
            workspace_id, name, kind, enabled, method, url, headers,
            status_ranges, required_literals, forbidden_literals,
            required_patterns, forbidden_patterns, id, created_at, updated_at
        )
        SELECT w.id, preset.name, preset.kind, true, 'GET', preset.url, '{}',
               '[[200,399]]', '[]', '[]', '[]', '[]', gen_random_uuid(), now(), now()
        FROM workspaces w
        CROSS JOIN (VALUES
            ('Brave Search', 'brave', 'https://search.brave.com/search?q=proxyhide-health-check'),
            ('Startpage', 'startpage', 'https://www.startpage.com/sp/search?query=proxyhide-health-check'),
            ('DuckDuckGo', 'duckduckgo', 'https://duckduckgo.com/html/?q=proxyhide-health-check'),
            ('Wikipedia Search', 'wikipedia', 'https://en.wikipedia.org/w/index.php?search=proxyhide-health-check')
        ) AS preset(name, kind, url)
        WHERE NOT EXISTS (
            SELECT 1 FROM targets t WHERE t.workspace_id = w.id AND t.kind = preset.kind
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM targets WHERE kind IN ('brave', 'startpage', 'duckduckgo', 'wikipedia')"
    )
    op.execute("ALTER TABLE targets ALTER COLUMN kind TYPE VARCHAR(6)")
