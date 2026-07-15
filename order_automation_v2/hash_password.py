import getpass
import sys

from auth import hash_password


def main() -> None:
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        sys.exit(1)
    print(hash_password(password))


if __name__ == "__main__":
    main()
