# `driftdb` Submodule Overview

This directory contains a Git submodule for [DriftDB](https://driftdb.com/), a real-time data backend for browser-based applications.

## Purpose

DriftDB provides a way to synchronize state between multiple clients in real-time. It is used in this project to enable collaborative features and to ensure that all users have a consistent view of the application state.

## Official Documentation

For more detailed information about DriftDB, including its API and usage, please refer to the official documentation:

-   **Website:** [https://driftdb.com/](https://driftdb.com/)
-   **GitHub Repository:** [https://github.com/jamsocket/driftdb](https://github.com/jamsocket/driftdb)

## Working with the Submodule

To initialize the submodule after cloning the main repository, run:

```bash
git submodule update --init --recursive
```

To update the submodule to the latest version, run:

```bash
git submodule update --remote
```
