#!/usr/bin/env python
"""Print a Werkzeug password hash. The password is not taken from the command line."""
import getpass
import sys

from werkzeug.security import generate_password_hash

if sys.stdin.isatty():
    password = getpass.getpass('Admin password: ')
else:
    password = sys.stdin.readline().rstrip('\n')
if len(password) < 12:
    print('Password must be at least 12 characters.', file=sys.stderr)
    sys.exit(1)
sys.stdout.write(generate_password_hash(password) + '\n')
