import os
import glob
import asyncio
import asyncpg
import logging
from datetime import datetime

logger = logging.getLogger("db")


class Database:
    def __init__(self):
        self.conn = None

    async def connect(self):
        if self.conn is None or self.conn.is_closed():
            db_name = os.environ.get('DB_NAME')
            db_user = os.environ.get('DB_USER')
            db_host = os.environ.get('DB_HOST')
            logger.info("Connecting to DB '%s' as '%s' at '%s'", db_name, db_user, db_host)
            self.conn = await asyncpg.connect(
                database=db_name,
                user=db_user,
                password=os.environ.get('DB_PASSWORD'),
                host=db_host
            )
            logger.info("DB connection established")

    async def ping(self):
        try:
            await self.connect()
            row = await self.conn.fetchrow("SELECT current_database() AS db, version() AS ver")
            db = row['db'] if row and 'db' in row else 'unknown'
            ver = row['ver'].split()[0] if row and 'ver' in row else 'unknown'
            return True, f"{db} | PostgreSQL {ver}"
        except Exception as e:
            logger.error("DB ping failed: %s", e)
            return False, str(e)

    async def fetch_expired_roles(self):
        await self.connect()
        return await self.conn.fetch("""
            SELECT r1.user_id, r1.role 
            FROM roles r1
            WHERE NOW() > r1.expiration
            AND NOT EXISTS (
                SELECT 1 FROM roles r2 
                WHERE r2.user_id = r1.user_id 
                AND r2.role = r1.role 
                AND NOW() <= r2.expiration
            )
        """)

    async def fetch_expired_roles_for_user(self, user_id):
        await self.connect()
        return await self.conn.fetch("""
            SELECT DISTINCT r1.role 
            FROM roles r1
            WHERE r1.user_id = $1
            AND NOW() > r1.expiration
            AND NOT EXISTS (
                SELECT 1 FROM roles r2 
                WHERE r2.user_id = r1.user_id 
                AND r2.role = r1.role 
                AND NOW() <= r2.expiration
            )
        """, user_id)

    async def delete_role(self, user_id, role_name):
        await self.connect()
        await self.conn.execute(
            "DELETE FROM roles WHERE user_id = $1 AND role = $2",
            user_id, role_name
        )

    async def delete_expired_role(self, user_id, role_name):
        await self.connect()
        await self.conn.execute(
            "DELETE FROM roles WHERE user_id = $1 AND role = $2 AND NOW() > expiration",
            user_id, role_name
        )

    async def assign_role(self, user_id, role_name, expiration):
        await self.connect()
        await self.delete_role(user_id, role_name)
        await self.conn.execute("""
            INSERT INTO roles (user_id, role, time_assigned, expiration) 
            VALUES ($1, $2, NOW(), $3)
        """, user_id, role_name, expiration)

    async def get_messages_for_range(self, range_key):
        await self.connect()
        records = await self.conn.fetch("SELECT message FROM phrases WHERE range_key = $1", range_key)
        return [record['message'] for record in records]

    async def clean_expired_roles(self):
        await self.connect()
        return await self.conn.execute("DELETE FROM roles WHERE NOW() > expiration")

    async def get_user_roles(self, user_id):
        await self.connect()
        records = await self.conn.fetch(
            "SELECT role, expiration FROM roles WHERE user_id = $1",
            user_id
        )
        return [(record['role'], record['expiration']) for record in records]

    async def run_migrations(self):
        await self.connect()
        await self._ensure_migrations_table()
        applied = await self._get_applied_migrations()
        base_dir = os.path.dirname(os.path.dirname(__file__))
        migrations_dir = os.path.join(base_dir, 'migrations')
        if not os.path.isdir(migrations_dir):
            logger.info("No migrations directory found at %s", migrations_dir)
            return
        files = sorted(glob.glob(os.path.join(migrations_dir, '*.sql')))
        logger.info("Found %d migration file(s)", len(files))
        for path in files:
            version = os.path.splitext(os.path.basename(path))[0]
            if version in applied:
                continue
            sql = self._read_file_sync(path)
            logger.info("Applying migration %s", version)
            async with self.conn.transaction():
                await self.conn.execute(sql)
                await self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES($1, NOW())",
                    version,
                )
        logger.info("Migrations up to date")

    async def _ensure_migrations_table(self):
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """
        )

    async def _get_applied_migrations(self):
        try:
            rows = await self.conn.fetch("SELECT version FROM schema_migrations")
            return {r['version'] for r in rows}
        except asyncpg.UndefinedTableError:
            await self._ensure_migrations_table()
            return set()

    def _read_file_sync(self, path):
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
