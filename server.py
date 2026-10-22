import argparse
import getpass
import os
import sqlite3
from datetime import datetime

from acervo import create_app
from acervo import repository
from acervo.models import now_iso
from acervo.services import create_user


def main():
    parser = argparse.ArgumentParser(
        description="Controle de entrega dos livros didáticos do IFC Fraiburgo"
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("create-user", help="Criar conta de servidor")
    commands.add_parser(
        "reset-dev-data",
        help="Apagar estudantes do banco dev, voltar ao ano corrente e inserir dados fictícios",
    )
    args = parser.parse_args()
    if args.command == "create-user":
        app = create_app()
        email = input("E-mail institucional: ")
        password = getpass.getpass("Senha (mínimo 12 caracteres): ")
        try:
            create_user(app.config["DATABASE_PATH"], email, password)
        except (ValueError, sqlite3.IntegrityError) as error:
            parser.error(str(error))
        print("Conta criada.")
        return
    if args.command == "reset-dev-data":
        if os.environ.get("APP_ENV") != "development":
            parser.error("Este comando só pode ser executado com APP_ENV=development.")
        app = create_app()
        school_year = datetime.now().year
        database_path = app.config["DATABASE_PATH"]
        repository.reset_dev_students(
            database_path,
            school_year,
            [
                ("2026000001", "Estudante Demonstração 1", "1º", now_iso()),
                ("2026000002", "Estudante Demonstração 2", "2º", now_iso()),
                ("2026000003", "Estudante Demonstração 3", "3º", now_iso()),
            ],
        )
        print(
            f"Banco de desenvolvimento resetado para {school_year}; "
            "3 estudantes fictícios foram cadastrados. Contas de servidores preservadas."
        )
        return
    app = create_app()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)


if __name__ == "__main__":
    main()
