"""Create (or refresh) the Northwind Freight demo workspace for showing Citebase.

    python -m app.seed_demo --email demo@yourdomain.com --password 'a-long-password'

Loads the fictional company documents in eval/demo_company through the real
upload pipeline. Safe to re-run: if the demo user already exists, nothing is
duplicated. Run it once against production after deploying, then share the
demo login (it is a separate workspace; no real customer data is visible).
"""
import argparse

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.models import User
from eval.harness import seed_demo_org


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True, help="at least 8 characters")
    parser.add_argument("--org-name", default="Northwind Freight (demo)")
    args = parser.parse_args()
    if len(args.password) < 8:
        parser.error("password must be at least 8 characters")

    email = args.email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(func.lower(User.email) == email)):
            print(f"{email} already exists; nothing to do.")
            return
        org_id, _ = seed_demo_org(db, org_name=args.org_name, email=email,
                                  password_hash=hash_password(args.password))
    print(f"Demo workspace ready (org {org_id}). Sign in as {email}.")


if __name__ == "__main__":
    main()
