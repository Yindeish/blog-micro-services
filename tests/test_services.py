import os
import unittest
from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from services.user.main import app as user_app
from services.blog.main import app as blog_app
from services.comment.main import app as comment_app
from services.payment.main import app as payment_app


# In-memory storage structures for isolated testing without file-based databases
class MockRecord:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        return None


class MockPrismaModel:
    def __init__(self):
        self._records = []
        self._id_counter = 1

    async def create(self, data):
        rec_data = dict(data)
        if "id" not in rec_data:
            rec_data["id"] = self._id_counter
            self._id_counter += 1
        if "created_at" not in rec_data:
            rec_data["created_at"] = "2026-09-22T12:00:00Z"
        if "updated_at" not in rec_data:
            rec_data["updated_at"] = "2026-09-22T12:00:00Z"
        record = MockRecord(**rec_data)
        self._records.append(record)
        return record

    async def find_unique(self, where):
        for r in self._records:
            match = True
            for k, v in where.items():
                if isinstance(v, dict):
                    # Compound unique e.g. user_id_post_id
                    for sub_k, sub_v in v.items():
                        if getattr(r, sub_k, None) != sub_v:
                            match = False
                elif getattr(r, k, None) != v:
                    match = False
            if match:
                return r
        return None

    async def find_first(self, where):
        if "OR" in where:
            for r in self._records:
                for cond in where["OR"]:
                    if any(getattr(r, k, None) == v for k, v in cond.items()):
                        return r
            return None
        return await self.find_unique(where)

    async def find_many(self, where=None, take=None, skip=None, order=None):
        results = list(self._records)
        if where:
            filtered = []
            for r in results:
                match = True
                for k, v in where.items():
                    if getattr(r, k, None) != v:
                        match = False
                if match:
                    filtered.append(r)
            results = filtered
        if skip:
            results = results[skip:]
        if take:
            results = results[:take]
        return results

    async def update(self, where, data):
        rec = await self.find_unique(where)
        if rec:
            for k, v in data.items():
                if isinstance(v, dict):
                    if "increment" in v:
                        setattr(rec, k, getattr(rec, k, 0.0) + v["increment"])
                    elif "decrement" in v:
                        setattr(rec, k, getattr(rec, k, 0.0) - v["decrement"])
                else:
                    setattr(rec, k, v)
        return rec

    async def delete(self, where):
        rec = await self.find_unique(where)
        if rec and rec in self._records:
            self._records.remove(rec)
        return rec


class MockPrismaClient:
    def __init__(self):
        self.user = MockPrismaModel()
        self.post = MockPrismaModel()
        self.comment = MockPrismaModel()
        self.wallet = MockPrismaModel()
        self.transaction = MockPrismaModel()
        self.accesspass = MockPrismaModel()

    def is_connected(self):
        return True

    async def connect(self):
        pass

    async def disconnect(self):
        pass


class MicroservicesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_prisma = MockPrismaClient()
        cls.prisma_patcher = patch("shared.prisma_client.get_prisma", new_callable=AsyncMock, return_value=cls.mock_prisma)
        cls.prisma_patcher.start()
        patch("services.user.routes.get_prisma", new_callable=AsyncMock, return_value=cls.mock_prisma).start()
        patch("services.blog.routes.get_prisma", new_callable=AsyncMock, return_value=cls.mock_prisma).start()
        patch("services.comment.routes.get_prisma", new_callable=AsyncMock, return_value=cls.mock_prisma).start()
        patch("services.payment.routes.get_prisma", new_callable=AsyncMock, return_value=cls.mock_prisma).start()

        cls.user_client = TestClient(user_app)
        cls.blog_client = TestClient(blog_app)
        cls.comment_client = TestClient(comment_app)
        cls.payment_client = TestClient(payment_app)

        cls.post_patcher = patch("services.comment.routes.verify_post_exists", new_callable=AsyncMock, return_value=True)
        cls.post_patcher.start()

    @classmethod
    def tearDownClass(cls):
        patch.stopall()

    def test_01_user_lifecycle(self):
        # 1. Register Author
        resp = self.user_client.post(
            "/register",
            json={
                "username": "author_alice",
                "email": "alice@example.com",
                "password": "password123",
                "full_name": "Alice Author",
                "bio": "Writer and engineer",
            },
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("access_token", data["data"])
        MicroservicesTestCase.alice_token = data["data"]["access_token"]
        MicroservicesTestCase.alice_id = data["data"]["user"]["id"]

        # 2. Register Reader
        resp = self.user_client.post(
            "/register",
            json={
                "username": "reader_bob",
                "email": "bob@example.com",
                "password": "password456",
                "full_name": "Bob Reader",
            },
        )
        self.assertEqual(resp.status_code, 201)
        MicroservicesTestCase.bob_token = resp.json()["data"]["access_token"]
        MicroservicesTestCase.bob_id = resp.json()["data"]["user"]["id"]

        # 3. Login
        login_resp = self.user_client.post(
            "/login",
            json={"username_or_email": "author_alice", "password": "password123"},
        )
        self.assertEqual(login_resp.status_code, 200)

        # 4. Profile /me
        me_resp = self.user_client.get(
            "/me",
            headers={"Authorization": f"Bearer {self.alice_token}"},
        )
        self.assertEqual(me_resp.status_code, 200)
        self.assertEqual(me_resp.json()["data"]["username"], "author_alice")

    def test_02_blog_posts(self):
        headers = {"Authorization": f"Bearer {self.alice_token}"}

        # 1. Create standard post
        resp = self.blog_client.post(
            "/posts",
            headers=headers,
            json={
                "title": "Getting Started with Microservices",
                "content": "Microservices allow decoupling systems into independent domains.",
                "tags": ["python", "architecture", "fastapi"],
            },
        )
        self.assertEqual(resp.status_code, 201)
        post = resp.json()["data"]
        MicroservicesTestCase.post_id = post["id"]
        self.assertEqual(post["title"], "Getting Started with Microservices")

        # 2. Create premium post
        resp_premium = self.blog_client.post(
            "/posts",
            headers=headers,
            json={
                "title": "Deep Dive: Advanced Microservices Patterns",
                "content": "Exclusive detailed breakdown of event-driven and distributed systems.",
                "tags": ["architecture", "advanced"],
                "is_premium": True,
                "price": 5.0,
            },
        )
        self.assertEqual(resp_premium.status_code, 201)
        MicroservicesTestCase.premium_post_id = resp_premium.json()["data"]["id"]

        # 3. List posts
        list_resp = self.blog_client.get("/posts")
        self.assertEqual(list_resp.status_code, 200)
        self.assertGreaterEqual(len(list_resp.json()["data"]), 1)

    def test_03_comments(self):
        reader_headers = {"Authorization": f"Bearer {self.bob_token}"}

        # 1. Add top-level comment
        resp = self.comment_client.post(
            "/comments",
            headers=reader_headers,
            json={
                "post_id": self.post_id,
                "content": "Great article! Very clear explanation.",
            },
        )
        self.assertEqual(resp.status_code, 201)
        comment_id = resp.json()["data"]["id"]

        # 2. Author replies to comment
        author_headers = {"Authorization": f"Bearer {self.alice_token}"}
        resp_reply = self.comment_client.post(
            "/comments",
            headers=author_headers,
            json={
                "post_id": self.post_id,
                "content": "Thanks Bob, glad you enjoyed it!",
                "parent_id": comment_id,
            },
        )
        self.assertEqual(resp_reply.status_code, 201)

        # 3. Fetch comments for post
        resp_list = self.comment_client.get(f"/posts/{self.post_id}/comments")
        self.assertEqual(resp_list.status_code, 200)
        comments = resp_list.json()["data"]
        self.assertEqual(len(comments), 1)
        self.assertEqual(len(comments[0]["replies"]), 1)
        self.assertEqual(comments[0]["replies"][0]["content"], "Thanks Bob, glad you enjoyed it!")

    def test_04_payments_wallet_and_tipping(self):
        reader_headers = {"Authorization": f"Bearer {self.bob_token}"}
        author_headers = {"Authorization": f"Bearer {self.alice_token}"}

        # 1. Top up reader wallet
        resp = self.payment_client.post(
            "/topup",
            headers=reader_headers,
            json={"amount": 20.0, "payment_method": "card"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["balance"], 20.0)

        # 2. Reader tips author 3.50
        tip_resp = self.payment_client.post(
            "/tip",
            headers=reader_headers,
            json={
                "recipient_user_id": self.alice_id,
                "amount": 3.50,
                "note": "Loved the post!",
            },
        )
        self.assertEqual(tip_resp.status_code, 200)

        # 3. Check author balance
        author_wallet = self.payment_client.get("/wallet", headers=author_headers)
        self.assertEqual(author_wallet.json()["data"]["balance"], 3.50)

        # 4. Check reader balance
        reader_wallet = self.payment_client.get("/wallet", headers=reader_headers)
        self.assertEqual(reader_wallet.json()["data"]["balance"], 16.50)

        # 5. Check transactions history
        tx_resp = self.payment_client.get("/transactions", headers=reader_headers)
        self.assertEqual(tx_resp.status_code, 200)
        self.assertEqual(len(tx_resp.json()["data"]), 2)  # 1 topup, 1 tip_sent

    def test_05_squad_payment_initiation(self):
        reader_headers = {"Authorization": f"Bearer {self.bob_token}"}
        resp = self.payment_client.post(
            "/initiate-payment",
            headers=reader_headers,
            json={
                "amount": 1000.0,
                "email": "bob@example.com",
                "payment_for": "wallet_topup",
            },
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("checkout_url", data["data"])
        self.assertTrue(data["data"]["checkout_url"].startswith("http"))
        self.assertEqual(data["data"]["amount"], 1000.0)


if __name__ == "__main__":
    unittest.main()
