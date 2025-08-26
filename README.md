# MCP GitHub PR Review Spec Maker

A Python MCP (Model Context Protocol) application that interacts with GitHub for Pull-Request information and review specifications.

## 🚀 Features

- **GitHub Integration**: Fetch and analyze pull request data
- **MCP Protocol**: Implements the Model Context Protocol for AI model interactions
- **Modern Python**: Built with Python 3.8+ and modern async patterns
- **UV Package Management**: Fast dependency management with UV
- **Development Container**: Complete development environment setup

## 🛠️ Development Setup

### Option 1: Using Dev Container (Recommended)

This project includes a complete development container setup that provides a consistent environment for all developers.

#### Prerequisites

- [Docker](https://www.docker.com/get-started)
- [VS Code](https://code.visualstudio.com/) with the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

#### Setup Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/cool-kids-inc/mcp-github-pr-review-spec-maker.git
   cd mcp-github-pr-review-spec-maker
   ```

2. **Open in VS Code**
   ```bash
   code .
   ```

3. **Open in Dev Container**
   - When VS Code opens, you'll see a notification asking if you want to "Reopen in Container"
   - Click "Reopen in Container" or use the command palette (`Ctrl+Shift+P`) and run "Dev Containers: Reopen in Container"

4. **Wait for setup**
   - The container will build and set up the development environment
   - Dependencies will be installed automatically
   - Pre-commit hooks will be configured

5. **Configure environment**
   - Update the `.env` file with your GitHub token
   - The file will be created automatically during setup

### Option 2: Local Development

If you prefer to develop locally:

#### Prerequisites

- Python 3.8 or higher
- [UV](https://docs.astral.sh/uv/) package manager

#### Setup Steps

1. **Install UV**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. **Clone and setup**
   ```bash
   git clone https://github.com/cool-kids-inc/mcp-github-pr-review-spec-maker.git
   cd mcp-github-pr-review-spec-maker
   uv sync
   ```

3. **Install pre-commit hooks**
   ```bash
   uv run pre-commit install
   ```

4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your GitHub token
   ```

## 📦 Project Structure

```
mcp-github-pr-review-spec-maker/
├── .devcontainer/          # Dev container configuration
│   ├── devcontainer.json   # VS Code dev container settings
│   ├── Dockerfile         # Container image definition
│   ├── .gitconfig         # Git configuration
│   └── post-create.sh     # Post-creation setup script
├── mcp_github_pr_review/  # Main application code
├── tests/                 # Test files
├── docs/                  # Documentation
├── pyproject.toml         # Project configuration and dependencies
├── .pre-commit-config.yaml # Pre-commit hooks configuration
├── .env                   # Environment variables (created during setup)
└── README.md             # This file
```

## 🧪 Development Commands

### Using UV (Recommended)

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=mcp_github_pr_review

# Format code
uv run black .

# Sort imports
uv run isort .

# Type checking
uv run mypy .

# Linting
uv run flake8 .
uv run pylint mcp_github_pr_review/

# Run pre-commit hooks on all files
uv run pre-commit run --all-files
```

### Using pip (Alternative)

```bash
# Install dependencies
pip install -e ".[dev]"

# Run commands (same as above, but without 'uv run')
pytest
black .
isort .
mypy .
flake8 .
pylint mcp_github_pr_review/
pre-commit run --all-files
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file with the following variables:

```env
# GitHub API Configuration
GITHUB_TOKEN=your_github_token_here
GITHUB_API_URL=https://api.github.com

# MCP Configuration
MCP_SERVER_HOST=localhost
MCP_SERVER_PORT=8000

# Development Configuration
DEBUG=true
LOG_LEVEL=INFO
```

### GitHub Token Setup

1. Go to [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. Generate a new token with the following scopes:
   - `repo` (for private repositories)
   - `public_repo` (for public repositories)
   - `read:org` (if accessing organization repositories)
3. Copy the token and add it to your `.env` file

## 🧪 Testing

The project uses pytest for testing with comprehensive coverage reporting.

```bash
# Run all tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=mcp_github_pr_review --cov-report=html

# Run specific test file
uv run pytest tests/test_github_api.py

# Run tests with specific markers
uv run pytest -m "not slow"
uv run pytest -m integration
```

## 📝 Code Quality

The project enforces high code quality standards through:

- **Black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **mypy**: Type checking
- **pylint**: Additional linting
- **pre-commit**: Automated quality checks

All quality checks run automatically on commit when using the dev container.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run quality checks (`uv run pre-commit run --all-files`)
5. Run tests (`uv run pytest`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

If you encounter any issues:

1. Check the [Issues](https://github.com/cool-kids-inc/mcp-github-pr-review-spec-maker/issues) page
2. Create a new issue with detailed information about your problem
3. Include your environment details and error messages

## 🔗 Related Links

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [GitHub API Documentation](https://docs.github.com/en/rest)
- [UV Package Manager](https://docs.astral.sh/uv/)
- [VS Code Dev Containers](https://code.visualstudio.com/docs/devcontainers/containers)

