import argparse
import getpass
import os
import sqlite3

from acervo import create_app
from acervo.services import create_user


def main():
    app = create_app()
    parser = argparse.ArgumentParser(
        description="Controle de entrega dos livros didáticos do IFC Fraiburgo"
    )
    parser.add_subparsers(dest="command").add_parser(
        "create-user", help="Criar conta de servidor"
    )
    args = parser.parse_args()
    if args.command == "create-user":
        email = input("E-mail institucional: ")
        password = getpass.getpass("Senha (mínimo 12 caracteres): ")
        try:
            create_user(app.config["DATABASE_PATH"], email, password)
        except (ValueError, sqlite3.IntegrityError) as error:
            parser.error(str(error))
        print("Conta criada.")
        return
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)


if __name__ == "__main__":
    main()
