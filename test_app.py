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
            }
        )
        create_user(str(database_path), "servidor@ifc.edu.br", "senha-segura-de-teste")
        self.informatics_course_id = next(
            course["id"]
            for course in repository.list_courses(str(database_path))
            if "Informática" in course["name"]
        )
        self.administration_course_id = next(
            course["id"]
            for course in repository.list_courses(str(database_path))
            if "Administração" in course["name"]
        )
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

    def student_qr_token(self, enrollment):
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
            temporary_password = reset.get_json()["temporary_password"]
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
        return issued.get_json()["token"]

    def test_login_requires_ifc_email(self):
        token = self.csrf()
        response = self.client.post(
            "/api/auth/login",
            json={"email": "outside@example.com", "password": "senha-segura-de-teste"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_can_advance_school_year_and_setting_persists(self):
        self.login()
        self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        denied = self.client.post(
            "/api/settings/school-year",
            json={"school_year": 2028},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(denied.status_code, 403)

        create_user(
            self.app.config["DATABASE_PATH"],
            "fabricio.bizotto@ifc.edu.br",
            "senha-admin-segura",
        )
        admin = self.app.test_client()
        admin_csrf = admin.get("/api/auth/session").get_json()["csrf_token"]
        logged_in = admin.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(logged_in.status_code, 200)
        admin_csrf = logged_in.get_json()["csrf_token"]
        updated = admin.post(
            "/api/settings/school-year",
            json={"school_year": 2028},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["school_year"], 2028)
        self.assertEqual(
            admin.get("/api/students").get_json()["school_year"],
            2028,
        )
        self.assertEqual(
            len(admin.get("/api/students?year=2026").get_json()["students"]),
            1,
        )
        historical_2027 = admin.get("/api/students?year=2027").get_json()["students"]
        self.assertEqual([student["enrollment"] for student in historical_2027], ["2026000001"])
        self.assertEqual(
            admin.get("/api/school-years").get_json()["school_years"],
            [2028, 2027, 2026],
        )
        promoted_response = admin.get("/api/students/2026000001")
        self.assertEqual(promoted_response.status_code, 200, promoted_response.get_json())
        promoted = promoted_response.get_json()
        self.assertEqual(promoted["grade"], "3º", promoted)
        self.assertEqual(promoted["school_year"], 2028)

        created = admin.post(
            "/api/students",
            json={"name": "João Souza", "enrollment": "2028000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(created.status_code, 201)
        newcomer = admin.get("/api/students/2028000001").get_json()
        self.assertEqual(newcomer["grade"], "1º")
        self.assertIn(
            "portugues-2028-1",
            {book["id"] for book in newcomer["books"]},
        )

        lower_year = admin.post(
            "/api/settings/school-year",
            json={"school_year": 2027},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(lower_year.status_code, 409)
        invalid_year = admin.post(
            "/api/settings/school-year",
            json={"school_year": 2101},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(invalid_year.status_code, 400)

        database_path = self.app.config["DATABASE_PATH"]
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": database_path,
                "SCHOOL_YEAR": 2026,
            }
        )
        self.client = self.app.test_client()
        self.assertEqual(self.app.config["SCHOOL_YEAR"], 2028)
        self.login()
        self.assertEqual(self.client.get("/api/students").get_json()["school_year"], 2028)

    def test_dev_reset_removes_only_student_data_and_sets_year(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Old development student", "enrollment": "2026000003", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)
        database_path = self.app.config["DATABASE_PATH"]
        repository.reset_dev_students(
            database_path,
            2026,
            [
                ("2026000001", "Estudante Demonstração 1", "1º", "2026-01-01T00:00:00+00:00"),
                ("2026000002", "Estudante Demonstração 2", "2º", "2026-01-01T00:00:00+00:00"),
                ("2026000003", "Estudante Demonstração 3", "3º", "2026-01-01T00:00:00+00:00"),
            ],
        )
        database = sqlite3.connect(database_path)
        try:
            students = database.execute(
                "SELECT enrollment, grade FROM students ORDER BY enrollment"
            ).fetchall()
            setting = database.execute(
                "SELECT value FROM application_settings WHERE key = 'school_year'"
            ).fetchone()[0]
            users = database.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            book_history = database.execute(
                "SELECT COUNT(*) FROM book_signature_history"
            ).fetchone()[0]
        finally:
            database.close()
        self.assertEqual(
            students,
            [("2026000001", "1º"), ("2026000002", "2º"), ("2026000003", "3º")],
        )
        self.assertEqual(setting, "2026")
        self.assertEqual(users, 1)
        self.assertEqual(book_history, 0)

    def test_checkout_requires_the_selected_students_enrollment(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()

        missing_enrollment = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/checkout",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(missing_enrollment.status_code, 400)
        mismatched_enrollment = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/checkout",
            json={"signature": signature, "enrollment_confirmation": "2026000002"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(mismatched_enrollment.status_code, 400)
        checked_out = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/checkout",
            json={"signature": signature, "enrollment_confirmation": "2026000001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checked_out.status_code, 200)
        second_checkout = self.client.put(
            "/api/students/2026000001/books/matematica-2026-1/checkout",
            json={"signature": signature, "enrollment_confirmation": "2026000001"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(second_checkout.status_code, 200)

    def test_multiple_books_can_be_checked_out_with_one_signature_atomically(self):
        self.login()
        self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        path = "/api/students/2026000001/books/checkout"
        headers = {"X-CSRF-Token": self.csrf()}
        body = {
            "book_ids": ["portugues-2026-1", "matematica-2026-1"],
            "signature": signature,
            "enrollment_confirmation": "2026000001",
        }
        checked_out = self.client.post(path, json=body, headers=headers)
        self.assertEqual(checked_out.status_code, 200)
        for book_id in body["book_ids"]:
            history = self.client.get(
                f"/api/students/2026000001/books/{book_id}/history"
            ).get_json()["history"]
            self.assertEqual([entry["action"] for entry in history], ["checkout"])
            self.assertEqual(history[0]["signature"], signature)

        atomic_failure = self.client.post(
            path,
            json={
                **body,
                "book_ids": ["historia", "portugues-2026-1"],
            },
            headers=headers,
        )
        self.assertEqual(atomic_failure.status_code, 409)
        student = self.client.get("/api/students/2026000001").get_json()
        history = {
            book["id"]: book["checkout_signature"]
            for book in student["books"]
        }
        self.assertIsNone(history["historia"])

    def test_book_signature_history_and_cancellation_preserve_all_events(self):
        self.login()
        created = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        checkout = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/checkout",
            json={
                "signature": signature,
                "enrollment_confirmation": "2026000001",
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checkout.status_code, 200)
        returned = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned.status_code, 200)

        history_path = "/api/students/2026000001/books/portugues-2026-1/history"
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
            "/api/students/2026000001/books/portugues-2026-1/checkout/cancel",
            json={"reason": "Corrigir sequência"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(cancel_checkout_early.status_code, 409)
        self.assertIn("Cancele a devolução", cancel_checkout_early.get_json()["error"])
        invalid_reason = self.client.post(
            "/api/students/2026000001/books/portugues-2026-1/return/cancel",
            json={"reason": "erro"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(invalid_reason.status_code, 400)

        cancelled_return = self.client.post(
            "/api/students/2026000001/books/portugues-2026-1/return/cancel",
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
            "/api/students/2026000001/books/portugues-2026-1/checkout/cancel",
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

    def test_admin_can_manage_courses_and_students_must_be_assigned(self):
        database_path = self.app.config["DATABASE_PATH"]
        create_user(
            database_path,
            "fabricio.bizotto@ifc.edu.br",
            "senha-admin-segura",
        )
        admin = self.app.test_client()
        admin_csrf = admin.get("/api/auth/session").get_json()["csrf_token"]
        login_response = admin.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(login_response.status_code, 200)
        admin_csrf = login_response.get_json()["csrf_token"]

        courses = admin.get("/api/courses").get_json()["courses"]
        self.assertEqual(len(courses), 2)
        self.assertEqual(
            {course["abbreviation"] for course in courses},
            {"INFO", "ADM"},
        )
        self.login()
        denied = self.client.post(
            "/api/courses",
            json={"name": "Curso restrito"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(denied.status_code, 403)

        created = admin.post(
            "/api/courses",
            json={
                "name": "Técnico em Gestão Integrado ao Ensino Médio",
                "abbreviation": " ges ",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(created.status_code, 201)
        course = created.get_json()
        self.assertEqual(course["abbreviation"], "GES")
        duplicate = admin.post(
            "/api/courses",
            json={
                "name": "técnico em gestão integrado ao ensino médio",
                "abbreviation": "GZ2",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(duplicate.status_code, 409)
        duplicate_abbreviation = admin.post(
            "/api/courses",
            json={"name": "Curso com sigla repetida", "abbreviation": "ges"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(duplicate_abbreviation.status_code, 409)
        invalid_abbreviation = admin.post(
            "/api/courses",
            json={"name": "Curso com sigla curta", "abbreviation": "AB"},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(invalid_abbreviation.status_code, 400)

        student = admin.post(
            "/api/students",
            json={
                "name": "Estudante de Gestão",
                "enrollment": "2026304710",
                "grade": "1º",
                "course_id": course["id"],
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(student.status_code, 201)
        self.assertEqual(student.get_json()["course_name"], course["name"])
        deactivated = admin.patch(
            f"/api/courses/{course['id']}",
            json={"is_active": False},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.get_json()["is_active"])
        archived_link = admin.get("/api/students/2026304710").get_json()
        self.assertEqual(archived_link["course_name"], course["name"])
        unavailable_course = admin.post(
            "/api/students",
            json={
                "name": "Outro estudante",
                "enrollment": "2026304711",
                "grade": "1º",
                "course_id": course["id"],
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(unavailable_course.status_code, 400)
        reactivated = admin.patch(
            f"/api/courses/{course['id']}",
            json={"is_active": True},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(reactivated.status_code, 200)
        for seeded_course in courses:
            disabled = admin.patch(
                f"/api/courses/{seeded_course['id']}",
                json={"is_active": False},
                headers={"X-CSRF-Token": admin_csrf},
            )
            self.assertEqual(disabled.status_code, 200)
        last_course = admin.patch(
            f"/api/courses/{course['id']}",
            json={"is_active": False},
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(last_course.status_code, 409)

    def test_existing_courses_migrate_to_abbreviations_and_preserve_student_links(self):
        database_path = Path(self.temp_dir.name) / "legacy-courses.db"
        database = sqlite3.connect(database_path)
        try:
            database.executescript(
                """
                CREATE TABLE courses (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    is_active INTEGER NOT NULL DEFAULT 1
                );
                INSERT INTO courses (name) VALUES ('Curso Técnico Antigo');
                CREATE TABLE students (
                    enrollment TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    grade TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO students VALUES (
                    '2026304710', 'Estudante Legado', '1º', '2026-01-01'
                );
                """
            )
        finally:
            database.close()

        migrated_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": str(database_path),
                "SCHOOL_YEAR": 2026,
            }
        )
        migrated_courses = repository.list_courses(str(database_path))
        self.assertEqual(
            {course["abbreviation"] for course in migrated_courses if course["name"].startswith("Técnico em")},
            {"INFO", "ADM"},
        )
        legacy_course = next(
            course for course in migrated_courses if course["name"] == "Curso Técnico Antigo"
        )
        self.assertEqual(len(legacy_course["abbreviation"]), 3)
        migrated_student = repository.find_student(
            str(database_path), "2026304710", migrated_app.config["SCHOOL_YEAR"]
        )
        self.assertEqual(
            migrated_student["course_name"],
            "Técnico em Informática Integrado ao Ensino Médio",
        )
        self.assertEqual(migrated_student["course_abbreviation"], "INFO")

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
        invalid_enrollment = self.client.post(
            "/api/students",
            json={"name": "Matrícula inválida", "enrollment": "202630471", "grade": "2º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(invalid_enrollment.status_code, 400)
        self.assertIn("exatamente 10 números", invalid_enrollment.get_json()["error"])
        response = self.client.post(
            "/api/students",
            json={"name": "Ana Silva", "enrollment": "2026304710", "grade": "2º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 201)
        books = response.get_json()["books"]
        self.assertEqual(len(books), 15)
        self.assertEqual(books[0]["title"], "360° Língua Portuguesa — 2º ano")
        self.assertEqual(books[-1]["title"], "Do seu jeito — Matemática — Volume 2")
        duplicate = self.client.post(
            "/api/students",
            json={"name": "Outra aluna", "enrollment": "2026304710", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_csv_import_ignores_existing_and_duplicate_enrollments(self):
        self.login()
        headers = {"X-CSRF-Token": self.csrf()}
        self.client.post(
            "/api/students",
            json={"name": "Ana cadastrada", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers=headers,
        )
        csv_content = (
            "\ufeffMatrícula;Nome;Turma;Curso\n"
            "2026000001;Ana atualizada;3º;Técnico em Informática Integrado ao Ensino Médio\n"
            "2026000002;João da Silva;2º ano;ADM\n"
            "2026000002;Duplicada no arquivo;1°;ADM\n"
            ";Sem matrícula;3;Técnico em Informática Integrado ao Ensino Médio\n"
            "2026000004;Turma inválida;4;Técnico em Informática Integrado ao Ensino Médio\n"
            "ABC1234567;Não numérica;1º;Técnico em Informática Integrado ao Ensino Médio\n"
            "2026000005;Curso desconhecido;1º;Técnico em Curso Desconhecido\n"
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
                "invalid": 4,
                "errors": [
                    {"line": 5, "reason": "matrícula inválida"},
                    {"line": 6, "reason": "turma deve ser 1º, 2º ou 3º"},
                    {"line": 7, "reason": "matrícula inválida"},
                    {"line": 8, "reason": "curso inválido ou inativo"},
                ],
            },
        )
        original_student = self.client.get("/api/students/2026000001").get_json()
        self.assertEqual(original_student["name"], "Ana cadastrada")
        imported_student = self.client.get("/api/students/2026000002").get_json()
        self.assertEqual(imported_student["name"], "João da Silva")
        self.assertEqual(imported_student["grade"], "2º")
        self.assertEqual(
            imported_student["course_name"],
            "Técnico em Administração Integrado ao Ensino Médio",
        )
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
            data={"file": (BytesIO(b"name;enrollment\nAna;2026000001"), "students.csv")},
        )
        self.assertEqual(unauthorized.status_code, 401)

        self.login()
        invalid = self.client.post(
            "/api/students/import",
            data={"file": (BytesIO(b"name;enrollment\nAna;2026000001"), "students.csv")},
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
        self.assertTrue(response.data.startswith(b"\xef\xbb\xbfmatricula;nome;turma;curso\r\n"))

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
            json={"name": "Ana Silva", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": token},
        )
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        returned_early = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned_early.status_code, 409)
        checkout = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/checkout",
            json={
                "signature": signature,
                "enrollment_confirmation": "2026000001",
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checkout.status_code, 200)
        self.assertTrue(checkout.get_json()["books"][0]["checkout_signature"])
        returned = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.get_json()["books"][0]["return_by"], "servidor@ifc.edu.br")
        previous_grade_math = self.client.put(
            "/api/students/2026000001/books/matematica-2026-1/checkout",
            json={
                "signature": signature,
                "enrollment_confirmation": "2026000001",
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(previous_grade_math.status_code, 200)
        updated = self.client.put(
            "/api/students/2026000001",
            json={
                "name": "Ana Silva",
                "grade": "2º",
                "course_id": self.informatics_course_id,
            },
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
            json={"name": "Ana Silva", "enrollment": "2026000001", "grade": "1º", "course_id": self.informatics_course_id},
            headers={"X-CSRF-Token": token},
        )
        signature = "data:image/png;base64," + base64.b64encode(
            b"\x89PNG\r\n\x1a\nvalid-test-image"
        ).decode()
        self.client.put(
            "/api/students/2026000001/books/historia/checkout",
            json={
                "signature": signature,
                "enrollment_confirmation": "2026000001",
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
        student_2027 = self.client.get("/api/students/2026000001?year=2027").get_json()
        self.assertEqual(student_2027["grade"], "2º")
        carried = next(book for book in student_2027["books"] if book["id"] == "historia")
        self.assertTrue(carried["carried_forward"])
        self.assertEqual(carried["issue_year"], 2026)
        self.assertEqual(len(student_2027["books"]), 15)
        historical_2026 = self.client.get("/api/students/2026000001?year=2026").get_json()
        self.assertEqual(len(historical_2026["books"]), 15)
        historical_pending = next(
            book for book in historical_2026["books"] if book["id"] == "redacao"
        )
        self.assertEqual(historical_pending["issue_year"], 2027)
        self.assertIsNone(historical_pending["checkout_signature"])
        self.assertNotIn("portugues-2026-1", {book["id"] for book in student_2027["books"]})
        self.assertIn("portugues-2027-2", {book["id"] for book in student_2027["books"]})
        old_book_checkout = self.client.put(
            "/api/students/2026000001/books/portugues-2026-1/checkout",
            json={
                "signature": signature,
                "enrollment_confirmation": "2026000001",
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(old_book_checkout.status_code, 409)

        returned = self.client.put(
            "/api/students/2026000001/books/historia/return",
            json={"signature": signature},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(returned.status_code, 200)
        current_history = next(
            book for book in returned.get_json()["books"] if book["id"] == "historia"
        )
        self.assertTrue(current_history["return_signature"])
        historical_return = self.client.get("/api/students/2026000001?year=2026").get_json()
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
            term = self.client.get(f"/api/students/2026000001?year={year}").get_json()
            self.assertEqual(term["grade"], expected_grade)
            self.assertEqual(term["status"], "active")
            if year == 2028:
                final_year_checkout = self.client.put(
                    "/api/students/2026000001/books/ingles/checkout",
                    json={
                        "signature": signature,
                        "enrollment_confirmation": "2026000001",
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
        finalized = self.client.get("/api/students/2026000001?year=2028").get_json()
        self.assertEqual(finalized["status"], "completed")
        self.assertEqual(self.client.get("/api/students/2026000001?year=2029").status_code, 404)
        archived_term = self.client.get("/api/students/2026000001").get_json()
        self.assertEqual(archived_term["school_year"], 2028)
        archived_list = self.client.get("/api/students").get_json()["students"]
        self.assertEqual(len(archived_list), 1)
        self.assertEqual(archived_list[0]["status"], "completed")
        self.assertEqual(archived_list[0]["grade"], "3º")
        archived_year_term = self.client.get(
            "/api/students?year=2028"
        ).get_json()["students"]
        self.assertEqual(len(archived_year_term), 1)
        self.assertEqual(archived_year_term[0]["status"], "completed")
        archived_loan_return = self.client.put(
            "/api/students/2026000001/books/ingles/return",
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
                ("2026000001",),
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
                INSERT INTO students VALUES ('2026000002', 'Bruno Lima', '2º', '2026-01-01');
                INSERT INTO book_signatures
                    VALUES ('2026000002', 'portugues-1', 'Português 1', 2026, 'assinatura-preservada',
                            '2026-02-01', NULL, NULL, NULL);
                INSERT INTO book_signatures
                    VALUES ('2026000002', 'historia', 'História por toda parte', 2026,
                            'emprestimo-preservado', '2026-02-01', NULL, NULL, NULL);
                """
            )
        finally:
            db.close()
        migrated_app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret-key-for-tests-32bytes",
                "DATABASE_PATH": str(database_path),
                "SCHOOL_YEAR": 2027,
            }
        )
        from acervo.repository import find_student

        prior_term = find_student(str(database_path), "2026000002", 2026)
        self.assertEqual(prior_term["grade"], "1º")
        self.assertEqual(
            prior_term["course_name"],
            "Técnico em Informática Integrado ao Ensino Médio",
        )
        migrated_portuguese = next(
            book for book in prior_term["books"] if book["id"] == "portugues-2026-1"
        )
        self.assertEqual(migrated_portuguese["checkout_signature"], "assinatura-preservada")
        migrated_history = repository.get_book_signature_history(
            str(database_path), "2026000002", "portugues-2026-1"
        )
        self.assertEqual(len(migrated_history), 1)
        self.assertEqual(migrated_history[0]["action"], "checkout")
        self.assertEqual(migrated_history[0]["signature"], "assinatura-preservada")
        current_term = find_student(str(database_path), "2026000002", 2027)
        self.assertEqual(current_term["grade"], "2º")
        carried_history = next(book for book in current_term["books"] if book["id"] == "historia")
        self.assertTrue(carried_history["carried_forward"])
        self.assertEqual(migrated_app.config["SCHOOL_YEAR"], 2027)

    def test_api_requires_authentication(self):
        response = self.client.get("/api/students")
        self.assertEqual(response.status_code, 401)

    def test_student_archive_reactivation_and_safe_deletion(self):
        self.login()
        student_data = {
            "name": "Estudante de Teste",
            "enrollment": "2026000091",
            "grade": "1º",
            "course_id": self.informatics_course_id,
        }
        created = self.client.post(
            "/api/students",
            json=student_data,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(created.status_code, 201)

        missing_reason = self.client.post(
            f"/api/students/{student_data['enrollment']}/archive",
            json={"reason": "  "},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(missing_reason.status_code, 400)

        archived = self.client.post(
            f"/api/students/{student_data['enrollment']}/archive",
            json={"reason": "Transferência para outra instituição"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.get_json()["is_archived"])
        self.assertEqual(
            archived.get_json()["archive_reason"],
            "Transferência para outra instituição",
        )
        self.assertEqual(archived.get_json()["archived_by"], "servidor@ifc.edu.br")
        archived_list = self.client.get("/api/students").get_json()["students"]
        self.assertTrue(next(row for row in archived_list if row["enrollment"] == student_data["enrollment"])["is_archived"])

        reactivated = self.client.post(
            f"/api/students/{student_data['enrollment']}/reactivate",
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(reactivated.status_code, 200)
        self.assertFalse(reactivated.get_json()["is_archived"])
        self.assertEqual(reactivated.get_json()["school_year"], 2026)
        with sqlite3.connect(self.app.config["DATABASE_PATH"]) as database:
            events = database.execute(
                """SELECT action, actor_email, reason
                   FROM student_status_history
                   WHERE enrollment = ? ORDER BY id""",
                (student_data["enrollment"],),
            ).fetchall()
        self.assertEqual(
            events,
            [
                ("archive", "servidor@ifc.edu.br", "Transferência para outra instituição"),
                ("reactivate", "servidor@ifc.edu.br", None),
            ],
        )

        denied_delete = self.client.delete(
            f"/api/students/{student_data['enrollment']}",
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(denied_delete.status_code, 403)

        create_user(
            self.app.config["DATABASE_PATH"],
            "fabricio.bizotto@ifc.edu.br",
            "senha-admin-segura",
        )
        admin = self.app.test_client()
        admin_csrf = admin.get("/api/auth/session").get_json()["csrf_token"]
        logged_in = admin.post(
            "/api/auth/login",
            json={
                "email": "fabricio.bizotto@ifc.edu.br",
                "password": "senha-admin-segura",
            },
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(logged_in.status_code, 200)
        admin_csrf = logged_in.get_json()["csrf_token"]
        deleted = admin.delete(
            f"/api/students/{student_data['enrollment']}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(deleted.status_code, 200)

        student_data["enrollment"] = "2026000092"
        student_data["name"] = "Estudante com histórico"
        created = admin.post(
            "/api/students",
            json=student_data,
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(created.status_code, 201)
        detail = repository.find_student(
            self.app.config["DATABASE_PATH"], student_data["enrollment"]
        )
        signature_result = repository.record_signature(
            self.app.config["DATABASE_PATH"],
            student_data["enrollment"],
            detail["books"][0]["id"],
            "checkout",
            "assinatura-de-teste",
            "2026-01-10T12:00:00+00:00",
            "fabricio.bizotto@ifc.edu.br",
            2026,
        )
        self.assertIsNone(signature_result)
        blocked_delete = admin.delete(
            f"/api/students/{student_data['enrollment']}",
            headers={"X-CSRF-Token": admin_csrf},
        )
        self.assertEqual(blocked_delete.status_code, 409)
        self.assertIsNotNone(
            repository.find_student(
                self.app.config["DATABASE_PATH"], student_data["enrollment"]
            )
        )

    def test_mvc_view_and_static_assets_are_served_by_flask(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Importar CSV", page.data)
        self.assertIn("Exportar termos do ano".encode(), page.data)
        self.assertIn(b"Aviso de Privacidade", page.data)
        self.assertRegex(page.data, rb"/static/styles\.css\?v=\d+")
        self.assertRegex(page.data, rb"/static/js/main\.js\?v=\d+")
        self.assertRegex(page.data, rb'"/static/js/dashboard\.js": "/static/js/dashboard\.js\?v=\d+"')
        self.assertRegex(page.data, rb'"/static/js/api\.js": "/static/js/api\.js\?v=\d+"')
        self.assertIn(b"Livros selecionados", page.data)
        self.assertIn(b"signature-book", page.data)
        self.assertIn(b'data-student-status="completed"', page.data)
        self.assertIn(b'data-student-status="archived"', page.data)
        self.assertIn(b'id="student-archive-form"', page.data)
        self.assertIn(b'id="reactivate-student-button"', page.data)
        self.assertIn(b'id="delete-student-button"', page.data)
        self.assertIn(b'id="annual-backup-form"', page.data)
        self.assertIn(b'id="export-student-terms-button"', page.data)
        self.assertNotIn(b"Gerar acesso do aluno", page.data)
        self.assertIn(b'id="admin-school-year-current"', page.data)
        self.assertIn(b'id="school-year-form"', page.data)
        self.assertIn(b'id="course-form"', page.data)
        self.assertIn(b'id="course-abbreviation"', page.data)
        self.assertIn(b'role="tablist"', page.data)
        self.assertIn(b'id="admin-tab-courses"', page.data)
        self.assertIn(b'id="admin-tab-school-year"', page.data)
        self.assertIn(b'id="admin-tab-users"', page.data)
        self.assertIn(b'id="menu-button"', page.data)
        self.assertIn(b'id="student-course"', page.data)
        self.assertNotIn(b'id="dashboard-course-filter"', page.data)
        self.assertIn(b'id="students-course-filter"', page.data)
        self.assertIn(b'id="students-pagination"', page.data)
        self.assertIn(b'http://fabrica.videira.ifc.edu.br/', page.data)
        self.assertNotIn(b"Atualizado em tempo real", page.data)
        self.assertIn(b'id="dashboard-course-chart"', page.data)
        self.assertIn(b'id="dashboard-book-chart"', page.data)
        self.assertIn(b'id="dashboard-pending-table"', page.data)
        self.assertNotIn(b"QR Code", page.data)
        privacy = self.client.get("/privacidade")
        self.assertEqual(privacy.status_code, 200)
        self.assertRegex(privacy.data, rb"/static/styles\.css\?v=\d+")
        self.assertIn("15 a 17 anos".encode(), privacy.data)
        self.assertIn("controle interno e arquivo".encode(), privacy.data)
        self.assertEqual(self.client.get("/aluno").status_code, 404)
        self.assertEqual(self.client.get("/api/student-auth/session").status_code, 404)
        self.assertEqual(
            self.client.post("/api/student-qr/verify").status_code,
            404,
        )
        with self.client.get("/static/styles.css") as styles:
            self.assertEqual(styles.status_code, 200)
        with self.client.get("/static/js/main.js") as script:
            self.assertEqual(script.status_code, 200)
        with self.client.get("/static/js/dashboard.js") as script:
            self.assertEqual(script.status_code, 200)
        self.assertEqual(
            self.client.get("/static/vendor/qr-scanner/qr-scanner.umd.min.js").status_code,
            404,
        )
        database_path = self.app.config["DATABASE_PATH"]
        database = sqlite3.connect(database_path)
        try:
            initial_tables = {
                row[0]
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue(
                {"student_credentials", "student_qr_tokens", "student_qr_attempts"}.isdisjoint(
                    initial_tables
                )
            )
            database.executescript(
                """
                CREATE TABLE student_credentials (enrollment TEXT PRIMARY KEY);
                CREATE TABLE student_qr_tokens (code TEXT PRIMARY KEY);
                CREATE TABLE student_qr_attempts (user_id INTEGER PRIMARY KEY);
                """
            )
            database.execute(
                "INSERT INTO student_credentials (enrollment) VALUES ('historical-student')"
            )
            database.commit()
        finally:
            database.close()
        repository.initialize_db(database_path, 2026)
        database = sqlite3.connect(database_path)
        try:
            tables = {
                row[0]
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            historical_enrollment = database.execute(
                "SELECT enrollment FROM student_credentials"
            ).fetchone()[0]
        finally:
            database.close()
        self.assertTrue(
            {"student_credentials", "student_qr_tokens", "student_qr_attempts"}.issubset(
                tables
            )
        )
        self.assertEqual(historical_enrollment, "historical-student")

    def login_attempt(self, client, password, email="servidor@ifc.edu.br"):
        token = client.get("/api/auth/session").get_json()["csrf_token"]
        return client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-CSRF-Token": token},
        )

    def test_login_is_blocked_after_repeated_failures(self):
        for _ in range(5):
            self.assertEqual(self.login_attempt(self.client, "senha-errada-123").status_code, 401)
        blocked = self.login_attempt(self.client, "senha-segura-de-teste")
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Muitas tentativas", blocked.get_json()["error"])
        other_client = self.app.test_client()
        self.assertEqual(self.login_attempt(other_client, "senha-segura-de-teste").status_code, 429)

        database_path = self.app.config["DATABASE_PATH"]
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("UPDATE login_failures SET failed_at = failed_at - 16 * 60")
            connection.commit()
        finally:
            connection.close()
        self.assertEqual(self.login_attempt(self.client, "senha-segura-de-teste").status_code, 200)

    def test_successful_login_resets_failure_count(self):
        for _ in range(4):
            self.login_attempt(self.client, "senha-errada-123")
        self.assertEqual(self.login_attempt(self.client, "senha-segura-de-teste").status_code, 200)
        other_client = self.app.test_client()
        for _ in range(4):
            self.assertEqual(self.login_attempt(other_client, "senha-errada-123").status_code, 401)
        self.assertEqual(self.login_attempt(other_client, "senha-segura-de-teste").status_code, 200)

    def test_unknown_email_failures_are_also_limited(self):
        for _ in range(5):
            response = self.login_attempt(self.client, "qualquer-senha-1", "ninguem@ifc.edu.br")
            self.assertEqual(response.status_code, 401)
        response = self.login_attempt(self.client, "qualquer-senha-1", "ninguem@ifc.edu.br")
        self.assertEqual(response.status_code, 429)

    def test_login_requires_csrf_token(self):
        response = self.app.test_client().post(
            "/api/auth/login",
            json={"email": "servidor@ifc.edu.br", "password": "senha-segura-de-teste"},
        )
        self.assertEqual(response.status_code, 403)

    def test_logout_invalidates_copies_of_the_session_cookie(self):
        self.assertEqual(self.login().status_code, 200)
        copied = self.app.test_client()
        cookie = self.client.get_cookie("session")
        copied.set_cookie("session", cookie.value)
        self.assertEqual(copied.get("/api/students").status_code, 200)

        logout = self.client.post("/api/auth/logout", headers={"X-CSRF-Token": self.csrf()})
        self.assertEqual(logout.status_code, 200)
        replay = copied.get("/api/students")
        self.assertEqual(replay.status_code, 401)
        self.assertIn("encerrada", replay.get_json()["error"])
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/students").status_code, 200)

    def test_reactivated_account_does_not_restore_old_sessions(self):
        database_path = self.app.config["DATABASE_PATH"]
        self.login()
        user = repository.find_user(database_path, "servidor@ifc.edu.br")
        repository.update_user(database_path, user["id"], False, False)
        repository.update_user(database_path, user["id"], False, True)
        self.assertEqual(self.client.get("/api/students").status_code, 401)

    def test_session_expires_after_idle_time_and_max_age(self):
        self.login()
        with self.client.session_transaction() as session:
            session["last_seen"] -= self.app.config["SESSION_IDLE_TIMEOUT"] + 1
        expired = self.client.get("/api/students")
        self.assertEqual(expired.status_code, 401)
        self.assertIn("expirou", expired.get_json()["error"])
        self.assertFalse(self.client.get("/api/auth/session").get_json()["authenticated"])

        self.login()
        with self.client.session_transaction() as session:
            session["login_at"] -= self.app.config["SESSION_MAX_AGE"] + 1
        self.assertEqual(self.client.get("/api/students").status_code, 401)

        login = self.login()
        self.assertEqual(login.status_code, 200)
        self.assertIn("Expires=", login.headers["Set-Cookie"])
        self.assertEqual(self.client.get("/api/students").status_code, 200)

    @staticmethod
    def real_png_signature():
        import struct
        import zlib

        def chunk(kind, data):
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

        png = (
            bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes([0, 0x23, 0x4B, 0x3A, 0xFF, 0xFF, 0xFF])))
            + chunk(b"IEND", b"")
        )
        return "data:image/png;base64," + base64.b64encode(png).decode()

    def test_year_terms_export_zips_one_pdf_per_student_grouped_by_course(self):
        import zipfile

        self.assertEqual(self.client.get("/api/school-years/2026/terms.zip").status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/school-years/2026/terms.zip").status_code, 404)
        students = [
            ("2026000001", "Ana Júlia", self.informatics_course_id),
            ("2026000002", "Bruno/Teste", self.administration_course_id),
            ("2026000003", "Caio", self.informatics_course_id),
        ]
        for enrollment, name, course_id in students:
            created = self.client.post(
                "/api/students",
                json={"name": name, "enrollment": enrollment, "grade": "1º", "course_id": course_id},
                headers={"X-CSRF-Token": self.csrf()},
            )
            self.assertEqual(created.status_code, 201)
        checkout = self.client.post(
            "/api/students/2026000001/books/checkout",
            json={
                "book_ids": ["portugues-2026-1"],
                "signature": self.real_png_signature(),
                "enrollment_confirmation": "2026000001",
            },
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(checkout.status_code, 200)

        response = self.client.get("/api/school-years/2026/terms.zip")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/zip")
        self.assertIn('filename="termos-2026.zip"', response.headers["Content-Disposition"])
        with zipfile.ZipFile(BytesIO(response.data)) as archive:
            names = sorted(archive.namelist())
            self.assertEqual(
                names,
                [
                    "ADM - Tecnico em Administracao Integrado ao Ensino Medio/2026000002 - BrunoTeste.pdf",
                    "INFO - Tecnico em Informatica Integrado ao Ensino Medio/2026000001 - Ana Julia.pdf",
                    "INFO - Tecnico em Informatica Integrado ao Ensino Medio/2026000003 - Caio.pdf",
                ],
            )
            for name in names:
                self.assertTrue(archive.read(name).startswith(b"%PDF-"))

        self.assertEqual(self.client.get("/api/school-years/2027/terms.zip").status_code, 400)

    def test_app_requires_secret_key_outside_local_runs(self):
        database_path = str(Path(self.temp_dir.name) / "no-secret.db")
        with self.assertRaises(RuntimeError):
            create_app({"DATABASE_PATH": database_path, "SECRET_KEY": None})
        local_app = create_app(
            {"DATABASE_PATH": database_path, "SECRET_KEY": None},
            allow_ephemeral_secret=True,
        )
        self.assertTrue(local_app.config["SECRET_KEY"])


if __name__ == "__main__":
    unittest.main()
