import os
import asyncpg
from datetime import datetime


class Database:
    def __init__(self):
        self.conn = None

    async def connect(self):
        if self.conn is None or self.conn.is_closed():
            self.conn = await asyncpg.connect(
                database=os.environ.get('DB_NAME'),
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASSWORD'),
                host=os.environ.get('DB_HOST')
            )

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
