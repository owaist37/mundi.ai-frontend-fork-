# `alembic` Directory Overview

This directory contains the database migration scripts for the application, managed by [Alembic](https://alembic.sqlalchemy.org/en/latest/). Alembic is a lightweight database migration tool for usage with the SQLAlchemy Database Toolkit for Python.

## Key Components

-   **`env.py`**: This file is run whenever the `alembic` command is invoked. It reads configuration from `alembic.ini` and sets up the connection to the database.
-   **`script.py.mako`**: This is a Mako template file used to generate new migration scripts.
-   **`versions/`**: This directory contains the individual migration scripts. Each file in this directory represents a successive version of the database schema.

## How to Use

### Creating a New Migration

To generate a new migration script, use the `alembic revision` command:

```bash
alembic revision -m "A descriptive message about the migration"
```

This will create a new file in the `versions/` directory. You should then edit this file to include the necessary schema changes using Alembic's `op` directives.

### Applying Migrations

To apply all migrations and bring the database up to the latest version, use the `alembic upgrade` command:

```bash
alembic upgrade head
```

### Downgrading Migrations

To revert a migration, you can use the `alembic downgrade` command, specifying the version to which you want to revert. For example, to revert a single migration:

```bash
alembic downgrade -1
```
