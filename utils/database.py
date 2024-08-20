import os
import asyncpg

class Database:
    def __init__(self):
        self.conn = None

    async def connect(self):
        if self.conn is None or self.conn.is_closed():
            self.conn = await asyncpg.connect(
                database=os.environ.get('DB_NAME', 'dulldb'),
                user=os.environ.get('DB_USER', 'dullfox'),
                password=os.environ.get('DB_PASSWORD', '1324'),
                host=os.environ.get('DB_HOST', '130.162.253.235')
            )

    async def fetch_expired_roles(self):
        await self.connect()
        return await self.conn.fetch("SELECT * FROM roles WHERE NOW() > expiration")

    async def delete_role(self, user_id, role_name):
        await self.connect()
        await self.conn.execute("DELETE FROM roles WHERE user_id = $1 AND role = $2", user_id, role_name)

    async def assign_role(self, user_id, role_name, expiration):
        await self.connect()
        await self.conn.execute("""
            INSERT INTO roles (user_id, role, time_assigned, expiration) VALUES ($1, $2, NOW(), $3)
            ON CONFLICT (user_id, role) DO UPDATE SET time_assigned = NOW(), expiration = $4
        """, user_id, role_name, expiration, expiration)

    async def get_messages_for_range(self, range_key):
        await self.connect()
        records = await self.conn.fetch("SELECT message FROM phrases WHERE range_key = $1", range_key)
        return [record['message'] for record in records]