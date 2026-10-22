import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import SHARED_BOOKS, book_list


@contextmanager
def database(database_path):
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_db(database_path, school_year):
    with database(database_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0 CHECK (is_admin IN (0, 1)),
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS students (
                enrollment TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                grade TEXT NOT NULL CHECK (grade IN ('1º', '2º', '3º')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS application_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS book_signatures (
                enrollment TEXT NOT NULL REFERENCES students(enrollment) ON DELETE CASCADE,
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
            CREATE TABLE IF NOT EXISTS book_signature_history (
                id INTEGER PRIMARY KEY,
                enrollment TEXT NOT NULL REFERENCES students(enrollment) ON DELETE CASCADE,
                book_id TEXT NOT NULL,
                school_year INTEGER NOT NULL,
                action TEXT NOT NULL CHECK (
                    action IN ('checkout', 'return', 'cancel_checkout', 'cancel_return')
                ),
                signature TEXT,
                recorded_at TEXT NOT NULL,
                actor_email TEXT,
                reason TEXT
            );
            CREATE TABLE IF NOT EXISTS student_years (
                enrollment TEXT NOT NULL REFERENCES students(enrollment) ON DELETE CASCADE,
                school_year INTEGER NOT NULL,
                grade TEXT NOT NULL CHECK (grade IN ('1º', '2º', '3º')),
                status TEXT NOT NULL CHECK (status IN ('active', 'completed')),
                PRIMARY KEY (enrollment, school_year)
            );
            CREATE TABLE IF NOT EXISTS student_year_books (
                enrollment TEXT NOT NULL,
                school_year INTEGER NOT NULL,
                book_id TEXT NOT NULL,
                PRIMARY KEY (enrollment, school_year, book_id),
                FOREIGN KEY (enrollment, school_year)
                    REFERENCES student_years(enrollment, school_year) ON DELETE CASCADE,
                FOREIGN KEY (enrollment, book_id)
                    REFERENCES book_signatures(enrollment, book_id) ON DELETE CASCADE
            );
            """
        )
        user_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_admin" not in user_columns:
            db.execute(
                "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0"
            )
        if "is_active" not in user_columns:
            db.execute(
                "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )
        db.execute(
            "UPDATE users SET is_admin = 1 WHERE lower(email) = ?",
            ("fabricio.bizotto@ifc.edu.br",),
        )
        stored_year = db.execute(
            "SELECT value FROM application_settings WHERE key = 'school_year'"
        ).fetchone()
        school_year = max(
            school_year, int(stored_year["value"]) if stored_year else school_year
        )
        _migrate_legacy_book_ids(db)
        _initialize_school_years(db, school_year)
        _backfill_school_year_books(db)
        db.execute(
            """INSERT INTO application_settings (key, value) VALUES ('school_year', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (str(school_year),),
        )
        db.execute(
            """INSERT INTO book_signature_history
                   (enrollment, book_id, school_year, action, signature, recorded_at, actor_email)
               SELECT b.enrollment, b.book_id, b.issue_year, 'checkout',
                      b.checkout_signature, COALESCE(b.checkout_at, ''), NULL
               FROM book_signatures b
               WHERE b.checkout_signature IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM book_signature_history h
                     WHERE h.enrollment = b.enrollment AND h.book_id = b.book_id
                       AND h.action = 'checkout'
                 )"""
        )
        db.execute(
            """INSERT INTO book_signature_history
                   (enrollment, book_id, school_year, action, signature, recorded_at, actor_email)
               SELECT b.enrollment, b.book_id, b.issue_year, 'return',
                      b.return_signature, COALESCE(b.return_at, ''), b.return_by
               FROM book_signatures b
               WHERE b.return_signature IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM book_signature_history h
                     WHERE h.enrollment = b.enrollment AND h.book_id = b.book_id
                       AND h.action = 'return'
                 )"""
        )
    return school_year


def get_school_year(database_path, fallback):
    with database(database_path) as db:
        row = db.execute(
            "SELECT value FROM application_settings WHERE key = 'school_year'"
        ).fetchone()
    return int(row["value"]) if row else fallback


def update_school_year(database_path, school_year):
    with database(database_path) as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT value FROM application_settings WHERE key = 'school_year'"
        ).fetchone()
        current_year = int(current["value"]) if current else school_year
        if school_year < current_year:
            return "cannot_decrease"
        _initialize_school_years(db, school_year)
        _backfill_school_year_books(db)
        db.execute(
            """INSERT INTO application_settings (key, value) VALUES ('school_year', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (str(school_year),),
        )
    return None


def reset_dev_students(database_path, school_year, students):
    with database(database_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM students")
        db.execute(
            """INSERT INTO application_settings (key, value) VALUES ('school_year', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (str(school_year),),
        )
        for enrollment, name, grade, created_at in students:
            db.execute(
                """INSERT INTO students (enrollment, name, grade, created_at)
                   VALUES (?, ?, ?, ?)""",
                (enrollment, name, grade, created_at),
            )
            _insert_school_year(db, enrollment, school_year, grade)


def _migrate_legacy_book_ids(db):
    rows = db.execute(
        """SELECT enrollment, book_id, issue_year FROM book_signatures
           WHERE book_id GLOB 'portugues-[123]' OR book_id GLOB 'matematica-[123]'"""
    ).fetchall()
    for row in rows:
        subject, grade_number = row["book_id"].split("-")
        new_id = f"{subject}-{row['issue_year']}-{grade_number}"
        current = db.execute(
            "SELECT 1 FROM book_signatures WHERE enrollment = ? AND book_id = ?",
            (row["enrollment"], new_id),
        ).fetchone()
        if current:
            continue
        title = (
            f"360° Língua Portuguesa — {grade_number}º ano"
            if subject == "portugues"
            else f"Do seu jeito — Matemática — Volume {grade_number}"
        )
        db.execute(
            """UPDATE book_signatures SET book_id = ?, title = ?
               WHERE enrollment = ? AND book_id = ?""",
            (new_id, title, row["enrollment"], row["book_id"]),
        )


def _insert_school_year(db, enrollment, school_year, grade, status="active"):
    db.execute(
        """INSERT OR IGNORE INTO student_years (enrollment, school_year, grade, status)
           VALUES (?, ?, ?, ?)""",
        (enrollment, school_year, grade, status),
    )
    if status != "active":
        return
    existing = {
        row["book_id"]: row
        for row in db.execute(
            """SELECT book_id, checkout_signature, return_signature, issue_year FROM book_signatures
               WHERE enrollment = ?""",
            (enrollment,),
        ).fetchall()
    }
    for book in book_list(grade, school_year):
        prior = existing.get(book["id"])
        if prior:
            if book["id"] in {book_id for book_id, _ in SHARED_BOOKS}:
                if prior["return_signature"]:
                    continue
                if not prior["checkout_signature"]:
                    db.execute(
                        """UPDATE book_signatures SET issue_year = ?
                           WHERE enrollment = ? AND book_id = ?""",
                        (school_year, enrollment, book["id"]),
                    )
            db.execute(
                """INSERT OR IGNORE INTO student_year_books (enrollment, school_year, book_id)
                   VALUES (?, ?, ?)""",
                (enrollment, school_year, book["id"]),
            )
            continue
        db.execute(
            """INSERT INTO book_signatures (enrollment, book_id, title, issue_year)
               VALUES (?, ?, ?, ?)""",
            (enrollment, book["id"], book["title"], school_year),
        )
        db.execute(
            """INSERT INTO student_year_books (enrollment, school_year, book_id)
               VALUES (?, ?, ?)""",
            (enrollment, school_year, book["id"]),
        )


def _backfill_school_year_books(db):
    shared_ids = tuple(book_id for book_id, _ in SHARED_BOOKS)
    placeholders = ",".join("?" for _ in shared_ids)
    db.execute(
        """INSERT OR IGNORE INTO student_year_books (enrollment, school_year, book_id)
           SELECT y.enrollment, y.school_year, b.book_id
           FROM student_years y
           JOIN book_signatures b ON b.enrollment = y.enrollment
           WHERE y.status = 'active' AND (
               b.issue_year = y.school_year OR (
                   b.book_id IN (""" + placeholders + """)
                   AND b.checkout_signature IS NOT NULL
                   AND b.return_signature IS NULL
                   AND b.issue_year < y.school_year
               )
           )""",
        shared_ids,
    )


def _initialize_school_years(db, current_year):
    students = db.execute(
        "SELECT enrollment, grade FROM students ORDER BY enrollment"
    ).fetchall()
    for student in students:
        years = db.execute(
            """SELECT school_year, grade, status FROM student_years
               WHERE enrollment = ? ORDER BY school_year""",
            (student["enrollment"],),
        ).fetchall()
        if not years:
            first_issue = db.execute(
                "SELECT MIN(issue_year) AS first_year FROM book_signatures WHERE enrollment = ?",
                (student["enrollment"],),
            ).fetchone()["first_year"]
            if first_issue and first_issue > current_year:
                raise ValueError(
                    f"O ano letivo configurado ({current_year}) é anterior ao primeiro "
                    f"empréstimo registrado ({first_issue})."
                )
            start_year = first_issue or current_year
            legacy_grade = student["grade"]
            legacy_language = db.execute(
                """SELECT book_id FROM book_signatures
                   WHERE enrollment = ? AND book_id GLOB 'portugues-[0-9]*-[123]'
                   ORDER BY issue_year LIMIT 1""",
                (student["enrollment"],),
            ).fetchone()
            if legacy_language:
                legacy_grade = f"{legacy_language['book_id'].split('-')[-1]}º"
            _insert_school_year(db, student["enrollment"], start_year, legacy_grade)
            years = db.execute(
                """SELECT school_year, grade, status FROM student_years
                   WHERE enrollment = ? ORDER BY school_year""",
                (student["enrollment"],),
            ).fetchall()

        latest = years[-1]
        if latest["school_year"] > current_year:
            raise ValueError(
                f"O ano letivo configurado ({current_year}) é anterior ao último ciclo "
                f"registrado ({latest['school_year']})."
            )
        for year in range(latest["school_year"] + 1, current_year + 1):
            if latest["status"] == "completed":
                break
            if latest["grade"] == "3º":
                db.execute(
                    """UPDATE student_years SET status = 'completed'
                       WHERE enrollment = ? AND school_year = ?""",
                    (student["enrollment"], latest["school_year"]),
                )
                break
            promoted_grade = f"{int(latest['grade'][0]) + 1}º"
            _insert_school_year(db, student["enrollment"], year, promoted_grade)
            latest = db.execute(
                """SELECT school_year, grade, status FROM student_years
                   WHERE enrollment = ? AND school_year = ?""",
                (student["enrollment"], year),
            ).fetchone()
        db.execute(
            """UPDATE students SET grade = (
                   SELECT grade FROM student_years
                   WHERE enrollment = ? ORDER BY school_year DESC LIMIT 1
               ) WHERE enrollment = ?""",
            (student["enrollment"], student["enrollment"]),
        )


def find_user(database_path, email):
    with database(database_path) as db:
        row = db.execute(
            """SELECT id, email, password_hash, is_admin, is_active
               FROM users WHERE email = ?""",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def find_user_by_id(database_path, user_id):
    with database(database_path) as db:
        row = db.execute(
            """SELECT id, email, is_admin, is_active FROM users
               WHERE id = ?""",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None


def add_user(database_path, email, password_hash, created_at, is_admin=False):
    with database(database_path) as db:
        cursor = db.execute(
            """INSERT INTO users (email, password_hash, created_at, is_admin, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (
                email,
                password_hash,
                created_at,
                int(is_admin or email.lower() == "fabricio.bizotto@ifc.edu.br"),
            ),
        )
    return cursor.lastrowid


def list_users(database_path):
    with database(database_path) as db:
        rows = db.execute(
            """SELECT id, email, is_admin, is_active, created_at
               FROM users ORDER BY email COLLATE NOCASE"""
        ).fetchall()
    return [dict(row) for row in rows]


def update_user(database_path, user_id, is_admin, is_active):
    with database(database_path) as db:
        user = db.execute(
            "SELECT id, is_admin, is_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user:
            return "not_found"
        if user["is_admin"] and (not is_admin or not is_active):
            active_admins = db.execute(
                "SELECT COUNT(*) FROM users WHERE is_admin = 1 AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                return "last_admin"
        db.execute(
            "UPDATE users SET is_admin = ?, is_active = ? WHERE id = ?",
            (int(is_admin), int(is_active), user_id),
        )
    return None


def add_student(database_path, enrollment, name, grade, created_at, school_year):
    with database(database_path) as db:
        db.execute(
            "INSERT INTO students (enrollment, name, grade, created_at) VALUES (?, ?, ?, ?)",
            (enrollment, name, grade, created_at),
        )
        _insert_school_year(db, enrollment, school_year, grade)


def import_students(database_path, students, school_year):
    imported = 0
    with database(database_path) as db:
        for student in students:
            cursor = db.execute(
                """INSERT OR IGNORE INTO students (enrollment, name, grade, created_at)
                   VALUES (?, ?, ?, ?)""",
                (
                    student["enrollment"],
                    student["name"],
                    student["grade"],
                    student["created_at"],
                ),
            )
            if cursor.rowcount == 0:
                continue
            _insert_school_year(db, student["enrollment"], school_year, student["grade"])
            imported += 1
    return imported


def update_student(database_path, enrollment, name, grade, school_year):
    with database(database_path) as db:
        current = db.execute(
            "SELECT grade FROM students WHERE enrollment = ?", (enrollment,)
        ).fetchone()
        if not current:
            return False
        if current["grade"] != grade:
            previous_grade = current["grade"][0]
            db.execute(
                """DELETE FROM book_signatures WHERE enrollment = ?
                   AND issue_year = ? AND book_id IN (?, ?) AND checkout_signature IS NULL""",
                (
                    enrollment,
                    school_year,
                    f"portugues-{school_year}-{previous_grade}",
                    f"matematica-{school_year}-{previous_grade}",
                ),
            )
        db.execute(
            "UPDATE students SET name = ?, grade = ? WHERE enrollment = ?",
            (name, grade, enrollment),
        )
        db.execute(
            """UPDATE student_years SET grade = ?
               WHERE enrollment = ? AND school_year = ? AND status = 'active'""",
            (grade, enrollment, school_year),
        )
        _insert_school_year(db, enrollment, school_year, grade)
    return True


def find_student(database_path, enrollment, school_year=None):
    with database(database_path) as db:
        student = db.execute(
            "SELECT enrollment, name, grade, created_at FROM students WHERE enrollment = ?",
            (enrollment,),
        ).fetchone()
        if not student:
            return None
        years = db.execute(
            """SELECT school_year, grade, status FROM student_years
               WHERE enrollment = ? ORDER BY school_year DESC""",
            (enrollment,),
        ).fetchall()
        if not years:
            return None
        selected_year = school_year or years[0]["school_year"]
        selected_term = next((year for year in years if year["school_year"] == selected_year), None)
        if not selected_term:
            return None
        books = db.execute(
            """SELECT b.book_id AS id, b.title, b.issue_year,
                      CASE WHEN b.issue_year <= ? THEN b.checkout_signature END AS checkout_signature,
                      CASE WHEN b.issue_year <= ? THEN b.checkout_at END AS checkout_at,
                      CASE WHEN b.issue_year <= ? THEN b.return_signature END AS return_signature,
                      CASE WHEN b.issue_year <= ? THEN b.return_at END AS return_at,
                      CASE WHEN b.issue_year <= ? THEN b.return_by END AS return_by,
                      CASE WHEN b.issue_year < ? THEN 1 ELSE 0 END AS carried_forward
               FROM student_year_books yb
               JOIN book_signatures b
                 ON b.enrollment = yb.enrollment AND b.book_id = yb.book_id
               WHERE yb.enrollment = ? AND yb.school_year = ?
               ORDER BY b.issue_year, b.rowid""",
            (
                selected_year,
                selected_year,
                selected_year,
                selected_year,
                selected_year,
                selected_year,
                enrollment,
                selected_year,
            ),
        ).fetchall()
    return {
        **dict(student),
        "grade": selected_term["grade"],
        "school_year": selected_term["school_year"],
        "status": selected_term["status"],
        "years": [dict(year) for year in years],
        "books": [dict(book) for book in books],
    }


def list_students(database_path, query, school_year, exact_year=False):
    year_join = (
        "y.enrollment = s.enrollment AND y.school_year = ?"
        if exact_year
        else """y.enrollment = s.enrollment AND y.school_year = COALESCE(
                   (SELECT MAX(active_year.school_year) FROM student_years active_year
                    WHERE active_year.enrollment = s.enrollment AND active_year.school_year <= ?),
                   (SELECT MAX(last_year.school_year) FROM student_years last_year
                    WHERE last_year.enrollment = s.enrollment)
               )"""
    )
    with database(database_path) as db:
        rows = db.execute(
            """SELECT s.enrollment, s.name, COALESCE(y.grade, s.grade) AS grade,
                      COALESCE(y.status, 'completed') AS status, s.created_at,
                      COUNT(b.book_id) AS total_books,
                      SUM(CASE WHEN b.checkout_signature IS NOT NULL THEN 1 ELSE 0 END) AS checked_out,
                      SUM(CASE WHEN b.checkout_signature IS NOT NULL AND b.return_signature IS NULL
                               THEN 1 ELSE 0 END) AS awaiting_return
               FROM students s
               LEFT JOIN student_years y ON """ + year_join + """
               LEFT JOIN student_year_books yb
                 ON yb.enrollment = y.enrollment AND yb.school_year = y.school_year
               LEFT JOIN book_signatures b
                 ON b.enrollment = yb.enrollment AND b.book_id = yb.book_id
               WHERE y.school_year IS NOT NULL AND (s.name LIKE ? OR s.enrollment LIKE ?)
               GROUP BY s.enrollment
               ORDER BY s.name COLLATE NOCASE""",
            (
                school_year,
                f"%{query}%",
                f"%{query}%",
            ),
        ).fetchall()
    return [
        {
            **dict(row),
            "checked_out": row["checked_out"] or 0,
            "awaiting_return": row["awaiting_return"] or 0,
        }
        for row in rows
    ]


def list_school_years(database_path, current_year):
    with database(database_path) as db:
        rows = db.execute(
            "SELECT DISTINCT school_year FROM student_years ORDER BY school_year DESC"
        ).fetchall()
    years = {row["school_year"] for row in rows}
    years.add(current_year)
    return sorted(years, reverse=True)


def record_signature(
    database_path,
    enrollment,
    book_id,
    action,
    signature,
    signed_at,
    actor_email,
    school_year,
):
    with database(database_path) as db:
        book = db.execute(
            """SELECT checkout_signature, return_signature, issue_year FROM book_signatures
               WHERE enrollment = ? AND book_id = ?""",
            (enrollment, book_id),
        ).fetchone()
        if not book:
            return "book_not_found"
        if action == "checkout" and book["issue_year"] != school_year:
            return "wrong_school_year"
        if action == "return" and not book["checkout_signature"]:
            return "checkout_required"
        if action == "checkout" and book["checkout_signature"]:
            return "already_checked_out"
        if action == "return" and book["return_signature"]:
            return "already_returned"
        if action == "checkout":
            db.execute(
                """UPDATE book_signatures SET checkout_signature = ?, checkout_at = ?
                   WHERE enrollment = ? AND book_id = ?""",
                (signature, signed_at, enrollment, book_id),
            )
            db.execute(
                """INSERT INTO book_signature_history
                       (enrollment, book_id, school_year, action, signature, recorded_at, actor_email)
                   VALUES (?, ?, ?, 'checkout', ?, ?, ?)""",
                (enrollment, book_id, school_year, signature, signed_at, actor_email),
            )
        else:
            db.execute(
                """UPDATE book_signatures SET return_signature = ?, return_at = ?, return_by = ?
                   WHERE enrollment = ? AND book_id = ?""",
                (signature, signed_at, actor_email, enrollment, book_id),
            )
            db.execute(
                """INSERT INTO book_signature_history
                       (enrollment, book_id, school_year, action, signature, recorded_at, actor_email)
                   VALUES (?, ?, ?, 'return', ?, ?, ?)""",
                (enrollment, book_id, school_year, signature, signed_at, actor_email),
            )
    return None


def record_signatures(
    database_path,
    enrollment,
    book_ids,
    signature,
    signed_at,
    actor_email,
    school_year,
):
    placeholders = ", ".join("?" for _ in book_ids)
    with database(database_path) as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            f"""SELECT b.book_id, b.title, b.issue_year, b.checkout_signature,
                       yb.book_id AS assigned_book_id
                FROM book_signatures b
                LEFT JOIN student_year_books yb
                  ON yb.enrollment = b.enrollment
                 AND yb.school_year = ?
                 AND yb.book_id = b.book_id
                WHERE b.enrollment = ? AND b.book_id IN ({placeholders})""",
            (school_year, enrollment, *book_ids),
        ).fetchall()
        books = {row["book_id"]: row for row in rows}
        for book_id in book_ids:
            book = books.get(book_id)
            if not book or not book["assigned_book_id"]:
                return "book_not_found", book_id
            if book["issue_year"] != school_year:
                return "wrong_school_year", book_id
            if book["checkout_signature"]:
                return "already_checked_out", book_id

        for book_id in book_ids:
            db.execute(
                """UPDATE book_signatures SET checkout_signature = ?, checkout_at = ?
                   WHERE enrollment = ? AND book_id = ?""",
                (signature, signed_at, enrollment, book_id),
            )
            db.execute(
                """INSERT INTO book_signature_history
                       (enrollment, book_id, school_year, action, signature, recorded_at, actor_email)
                   VALUES (?, ?, ?, 'checkout', ?, ?, ?)""",
                (enrollment, book_id, school_year, signature, signed_at, actor_email),
            )
    return None


def get_book_signature_history(database_path, enrollment, book_id):
    with database(database_path) as db:
        if not db.execute(
            """SELECT 1 FROM book_signatures
               WHERE enrollment = ? AND book_id = ?""",
            (enrollment, book_id),
        ).fetchone():
            return None
        rows = db.execute(
            """SELECT id, school_year, action, signature, recorded_at,
                      actor_email, reason
               FROM book_signature_history
               WHERE enrollment = ? AND book_id = ?
               ORDER BY id DESC""",
            (enrollment, book_id),
        ).fetchall()
    return [dict(row) for row in rows]


def cancel_book_signature(
    database_path, enrollment, book_id, action, reason, recorded_at, actor_email, school_year
):
    with database(database_path) as db:
        book = db.execute(
            """SELECT checkout_signature, return_signature
               FROM book_signatures WHERE enrollment = ? AND book_id = ?""",
            (enrollment, book_id),
        ).fetchone()
        if not book:
            return "book_not_found"
        if action == "return":
            if not book["return_signature"]:
                return "return_not_found"
            db.execute(
                """UPDATE book_signatures
                   SET return_signature = NULL, return_at = NULL, return_by = NULL
                   WHERE enrollment = ? AND book_id = ?""",
                (enrollment, book_id),
            )
            history_action = "cancel_return"
        elif action == "checkout":
            if not book["checkout_signature"]:
                return "checkout_not_found"
            if book["return_signature"]:
                return "return_must_be_cancelled_first"
            db.execute(
                """UPDATE book_signatures
                   SET checkout_signature = NULL, checkout_at = NULL
                   WHERE enrollment = ? AND book_id = ?""",
                (enrollment, book_id),
            )
            history_action = "cancel_checkout"
        else:
            return "invalid_action"
        db.execute(
            """INSERT INTO book_signature_history
                   (enrollment, book_id, school_year, action, recorded_at, actor_email, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (enrollment, book_id, school_year, history_action, recorded_at, actor_email, reason),
        )
    return None
