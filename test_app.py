import base64
from io import BytesIO
import sqlite3
import tempfile
import unittest
from pathlib import Path

from acervo import create_app, repository
from acervo.services import create_user


class LibraryAppTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": str(database_path),
                "SCHOOL_YEAR": 2026,
                "PUBLIC_BASE_URL": "https://acervo.ifc.edu.br",
            }
        )
        create_user(str(database_path), "servidor@ifc.edu.br", "senha-segura-de-teste")
        self.client = self.app.test_client()
        self.student_passwords = {}

    def tearDown(self):
        self.temp_dir.cleanup()

    def csrf(self):
        response = self.client.get("/api/auth/session")
        return response.get_json()["csrf_token"]

    def login(self):
        token = self.csrf()
        return self.client.post(
            "/api/auth/login",
            json={"email": "servidor@ifc.edu.br", "password": "senha-segura-de-teste"},
            headers={"X-CSRF-Token": token},
        )

    def student_qr_code(self, enrollment):
        database_path = self.app.config["DATABASE_PATH"]
        if not repository.find_user(database_path, "fabricio.bizotto@ifc.edu.br"):
            create_user(
                database_path,
                "fabricio.bizotto@ifc.edu.br",
                "senha-admin-segura",
            )
        admin = self.app.test_client()
        admin_csrf = admin.get("/api/auth/session").get_json()["csrf_token"]
        admin_login = admin.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(admin_login.status_code, 200)
        admin_csrf = admin_login.get_json()["csrf_token"]
        password = self.student_passwords.get(enrollment)
        if password is None:
            reset = admin.post(
                f"/api/students/{enrollment}/student-access",
                json={},
                headers={"X-CSRF-Token": admin_csrf},
            )
            self.assertEqual(reset.status_code, 200)
            reset_result = reset.get_json()
            temporary_password = reset_result["temporary_password"]
            self.assertRegex(temporary_password, r"^\d{4}$")
            self.assertEqual(
                reset_result["portal_url"], "https://acervo.ifc.edu.br/aluno"
            )
            self.assertTrue(reset_result["portal_qr_data"].startswith("data:image/svg+xml;base64,"))
            password = "senha-estudante-segura-123"
            self.student_passwords[enrollment] = password
        else:
            temporary_password = None

        student = self.app.test_client()
        student_csrf = student.get("/api/student-auth/session").get_json()["csrf_token"]
        login_password = temporary_password or password
        logged_in = student.post(
            "/api/student-auth/login",
            json={"enrollment": enrollment, "password": login_password},
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(logged_in.status_code, 200)
        student_csrf = logged_in.get_json()["csrf_token"]
        if temporary_password:
            changed = student.post(
                "/api/student-auth/password",
                json={"new_password": password},
                headers={"X-CSRF-Token": student_csrf},
            )
            self.assertEqual(changed.status_code, 200)
            student_csrf = changed.get_json().get("csrf_token", student_csrf)
        issued = student.post(
            "/api/student-auth/qr",
            json={},
            headers={"X-CSRF-Token": student_csrf},
        )
        self.assertEqual(issued.status_code, 200)
        return issued.get_json()["code"]

    def test_login_requires_ifc_email(self):
        token = self.csrf()
        response = self.client.post(
            "/api/auth/login",
            json={"email": "outside@example.com", "password": "senha-segura-de-teste"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 400)

    def test_student_qr_is_required_student_bound_and_reusable_until_expiration(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()

        missing_qr = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/checkout",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(missing_qr.status_code, 400)

        qr_code = self.student_qr_code("2026001")
        self.assertRegex(qr_code, r"^\d{6}$")
        wrong_student = self.client.post(
            "/api/student-qr/verify",
            json={"code": qr_code, "enrollment": "2026002"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(wrong_student.status_code, 409)
        self.assertEqual(
            wrong_student.get_json()["error"],
            "Este QR Code pertence a outro estudante. Confira a matrícula selecionada.",
        )
        valid_student = self.client.post(
            "/api/student-qr/verify",
            json={"code": qr_code, "enrollment": "2026001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(valid_student.status_code, 200)
        checked_out = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/checkout",
            json={"signature": signature, "student_qr_code": qr_code},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checked_out.status_code, 200)
        second_checkout = self.client.put(
            "/api/students/2026001/books/matematica-2026-1/checkout",
            json={"signature": signature, "student_qr_code": qr_code},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(second_checkout.status_code, 200)
        qr_still_valid = self.client.post(
            "/api/student-qr/verify",
            json={"code": qr_code, "enrollment": "2026001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(qr_still_valid.status_code, 200)
        database = sqlite3.connect(self.app.config["DATABASE_PATH"])
        try:
            database.execute(
                "UPDATE student_qr_tokens SET expires_at = 0 WHERE code = ?",
                (qr_code,),
            )
            database.commit()
        finally:
            database.close()
        expired = self.client.post(
            "/api/student-qr/verify",
            json={"code": qr_code, "enrollment": "2026001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(
            expired.get_json()["error"],
            "Código inválido ou expirado. Peça ao estudante para gerar um novo QR Code.",
        )

        old_code = self.student_qr_code("2026001")
        admin = self.app.test_client()
        admin_csrf = admin.get("/api/auth/session").get_json()["csrf_token"]
        admin_login = admin.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        admin_csrf = admin_login.get_json()["csrf_token"]
        reset = admin.post(
            "/api/students/2026001/student-access",
            json={},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(reset.status_code, 200)
        invalidated = self.client.post(
            "/api/student-qr/verify",
            json={"code": old_code, "enrollment": "2026001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(invalidated.status_code, 401)

    def test_qr_code_validation_is_rate_limited_for_server(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)
        qr_code = self.student_qr_code("2026001")
        invalid_code = f"{(int(qr_code) + 1) % 1_000_000:06d}"
        for _ in range(5):
            response = self.client.post(
                "/api/student-qr/verify",
                json={"code": invalid_code, "enrollment": "2026001"},
                headers={"X-CSRF-Token": self.csrf()},
            )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Aguarde 15 minutos", response.get_json()["error"])
        blocked_correct_code = self.client.post(
            "/api/student-qr/verify",
            json={"code": qr_code, "enrollment": "2026001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(blocked_correct_code.status_code, 429)

    def test_book_signature_history_and_cancellation_preserve_all_events(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        checkout = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/checkout",
            json={
                "signature": signature,
                "student_qr_code": self.student_qr_code("2026001"),
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checkout.status_code, 200)
        returned = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned.status_code, 200)

        history_path = "/api/students/2026001/books/portugues-2026-1/history"
        initial_history = self.client.get(history_path)
        self.assertEqual(initial_history.status_code, 200)
        self.assertEqual(
            [entry["action"] for entry in initial_history.get_json()["history"]],
            ["return", "checkout"],
        )
        self.assertEqual(
            initial_history.get_json()["history"][0]["actor_email"],
            "servidor@ifc.edu.br",
        )

        cancel_checkout_early = self.client.post(
            "/api/students/2026001/books/portugues-2026-1/checkout/cancel",
            json={"reason": "Corrigir sequência"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(cancel_checkout_early.status_code, 409)
        self.assertIn("Cancele a devolução", cancel_checkout_early.get_json()["error"])
        invalid_reason = self.client.post(
            "/api/students/2026001/books/portugues-2026-1/return/cancel",
            json={"reason": "erro"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(invalid_reason.status_code, 400)

        cancelled_return = self.client.post(
            "/api/students/2026001/books/portugues-2026-1/return/cancel",
            json={"reason": "A devolução foi registrada por engano."},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(cancelled_return.status_code, 200)
        book = next(
            item for item in cancelled_return.get_json()["books"]
            if item["id"] == "portugues-2026-1"
        )
        self.assertTrue(book["checkout_signature"])
        self.assertIsNone(book["return_signature"])

        cancelled_checkout = self.client.post(
            "/api/students/2026001/books/portugues-2026-1/checkout/cancel",
            json={"reason": "A assinatura ficou ilegível e será refeita."},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(cancelled_checkout.status_code, 200)
        book = next(
            item for item in cancelled_checkout.get_json()["books"]
            if item["id"] == "portugues-2026-1"
        )
        self.assertIsNone(book["checkout_signature"])
        self.assertIsNone(book["return_signature"])
        history = self.client.get(history_path).get_json()["history"]
        self.assertEqual(
            [entry["action"] for entry in history],
            ["cancel_checkout", "cancel_return", "return", "checkout"],
        )
        self.assertEqual(
            history[0]["reason"],
            "A assinatura ficou ilegível e será refeita.",
        )
        self.assertEqual(history[0]["actor_email"], "servidor@ifc.edu.br")

    def test_student_portal_is_publicly_rendered(self):
        response = self.client.get("/aluno")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"student-login-form", response.data)

    def test_four_digit_temporary_code_is_rate_limited(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)

        database_path = self.app.config["DATABASE_PATH"]
        if not repository.find_user(database_path, "fabricio.bizotto@ifc.edu.br"):
            create_user(
                database_path,
                "fabricio.bizotto@ifc.edu.br",
                "senha-admin-segura",
            )
        admin = self.app.test_client()
        admin_csrf = admin.get("/api/auth/session").get_json()["csrf_token"]
        admin_login = admin.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        access = admin.post(
            "/api/students/2026001/student-access",
            json={},
            headers={"X-CSRF-Token": admin_login.get_json()["csrf_token"]},
        )
        self.assertEqual(access.status_code, 200)
        temporary_code = access.get_json()["temporary_password"]
        self.assertRegex(temporary_code, r"^\d{4}$")

        student = self.app.test_client()
        for _ in range(5):
            csrf = student.get("/api/student-auth/session").get_json()["csrf_token"]
            failed = student.post(
                "/api/student-auth/login",
                json={"enrollment": "2026001", "password": "not-the-code"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(failed.status_code, 401)
        csrf = student.get("/api/student-auth/session").get_json()["csrf_token"]
        locked = student.post(
            "/api/student-auth/login",
            json={"enrollment": "2026001", "password": temporary_code},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(locked.status_code, 429)

    def test_designated_admin_can_manage_accounts_and_regular_users_cannot(self):
        database_path = self.app.config["DATABASE_PATH"]
        create_user(
            database_path,
            "fabricio.bizotto@ifc.edu.br",
            "senha-admin-segura",
        )
        admin_client = self.app.test_client()
        login_response = admin_client.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={
                "X-CSRF-Token": admin_client.get("/api/auth/session").get_json()[
                    "csrf_token"
                ]
            },
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json()["is_admin"])
        admin_token = login_response.get_json()["csrf_token"]
        self.assertEqual(
            admin_client.get("/api/users").status_code,
            200,
        )
        admin_id = next(
            user["id"]
            for user in admin_client.get("/api/users").get_json()["users"]
            if user["email"] == "fabricio.bizotto@ifc.edu.br"
        )
        self.login()
        self.assertEqual(self.client.get("/api/users").status_code, 403)

        created = admin_client.post(
            "/api/users",
            json={
                "email": "novo.servidor@ifc.edu.br",
                "password": "senha-servidor-segura",
                "is_admin": False,
            },
            headers={"X-CSRF-Token": admin_token},
        )
        self.assertEqual(created.status_code, 201)
        managed_user = created.get_json()
        self.assertFalse(managed_user["is_admin"])
        self.assertTrue(managed_user["is_active"])

        promoted = admin_client.patch(
            f"/api/users/{managed_user['id']}",
            json={"is_admin": True, "is_active": True},
            headers={"X-CSRF-Token": admin_token},
        )
        self.assertEqual(promoted.status_code, 200)
        self.assertTrue(promoted.get_json()["is_admin"])

        user_client = self.app.test_client()
        user_token = user_client.get("/api/auth/session").get_json()["csrf_token"]
        user_login = user_client.post(
            "/api/auth/login",
            json={
                "email": "novo.servidor@ifc.edu.br",
                "password": "senha-servidor-segura",
            },
            headers={"X-CSRF-Token": user_token},
        )
        self.assertTrue(user_login.get_json()["is_admin"])
        admin_token = user_login.get_json()["csrf_token"]
        deactivated = user_client.patch(
            f"/api/users/{managed_user['id']}",
            json={"is_admin": True, "is_active": False},
            headers={"X-CSRF-Token": admin_token},
        )
        self.assertEqual(deactivated.status_code, 409)

        admin_token = login_response.get_json()["csrf_token"]
        disabled = admin_client.patch(
            f"/api/users/{managed_user['id']}",
            json={"is_admin": True, "is_active": False},
            headers={"X-CSRF-Token": admin_token},
        )
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(user_client.get("/api/students").status_code, 401)
        inactive_client = self.app.test_client()
        bad_login = inactive_client.post(
            "/api/auth/login",
            json={
                "email": "novo.servidor@ifc.edu.br",
                "password": "senha-servidor-segura",
            },
            headers={
                "X-CSRF-Token": inactive_client.get("/api/auth/session").get_json()[
                    "csrf_token"
                ]
            },
        )
        self.assertEqual(bad_login.status_code, 401)

        self_demote = admin_client.patch(
            f"/api/users/{admin_id}",
            json={"is_admin": False, "is_active": True},
            headers={"X-CSRF-Token": admin_token},
        )
        self.assertEqual(self_demote.status_code, 409)

    def test_existing_user_table_is_migrated_and_designated_admin_promoted(self):
        database_path = Path(self.temp_dir.name) / "legacy-users.db"
        from werkzeug.security import generate_password_hash

        db = sqlite3.connect(database_path)
        try:
            db.execute(
                """CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            db.execute(
                """INSERT INTO users (email, password_hash, created_at)
                   VALUES (?, ?, ?)""",
                (
                    "fabricio.bizotto@ifc.edu.br",
                    generate_password_hash("senha-admin-segura"),
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            db.commit()
        finally:
            db.close()

        migrated_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": str(database_path),
                "SCHOOL_YEAR": 2026,
            }
        )
        client = migrated_app.test_client()
        token = client.get("/api/auth/session").get_json()["csrf_token"]
        login_response = client.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(login_response.get_json()["is_admin"])

    def test_student_books_are_grade_specific_and_unique(self):
        self.login()
        token = self.csrf()
        response = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "2º"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201)
        books = response.get_json()["books"]
        self.assertEqual(len(books), 15)
        self.assertEqual(books[0]["title"], "360° Língua Portuguesa — 2º ano")
        self.assertEqual(books[-1]["title"], "Do seu jeito — Matemática — Volume 2")
        duplicate = self.client.post(
            "/api/students",
            json={"name": "Outra aluna", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_csv_import_ignores_existing_and_duplicate_enrollments(self):
        self.login()
        headers = {"X-CSRF-Token": self.csrf()}
        self.client.post(
            "/api/students",
            json={"name": "Ana cadastrada", "enrollment": "2026001", "grade": "1º"},
            headers=headers,
        )
        csv_content = (
            "\ufeffMatrícula;Nome;Turma\n"
            "2026001;Ana atualizada;3º\n"
            "2026002;João da Silva;2º ano\n"
            "2026002;Duplicada no arquivo;1°\n"
            ";Sem matrícula;3\n"
            "2026004;Turma inválida;4\n"
        ).encode("utf-8")

        response = self.client.post(
            "/api/students/import",
            data={"file": (BytesIO(csv_content), "estudantes.csv")},
            headers={"X-CSRF-Token": self.csrf()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {
                "imported": 1,
                "ignored": 2,
                "invalid": 2,
                "errors": [
                    {"line": 5, "reason": "matrícula inválida"},
                    {"line": 6, "reason": "turma deve ser 1º, 2º ou 3º"},
                ],
            },
        )
        original_student = self.client.get("/api/students/2026001").get_json()
        self.assertEqual(original_student["name"], "Ana cadastrada")
        imported_student = self.client.get("/api/students/2026002").get_json()
        self.assertEqual(imported_student["name"], "João da Silva")
        self.assertEqual(imported_student["grade"], "2º")
        self.assertEqual(len(imported_student["books"]), 15)

        repeated = self.client.post(
            "/api/students/import",
            data={"file": (BytesIO(csv_content), "estudantes.csv")},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.get_json()["imported"], 0)
        self.assertEqual(repeated.get_json()["ignored"], 3)

    def test_csv_import_requires_auth_and_valid_headers(self):
        unauthorized = self.client.post(
            "/api/students/import",
            data={"file": (BytesIO(b"name;enrollment\nAna;2026001"), "students.csv")},
        )
        self.assertEqual(unauthorized.status_code, 401)

        self.login()
        invalid = self.client.post(
            "/api/students/import",
            data={"file": (BytesIO(b"name;enrollment\nAna;2026001"), "students.csv")},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("cabeçalhos", invalid.get_json()["error"])

    def test_download_csv_template_requires_auth_and_has_import_headers(self):
        unauthorized = self.client.get("/api/students/import-template")
        self.assertEqual(unauthorized.status_code, 401)

        self.login()
        response = self.client.get("/api/students/import-template")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        self.assertIn("modelo-estudantes.csv", response.headers["Content-Disposition"])
        self.assertTrue(response.data.startswith(b"\xef\xbb\xbfmatricula;nome;turma\r\n"))

        imported = self.client.post(
            "/api/students/import",
            data={"file": (BytesIO(response.data), "modelo-estudantes.csv")},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.get_json()["imported"], 0)

    def test_checkout_return_and_pdf_data_are_persisted(self):
        self.login()
        token = self.csrf()
        self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": token},
        )
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        returned_early = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned_early.status_code, 409)
        checkout = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/checkout",
            json={
                "signature": signature,
                "student_qr_code": self.student_qr_code("2026001"),
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checkout.status_code, 200)
        self.assertTrue(checkout.get_json()["books"][0]["checkout_signature"])
        returned = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.get_json()["books"][0]["return_by"], "servidor@ifc.edu.br")
        previous_grade_math = self.client.put(
            "/api/students/2026001/books/matematica-2026-1/checkout",
            json={
                "signature": signature,
                "student_qr_code": self.student_qr_code("2026001"),
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(previous_grade_math.status_code, 200)
        updated = self.client.put(
            "/api/students/2026001",
            json={"name": "Ana Silva", "grade": "2º"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(updated.status_code, 200)
        books = updated.get_json()["books"]
        self.assertEqual(len(books), 17)
        titles = {book["title"] for book in books}
        self.assertIn("360° Língua Portuguesa — 1º ano", titles)
        self.assertIn("360° Língua Portuguesa — 2º ano", titles)
        self.assertIn("Do seu jeito — Matemática — Volume 1", titles)
        self.assertIn("Do seu jeito — Matemática — Volume 2", titles)
        portuguese_one = next(book for book in books if book["id"] == "portugues-2026-1")
        self.assertEqual(portuguese_one["return_by"], "servidor@ifc.edu.br")

    def test_school_years_promote_students_and_carry_open_shared_books(self):
        self.login()
        token = self.csrf()
        self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026001", "grade": "1º"},
            headers={"X-CSRF-Token": token},
        )
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        self.client.put(
            "/api/students/2026001/books/historia/checkout",
            json={
                "signature": signature,
                "student_qr_code": self.student_qr_code("2026001"),
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        database_path = self.app.config["DATABASE_PATH"]

        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": database_path,
                "SCHOOL_YEAR": 2027,
            }
        )
        self.client = self.app.test_client()
        self.login()
        student_2027 = self.client.get("/api/students/2026001?year=2027").get_json()
        self.assertEqual(student_2027["grade"], "2º")
        carried = next(book for book in student_2027["books"] if book["id"] == "historia")
        self.assertTrue(carried["carried_forward"])
        self.assertEqual(carried["issue_year"], 2026)
        self.assertEqual(len(student_2027["books"]), 15)
        historical_2026 = self.client.get("/api/students/2026001?year=2026").get_json()
        self.assertEqual(len(historical_2026["books"]), 15)
        historical_pending = next(
            book for book in historical_2026["books"] if book["id"] == "redacao"
        )
        self.assertEqual(historical_pending["issue_year"], 2027)
        self.assertIsNone(historical_pending["checkout_signature"])
        self.assertNotIn("portugues-2026-1", {book["id"] for book in student_2027["books"]})
        self.assertIn("portugues-2027-2", {book["id"] for book in student_2027["books"]})
        old_book_checkout = self.client.put(
            "/api/students/2026001/books/portugues-2026-1/checkout",
            json={
                "signature": signature,
                "student_qr_code": self.student_qr_code("2026001"),
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(old_book_checkout.status_code, 409)

        returned = self.client.put(
            "/api/students/2026001/books/historia/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned.status_code, 200)
        current_history = next(
            book for book in returned.get_json()["books"] if book["id"] == "historia"
        )
        self.assertTrue(current_history["return_signature"])
        historical_return = self.client.get("/api/students/2026001?year=2026").get_json()
        self.assertTrue(
            next(book for book in historical_return["books"] if book["id"] == "historia")[
                "return_signature"
            ]
        )

        for year, expected_grade in ((2028, "3º"),):
            self.app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                    "DATABASE_PATH": database_path,
                    "SCHOOL_YEAR": year,
                }
            )
            self.client = self.app.test_client()
            self.login()
            term = self.client.get(f"/api/students/2026001?year={year}").get_json()
            self.assertEqual(term["grade"], expected_grade)
            self.assertEqual(term["status"], "active")
            if year == 2028:
                final_year_checkout = self.client.put(
                    "/api/students/2026001/books/ingles/checkout",
                    json={
                        "signature": signature,
                        "student_qr_code": self.student_qr_code("2026001"),
                    },
                    headers={"X-CSRF-Token": self.csrf()},
                )
                self.assertEqual(final_year_checkout.status_code, 200)

        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": database_path,
                "SCHOOL_YEAR": 2030,
            }
        )
        self.client = self.app.test_client()
        self.login()
        finalized = self.client.get("/api/students/2026001?year=2028").get_json()
        self.assertEqual(finalized["status"], "completed")
        self.assertEqual(self.client.get("/api/students/2026001?year=2029").status_code, 404)
        archived_term = self.client.get("/api/students/2026001").get_json()
        self.assertEqual(archived_term["school_year"], 2028)
        archived_loan_return = self.client.put(
            "/api/students/2026001/books/ingles/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(archived_loan_return.status_code, 200)
        self.assertTrue(
            next(
                book
                for book in archived_loan_return.get_json()["books"]
                if book["id"] == "ingles"
            )["return_signature"]
        )
        db = sqlite3.connect(database_path)
        try:
            years = db.execute(
                "SELECT school_year FROM student_years WHERE enrollment = ? ORDER BY school_year",
                ("2026001",),
            ).fetchall()
        finally:
            db.close()
        self.assertEqual([year[0] for year in years], [2026, 2027, 2028])

    def test_legacy_database_migrates_annual_books_and_preserves_signatures(self):
        database_path = Path(self.temp_dir.name) / "legacy.db"
        db = sqlite3.connect(database_path)
        try:
            db.executescript(
                """
                CREATE TABLE students (
                    enrollment TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE book_signatures (
                    enrollment TEXT NOT NULL,
                    book_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    issue_year INTEGER NOT NULL,
                    checkout_signature TEXT,
                    checkout_at TEXT,
                    return_signature TEXT,
                    return_at TEXT,
                    return_by TEXT,
                    PRIMARY KEY (enrollment, book_id)
                );
                INSERT INTO students VALUES ('2026002', 'Bruno Lima', '2º', '2026-01-01');
                INSERT INTO book_signatures
                    VALUES ('2026002', 'portugues-1', 'Português 1', 2026, 'assinatura-preservada',
                            '2026-02-01', NULL, NULL, NULL);
                INSERT INTO book_signatures
                    VALUES ('2026002', 'historia', 'História por toda parte', 2026,
                            'emprestimo-preservado', '2026-02-01', NULL, NULL, NULL);
                """
            )
        finally:
            db.close()
        migrated_app = create_app(
            {
                "TESTING": True,
                "DATABASE_PATH": str(database_path),
                "SCHOOL_YEAR": 2027,
            }
        )
        from acervo.repository import find_student

        prior_term = find_student(str(database_path), "2026002", 2026)
        self.assertEqual(prior_term["grade"], "1º")
        migrated_portuguese = next(
            book for book in prior_term["books"] if book["id"] == "portugues-2026-1"
        )
        self.assertEqual(migrated_portuguese["checkout_signature"], "assinatura-preservada")
        migrated_history = repository.get_book_signature_history(
            str(database_path), "2026002", "portugues-2026-1"
        )
        self.assertEqual(len(migrated_history), 1)
        self.assertEqual(migrated_history[0]["action"], "checkout")
        self.assertEqual(migrated_history[0]["signature"], "assinatura-preservada")
        current_term = find_student(str(database_path), "2026002", 2027)
        self.assertEqual(current_term["grade"], "2º")
        carried_history = next(book for book in current_term["books"] if book["id"] == "historia")
        self.assertTrue(carried_history["carried_forward"])
        self.assertEqual(migrated_app.config["SCHOOL_YEAR"], 2027)

    def test_api_requires_authentication(self):
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 401)

    def test_mvc_view_and_static_assets_are_served_by_flask(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Importar CSV", page.data)
        self.assertIn(b"Exportar backup anual", page.data)
        self.assertIn(b"Aviso de Privacidade", page.data)
        self.assertRegex(page.data, rb"/static/styles\.css\?v=\d+")
        self.assertRegex(page.data, rb"/static/app\.js\?v=\d+")
        self.assertRegex(
            page.data,
            rb"/static/vendor/qr-scanner/qr-scanner\.umd\.min\.js\?v=\d+",
        )
        privacy = self.client.get("/privacidade")
        self.assertEqual(privacy.status_code, 200)
        self.assertRegex(privacy.data, rb"/static/styles\.css\?v=\d+")
        self.assertIn("15 a 17 anos".encode(), privacy.data)
        self.assertIn("controle interno e arquivo".encode(), privacy.data)
        student_portal = self.client.get("/aluno")
        self.assertEqual(student_portal.status_code, 200)
        self.assertRegex(student_portal.data, rb"/static/styles\.css\?v=\d+")
        self.assertRegex(student_portal.data, rb"/static/student\.js\?v=\d+")
        with self.client.get("/static/styles.css") as styles:
            self.assertEqual(styles.status_code, 200)
        with self.client.get("/static/app.js") as script:
            self.assertEqual(script.status_code, 200)
        with self.client.get(
            "/static/vendor/qr-scanner/qr-scanner.umd.min.js"
        ) as scanner:
            self.assertEqual(scanner.status_code, 200)
        with self.client.get(
            "/static/vendor/qr-scanner/qr-scanner-worker.min.js"
        ) as worker:
            self.assertEqual(worker.status_code, 200)


if __name__ == "__main__":
    unittest.main()
