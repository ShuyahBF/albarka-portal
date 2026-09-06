"""Le Chat interne est strictement réservé aux collaborateurs entre eux —
un compte client ne doit plus jamais pouvoir lire ni écrire sur aucun fil,
y compris un ancien fil `client:{tenant_id}` déjà présent en base d'avant
la restructuration en fils nommés par sujet/mission."""
from conftest import API, CREDENTIALS, fresh_async_env, make_session, run_async


class TestChatClientAccess:
    def test_client_blocked_on_every_chat_endpoint(self, client1, superviseur):
        client_session, client_user = client1
        staff_session, _ = superviseur
        legacy_thread_id = f"client:{client_user['id']}"

        async def _seed_legacy_thread(db):
            await db.chat_messages.insert_one({
                "id": "TEST_legacy_msg",
                "thread_id": legacy_thread_id,
                "body": "ancien message pré-migration",
                "author_id": client_user["id"],
                "author_name": client_user["full_name"],
                "created_at": "2026-01-01T00:00:00+00:00",
            })

        run_async(_seed_legacy_thread)

        try:
            assert client_session.get(f"{API}/chat/threads", timeout=60).status_code == 403
            assert client_session.post(
                f"{API}/chat/threads", json={"title": "Tentative client"}, timeout=60,
            ).status_code == 403
            assert client_session.get(
                f"{API}/chat/messages", params={"thread_id": legacy_thread_id}, timeout=60,
            ).status_code == 403
            assert client_session.post(
                f"{API}/chat/messages",
                json={"thread_id": legacy_thread_id, "body": "je réponds quand même"},
                timeout=60,
            ).status_code == 403

            # Un collaborateur, lui, n'a plus connaissance de la notion de fil
            # client : le fil legacy n'apparaît nulle part dans /chat/threads
            # (seuls les fils créés via POST /chat/threads y figurent).
            threads = staff_session.get(f"{API}/chat/threads", timeout=60).json()
            assert not any(t["thread_id"] == legacy_thread_id for t in threads)
        finally:
            async def _cleanup(db):
                await db.chat_messages.delete_many({"id": "TEST_legacy_msg"})
            run_async(_cleanup)
