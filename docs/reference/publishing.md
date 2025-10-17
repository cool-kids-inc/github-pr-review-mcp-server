# Publishing to PyPI

1. Ensure the repository uses the `src/` layout and package metadata lives in `pyproject.toml`.
2. Update the version field in `pyproject.toml` and `mcp.json` (see [MCP Manifest](mcp-manifest.md)).
3. Build distributions with Hatch:

```bash
uv run hatch build
```

4. Inspect the generated `dist/` directory to confirm both `tar.gz` and `whl` artifacts contain the package, `mcp.json`, and documentation pointers.
5. Upload using `twine`:

```bash
uv run python -m twine upload dist/*
```

6. Create and tag a release (`git tag v0.2.0 && git push --tags`).

For release automation, configure GitHub Actions with a workflow that runs linting, tests, documentation build (`mkdocs build`), and publishes to PyPI on tagged commits. Store `PYPI_TOKEN` as an encrypted secret.
