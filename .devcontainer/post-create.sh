#!/bin/bash

# Post-create script for dev container setup

set -e

echo "🚀 Setting up development environment..."

# Install UV
echo "📦 Installing UV package manager..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="/root/.cargo/bin:$PATH"

# Install development tools
echo "🔧 Installing development tools..."
pip3 install --no-cache-dir \
    black \
    flake8 \
    isort \
    mypy \
    pylint \
    pytest \
    pytest-cov \
    pre-commit

# Install UV dependencies
echo "📦 Installing dependencies with UV..."
uv sync

# Set up pre-commit hooks
echo "🔧 Setting up pre-commit hooks..."
uv run pre-commit install

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cat > .env << EOF
# GitHub API Configuration
GITHUB_TOKEN=your_github_token_here
GITHUB_API_URL=https://api.github.com

# MCP Configuration
MCP_SERVER_HOST=localhost
MCP_SERVER_PORT=8000

# Development Configuration
DEBUG=true
LOG_LEVEL=INFO
EOF
    echo "✅ Created .env file - please update with your GitHub token"
fi

# Create basic project structure if it doesn't exist
if [ ! -d "mcp_github_pr_review" ]; then
    echo "📁 Creating project structure..."
    mkdir -p mcp_github_pr_review
    mkdir -p tests
    mkdir -p docs
fi

# Create __init__.py files
touch mcp_github_pr_review/__init__.py
touch tests/__init__.py

# Set up git configuration
echo "🔧 Configuring git..."
git config --global core.autocrlf input
git config --global core.editor "code --wait"

echo "✅ Development environment setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Update .env file with your GitHub token"
echo "2. Run 'uv run pytest' to run tests"
echo "3. Run 'uv run black .' to format code"
echo "4. Run 'uv run mypy .' to type check"
echo ""
echo "🎉 Happy coding!"
