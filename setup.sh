#!/bin/bash
# HEON Setup Script
# Installs dependencies and verifies the installation

set -e

echo "╔══════════════════════════════════════╗"
echo "║   HEON Setup — Free Financial Agent  ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Check for uv
if ! command -v uv &> /dev/null; then
    echo "Installing uv (fast Python package manager)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source $HOME/.cargo/env
fi

echo "Creating virtual environment and installing dependencies..."
cd "$(dirname "$0")"
uv sync

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   ✓ HEON installed successfully!     ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  1. Set an LLM API key:"
echo "     export OPENAI_API_KEY=your-key-here"
echo "     # OR"
echo "     export ANTHROPIC_API_KEY=your-key-here"
echo "     # OR"
echo "     export OPENROUTER_API_KEY=your-key-here"
echo "     # OR use local Ollama:"
echo "     export HEON_PROVIDER=ollama"
echo "     export HEON_MODEL=llama3.1"
echo ""
echo "  2. Run HEON:"
echo "     uv run heon \"Analyze AAPL\""
echo "     uv run heon  # interactive mode"
echo ""
