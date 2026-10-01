#!/bin/sh
set -eu

MODEL="${1:-smollm2:135m}"

if command -v ollama >/dev/null 2>&1; then
  ollama pull "$MODEL"
else
  docker compose exec ollama ollama pull "$MODEL"
fi
