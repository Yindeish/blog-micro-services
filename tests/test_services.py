import os
import shutil
import tempfile
import unittest
from pathlib import Path

from starlette.testclient import TestClient

# Create a temporary directory for test databases before importing service modules
test_dir = tempfile.mkdtemp(prefix="blog_test_data_")
os.environ["DATA_DIR"] = test_dir

import shared.config
shared.config.DATA_DIR = Path(test_dir)

import services.user.database as user_db
import services.blog.database as blog_db
import services.comment.database as comment_db
import services.payment.database as payment_db

user_db.DB_PATH = Path(test_dir) / "user.db"
blog_db.DB_PATH = Path(test_dir) / "blog.db"
comment_db.DB_PATH = Path(test_dir) / "comment.db"
payment_db.DB_PATH = Path(test_dir) / "payment.db"

user_db.init_db()
blog_db.init_db()
comment_db.init_db()
payment_db.init_db()

from services.user.main import app as user_app
from services.blog.main import app as blog_app
from services.comment.main import app as comment_app
from services.payment.main import app as payment_app


class MicroservicesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.user_client = TestClient(user_app)
        cls.blog_client = TestClient(blog_app)
        cls.comment_client = TestClient(comment_app)
        cls.payment_client = TestClient(payment_app)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(test_dir, ignore_errors=True)

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
        list_resp = self.blog_client.get("/posts?tag=architecture")
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


if __name__ == "__main__":
    unittest.main()
