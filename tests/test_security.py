"""Security tests for HTML escaping and XSS prevention in markdown generation."""

from mcp_github_pr_review_spec_maker.server import escape_html_safe, generate_markdown


class TestHTMLEscaping:
    """Test HTML escaping functionality to prevent XSS attacks."""

    def test_generate_markdown_escapes_malicious_username(self) -> None:
        """Should escape malicious HTML in usernames to prevent XSS."""
        malicious_comment = {
            "user": {"login": '<script>alert("xss")</script>'},
            "path": "safe_file.py",
            "line": 42,
            "body": "Normal comment",
        }

        result = generate_markdown([malicious_comment])

        # Should escape the script tag in username
        assert "<script>" not in result
        assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;" in result
        assert "Review Comment by &lt;script&gt;" in result

    def test_generate_markdown_escapes_malicious_file_path(self) -> None:
        """Should escape malicious HTML in file paths."""
        malicious_comment = {
            "user": {"login": "safe_user"},
            "path": "test<img src=x onerror=alert(1)>.py",
            "line": 10,
            "body": "Comment about file",
        }

        result = generate_markdown([malicious_comment])

        # Should escape the img tag in file path
        assert "<img" not in result
        assert "&lt;img src=x onerror=alert(1)&gt;" in result
        assert "**File:** `test&lt;img" in result

    def test_generate_markdown_escapes_malicious_line_number(self) -> None:
        """Should escape malicious HTML in line numbers (edge case)."""
        malicious_comment = {
            "user": {"login": "user"},
            "path": "file.py",
            "line": "<script>alert('line')</script>",
            "body": "Comment",
        }

        result = generate_markdown([malicious_comment])

        # Should escape script in line number
        assert "<script>" not in result
        assert "&lt;script&gt;alert(" in result

    def test_generate_markdown_escapes_malicious_comment_body(self) -> None:
        """Should escape malicious HTML in comment bodies - main attack vector."""
        malicious_comment = {
            "user": {"login": "user"},
            "path": "file.py",
            "line": 1,
            "body": "Click here: <a href=\"javascript:alert('XSS')\">link</a>",
        }

        result = generate_markdown([malicious_comment])

        # Should escape the malicious link - content is escaped but javascript: remains
        # since it's part of escaped string (html.escape escapes tags not URL content)
        assert "<a href=" not in result  # Raw HTML tag should not be present
        assert "&lt;a href=&quot;javascript:alert(" in result

    def test_generate_markdown_escapes_malicious_diff_content(self) -> None:
        """Should escape malicious HTML in diff hunks."""
        malicious_comment = {
            "user": {"login": "user"},
            "path": "file.py",
            "line": 5,
            "body": "Comment about diff",
            "diff_hunk": '- old_line\n+ <iframe src="evil.com"></iframe>new_line',
        }

        result = generate_markdown([malicious_comment])

        # Should escape iframe in diff
        assert "<iframe" not in result
        assert "&lt;iframe src=&quot;evil.com&quot;&gt;" in result

    def test_generate_markdown_comprehensive_xss_payload(self) -> None:
        """Should handle comprehensive XSS payload across all fields."""
        xss_payload = '<script>alert("pwned")</script>'
        malicious_comment = {
            "user": {"login": f"evil{xss_payload}user"},
            "path": f"bad{xss_payload}file.py",
            "line": f"99{xss_payload}",
            "body": f"This comment has {xss_payload} embedded",
            "diff_hunk": f"- clean\n+ dirty{xss_payload}line",
        }

        result = generate_markdown([malicious_comment])

        # Should not contain any unescaped script tags
        assert "<script>" not in result
        assert 'alert("pwned")' not in result  # Raw payload
        # Should contain escaped versions
        assert "&lt;script&gt;alert(&quot;pwned&quot;)&lt;/script&gt;" in result

    def test_generate_markdown_handles_empty_and_none_values(self) -> None:
        """Should handle empty/None values gracefully without escaping issues."""
        edge_case_comment = {
            "user": {"login": ""},
            "path": None,
            "line": "",
            "body": None,
            "diff_hunk": "",
        }

        result = generate_markdown([edge_case_comment])

        # Should not crash and should handle None/empty values
        assert "# Pull Request Review Spec" in result
        assert "Review Comment by" in result

    def test_generate_markdown_preserves_safe_content(self) -> None:
        """Should preserve safe content without unnecessary escaping."""
        safe_comment = {
            "user": {"login": "normal_user"},
            "path": "src/components/Button.tsx",
            "line": 42,
            "body": "This looks good! Consider using const instead of let.",
            "diff_hunk": "- let isVisible = true;\n+ const isVisible = true;",
        }

        result = generate_markdown([safe_comment])

        # Should preserve normal content
        assert "normal_user" in result
        assert "Button.tsx" in result
        assert "This looks good!" in result
        assert "const isVisible" in result

    def test_generate_markdown_handles_unicode_and_special_chars(self) -> None:
        """Should handle unicode and special characters correctly."""
        unicode_comment = {
            "user": {"login": "用户名"},
            "path": "файл.py",
            "line": 1,
            "body": "Comment with émojis 🚀 and spéçial chars: ñoño",
            "diff_hunk": "- print('hello')\n+ print('héllo 世界')",
        }

        result = generate_markdown([unicode_comment])

        # Should preserve unicode without breaking
        assert "用户名" in result
        assert "🚀" in result
        assert "héllo 世界" in result

    def test_generate_markdown_mixed_safe_and_malicious_content(self) -> None:
        """Should handle mix of safe and malicious content correctly."""
        comments = [
            {  # Safe comment
                "user": {"login": "good_user"},
                "path": "safe.py",
                "line": 1,
                "body": "This is a normal comment",
            },
            {  # Malicious comment
                "user": {"login": "bad_user<script>"},
                "path": "evil.py",
                "line": 2,
                "body": "Evil comment <img src=x onerror=alert(1)>",
            },
        ]

        result = generate_markdown(comments)

        # Should preserve safe content
        assert "good_user" in result
        assert "This is a normal comment" in result

        # Should escape malicious content
        assert "<script>" not in result
        assert "<img" not in result
        assert "&lt;script&gt;" in result
        assert "&lt;img src=x onerror=alert(1)&gt;" in result


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling for security features."""

    def test_generate_markdown_handles_missing_user_field(self) -> None:
        """Should handle missing user field gracefully."""
        comment_no_user = {
            "path": "file.py",
            "line": 1,
            "body": "Comment without user",
        }

        result = generate_markdown([comment_no_user])

        # Should handle gracefully with N/A
        assert "Review Comment by N/A" in result

    def test_generate_markdown_handles_malformed_user_object(self) -> None:
        """Should handle malformed user objects gracefully."""
        comment_bad_user = {
            "user": "not_an_object",
            "path": "file.py",
            "line": 1,
            "body": "Comment with string user",
        }

        # Should handle gracefully without crashing
        result = generate_markdown([comment_bad_user])

        # Should default to N/A for malformed user object
        assert "Review Comment by N/A" in result
        assert "Comment with string user" in result

    def test_generate_markdown_extremely_long_malicious_content(self) -> None:
        """Should handle very long malicious content without performance issues."""
        long_payload = "<script>" * 1000 + "alert('big payload')" + "</script>" * 1000

        malicious_comment = {
            "user": {"login": "user"},
            "path": "file.py",
            "line": 1,
            "body": long_payload,
        }

        result = generate_markdown([malicious_comment])

        # Should escape without performance issues
        assert "<script>" not in result
        assert "&lt;script&gt;" in result
        assert len(result) > 0  # Should not crash or return empty


class TestEscapeHtmlSafeFunction:
    """Direct tests for the escape_html_safe function."""

    def test_escape_html_safe_basic_tags(self) -> None:
        """Should escape basic HTML tags."""
        result = escape_html_safe("<script>alert(1)</script>")
        assert result == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_escape_html_safe_quotes_and_attributes(self) -> None:
        """Should escape quotes and HTML attributes."""
        result = escape_html_safe('<img src="evil.jpg" onload="alert(1)">')
        assert result == (
            "&lt;img src=&quot;evil.jpg&quot; onload=&quot;alert(1)&quot;&gt;"
        )

    def test_escape_html_safe_empty_string(self) -> None:
        """Should handle empty strings gracefully."""
        result = escape_html_safe("")
        assert result == ""

    def test_escape_html_safe_none_values(self) -> None:
        """Should handle None values gracefully."""
        result = escape_html_safe(None)
        assert result == "N/A"

    def test_escape_html_safe_ampersand_already_escaped(self) -> None:
        """Should properly handle content that's already partially escaped."""
        result = escape_html_safe("&lt;script&gt; and <script>")
        # html.escape will escape the & in already-escaped part, making it &amp;lt;
        # This is correct behavior - html.escape doesn't know what's already escaped
        assert result == "&amp;lt;script&amp;gt; and &lt;script&gt;"

    def test_escape_html_safe_special_characters(self) -> None:
        """Should handle special characters that need escaping."""
        result = escape_html_safe("Test & verify < > \" ' symbols")
        # Should escape special HTML characters
        assert result == "Test &amp; verify &lt; &gt; &quot; &#x27; symbols"
