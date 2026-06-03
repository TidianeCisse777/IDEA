#!/bin/sh

set -eu

if [ ! -f ".env" ]; then
  echo "Missing .env in the project root."
  echo "Copy share.env.example to .env and fill in the values before starting."
  exit 1
fi

echo "Starting IDEA with the project .env file only..."
env -i PATH="$PATH" HOME="$HOME" docker compose --env-file .env up -d --build
