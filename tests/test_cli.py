"""Tests for the CLI module."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pyvisualizer.cli import main


class TestCLI:
    """Tests for CLI functionality."""

    def test_help_option(self):
        """Test that --help works."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_version_option(self):
        """Test that --version works."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0

    def test_missing_path(self):
        """Test that missing path raises error."""
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_invalid_path(self, capsys):
        """Test that invalid path raises error."""
        result = main(["/nonexistent/path"])
        assert result == 1

    def test_sample_project_html(self, sample_project_path, temp_output_dir):
        """Test generating HTML visualization for sample project."""
        output_file = temp_output_dir / "test.html"
        result = main([str(sample_project_path), "--format", "html", "--output", str(output_file)])

        assert result == 0
        assert output_file.exists()

        # Check HTML content
        content = output_file.read_text()
        assert "<!DOCTYPE html>" in content
        # Self-contained viewer: embeds graph data and template is fully rendered.
        assert 'id="graph-data"' in content
        assert "__GRAPH_DATA__" not in content
        # Zero network requests: no external resource loading (CDN scripts,
        # stylesheets, fonts). The SVG namespace URI is not a network request.
        for pat in ('src="http', "src='http", 'href="http', "href='http", "@import", "cdn."):
            assert pat not in content, f"unexpected external resource: {pat}"

    def test_sample_project_mermaid(self, sample_project_path, temp_output_dir):
        """Test generating Mermaid diagram for sample project."""
        output_file = temp_output_dir / "test.mmd"
        result = main(
            [str(sample_project_path), "--format", "mermaid", "--output", str(output_file)]
        )

        assert result == 0
        assert output_file.exists()

        # Check Mermaid content
        content = output_file.read_text()
        assert "flowchart" in content

    def test_max_nodes_filter(self, sample_project_path, temp_output_dir):
        """Test that max-nodes filter works."""
        output_file = temp_output_dir / "test.html"
        result = main(
            [
                str(sample_project_path),
                "--format",
                "html",
                "--output",
                str(output_file),
                "--max-nodes",
                "5",
            ]
        )

        assert result == 0
        assert output_file.exists()

    def test_exclude_filter(self, sample_project_path, temp_output_dir):
        """Test that exclude filter works."""
        output_file = temp_output_dir / "test.html"
        result = main(
            [
                str(sample_project_path),
                "--format",
                "html",
                "--output",
                str(output_file),
                "--exclude",
                "module_a",
            ]
        )

        assert result == 0
        assert output_file.exists()

    def test_verbose_mode(self, sample_project_path, temp_output_dir, capsys):
        """Test verbose mode enables debug logging."""
        output_file = temp_output_dir / "test.html"
        result = main(
            [
                str(sample_project_path),
                "--format",
                "html",
                "--output",
                str(output_file),
                "--verbose",
            ]
        )

        assert result == 0

    def test_project_name_override(self, sample_project_path, temp_output_dir):
        """Test custom project name."""
        output_file = temp_output_dir / "test.html"
        result = main(
            [
                str(sample_project_path),
                "--format",
                "html",
                "--output",
                str(output_file),
                "--project-name",
                "My Custom Project",
            ]
        )

        assert result == 0
        content = output_file.read_text()
        assert "My Custom Project" in content

    def test_single_file_input(self, temp_python_file, temp_output_dir):
        """Test analyzing a single Python file."""
        output_file = temp_output_dir / "test.html"
        result = main([str(temp_python_file), "--format", "html", "--output", str(output_file)])

        assert result == 0
        assert output_file.exists()
