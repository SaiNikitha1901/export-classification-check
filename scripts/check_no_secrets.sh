#!/usr/bin/env bash
# D4: no credentials, provider endpoints or model identifiers in the repository.
# Allowed places: .env.example (the documented configuration) and docs/.
set -uo pipefail
cd "$(dirname "$0")/.."
files=$(git ls-files 2>/dev/null || find . -type f -not -path './.git/*')
files=$(echo "$files" | grep -v -E '^(\./)?(\.env\.example|docs/|scripts/check_no_secrets\.sh|corpus/|.*\.pdf$|.*\.png$)')
patterns='(sk-[A-Za-z0-9]{20,}|gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|hf_[A-Za-z0-9]{30,}|api\.openai\.com|api\.groq\.com|generativelanguage\.googleapis\.com|api\.anthropic\.com|openrouter\.ai|gpt-4|gpt-3\.5|llama-?3|mixtral|gemini-[0-9]|claude-[0-9a-z]|all-MiniLM)'
hits=$(echo "$files" | xargs grep -n -I -E "$patterns" 2>/dev/null)
if [ -n "$hits" ]; then
  echo "D4 violation: move these values into .env / .env.example:"; echo "$hits"; exit 1
fi
echo "D4 check passed: no credentials, provider endpoints or model identifiers outside .env.example/docs"
