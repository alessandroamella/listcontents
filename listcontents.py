#!/usr/bin/env python3
import argparse
import os
import logging
import fnmatch
import subprocess
import shutil
from typing import List, Optional
from gitignore_parser import parse_gitignore

# Set up logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def find_git_root(start_path: str) -> Optional[str]:
    """
    Find the root directory of a git repository by looking for .git directory.

    Args:
        start_path (str): Directory to start searching from

    Returns:
        str or None: Path to git root directory, or None if not in a git repo
    """
    current_path = os.path.abspath(start_path)

    while True:
        git_dir = os.path.join(current_path, ".git")
        if os.path.exists(git_dir):
            return current_path

        parent_path = os.path.dirname(current_path)

        # Stop if we've reached the root directory
        if parent_path == current_path:
            return None

        current_path = parent_path


def is_git_repository(directory: str) -> bool:
    """
    Check if a directory is inside a git repository.

    Args:
        directory (str): Directory to check

    Returns:
        bool: True if inside a git repository, False otherwise
    """
    return find_git_root(directory) is not None


def check_pdftotext_available() -> bool:
    """
    Check if pdftotext utility is available on the system.

    Returns:
        bool: True if pdftotext is available, False otherwise.
    """
    return shutil.which("pdftotext") is not None


def extract_pdf_text(file_path: str) -> str:
    """
    Extract text from a PDF file using pdftotext utility.

    Args:
        file_path (str): Path to the PDF file

    Returns:
        str: Extracted text content or error message
    """
    try:
        # Run pdftotext to extract text to stdout
        result = subprocess.run(
            ["pdftotext", file_path, "-"],
            capture_output=True,
            text=True,
            timeout=30,  # 30 second timeout
        )

        if result.returncode == 0:
            return result.stdout
        else:
            return f"<Error extracting PDF text: {result.stderr.strip()}>"

    except subprocess.TimeoutExpired:
        return "<PDF text extraction timed out after 30 seconds>"
    except FileNotFoundError:
        return "<pdftotext utility not found>"
    except Exception as e:
        return f"<Error extracting PDF text: {str(e)}>"


def is_pdf_file(file_path: str) -> bool:
    """
    Check if a file is a PDF based on its extension.

    Args:
        file_path (str): Path to the file

    Returns:
        bool: True if file has .pdf extension, False otherwise
    """
    return file_path.lower().endswith(".pdf")


def is_binary_file(file_path: str) -> bool:
    """
    Check if a file is binary by scanning its content for null bytes.

    Args:
        file_path (str): Path to the file to check.

    Returns:
        bool: True if file is binary, False otherwise.
    """
    try:
        # Check if the file can be opened and read
        with open(file_path, "rb") as f:
            # Read the first 1024 bytes for analysis
            chunk = f.read(1024)
            # A file is binary if it contains a null byte
            return b"\x00" in chunk
    except Exception as e:
        logger.warning(f"Error checking if file is binary ({file_path}): {str(e)}")
        return True  # Treat as binary if an error occurs


def is_excluded(path: str, exclude_patterns: Optional[List[str]]) -> bool:
    """
    Check if a path should be excluded based on exclude patterns.

    Args:
        path (str): Path to check
        exclude_patterns (List[str]): List of patterns to exclude

    Returns:
        bool: True if path should be excluded, False otherwise
    """
    if not exclude_patterns:
        return False

    # Normalize path to use forward slashes for consistent matching
    norm_path = path.replace(os.sep, "/")

    for pattern in exclude_patterns:
        # Normalize pattern too
        norm_pattern = pattern.replace(os.sep, "/")

        # Check if pattern is a directory (ends with /)
        if norm_pattern.endswith("/"):
            # Directory pattern
            norm_pattern_dir = norm_pattern
            pattern_name = norm_pattern.rstrip("/")
            if (
                norm_path.startswith(norm_pattern_dir)
                or ("/" + pattern_name + "/") in norm_path
                or norm_path.endswith("/" + pattern_name)
            ):
                return True
        else:
            # File pattern - check exact match, path contains pattern, or filename matches
            filename = os.path.basename(norm_path)
            if (
                norm_path == norm_pattern
                or ("/" + norm_pattern) in norm_path
                or filename == norm_pattern
                or fnmatch.fnmatch(filename, norm_pattern)
                or fnmatch.fnmatch(norm_path, norm_pattern)
            ):
                return True

    return False


def is_included(
    path: str, include_patterns: Optional[List[str]], base_dir: str
) -> bool:
    """
    Check if a path should be included based on include patterns.

    Args:
        path (str): Absolute path to check
        include_patterns (List[str]): List of patterns to include
        base_dir (str): The starting directory for the script, to create relative paths

    Returns:
        bool: True if path should be included, False otherwise
    """
    if not include_patterns:
        return False  # If there are no include patterns, nothing is included.

    try:
        # Make the path relative to the starting directory for comparison
        rel_path = os.path.relpath(path, base_dir).replace(os.sep, "/")
    except ValueError:
        # This can happen if path and base_dir are on different drives (Windows)
        # Fall back to the full path, which may not work as expected but avoids a crash.
        rel_path = path.replace(os.sep, "/")

    for pattern in include_patterns:
        norm_pattern = pattern.replace(os.sep, "/")

        # Case 1: Pattern is explicitly a directory (e.g., "auth/")
        if norm_pattern.endswith("/"):
            if rel_path.startswith(norm_pattern):
                return True
        # Case 2: Pattern is a file/wildcard OR a directory name without a slash
        else:
            # Check for a file-level match (e.g., "*.py", "main.py")
            if fnmatch.fnmatch(rel_path, norm_pattern) or fnmatch.fnmatch(
                os.path.basename(rel_path), norm_pattern
            ):
                return True

            # Check for a directory-level match (e.g., "dir1")
            # A path matches if it is the directory itself or is inside that directory.
            if rel_path == norm_pattern or rel_path.startswith(norm_pattern + "/"):
                return True

    return False


def find_all_gitignore_files(directory: str) -> List[str]:
    """
    Find all .gitignore files within a git repository (from its root) or,
    if not in a repo, from the specified directory downward.

    Args:
        directory (str): The directory to start the search from.

    Returns:
        List[str]: A list of absolute paths to all found .gitignore files.
    """
    gitignore_files = []
    git_root = find_git_root(directory)
    start_walk_path = git_root if git_root else os.path.abspath(directory)

    try:
        for root, dirs, files in os.walk(start_walk_path, topdown=True):
            # Skip .git directories
            if ".git" in dirs:
                dirs.remove(".git")
            if ".gitignore" in files:
                gitignore_files.append(os.path.join(root, ".gitignore"))
    except Exception as e:
        logger.warning(f"Error scanning for .gitignore files: {str(e)}")

    return gitignore_files


def create_gitignore_matchers(gitignore_files: List[str]) -> List[tuple]:
    """
    Create a list of (base_dir, matcher) tuples from .gitignore files.

    Args:
        gitignore_files (List[str]): List of .gitignore file paths

    Returns:
        List[tuple]: A list of (base_directory, matcher_function) tuples.
    """
    matchers = []
    for gitignore_path in gitignore_files:
        try:
            if os.path.exists(gitignore_path):
                # The base directory is the directory containing the .gitignore file
                base_dir = os.path.dirname(gitignore_path)
                matcher = parse_gitignore(gitignore_path)
                if matcher:
                    # Store the base_dir and matcher together
                    matchers.append((base_dir, matcher))
        except Exception as e:
            logger.warning(
                f"Error parsing .gitignore file ({gitignore_path}): {str(e)}"
            )
    return matchers


def get_gitignore_matcher(gitignore_path: str):
    """
    Get a gitignore matcher function using gitignore_parser library.

    Args:
        gitignore_path (str): Path to the .gitignore file

    Returns:
        function or None: Matcher function or None if gitignore_parser is not available
    """

    try:
        if os.path.exists(gitignore_path):
            return parse_gitignore(gitignore_path)
        else:
            return None
    except Exception as e:
        logger.warning(f"Error parsing .gitignore file ({gitignore_path}): {str(e)}")
        return None


def should_process_file(
    file_path: str,
    base_dir: str,
    extensions: Optional[List[str]],
    exclude_patterns: Optional[List[str]],
    include_patterns: Optional[List[str]],
    gitignore_matchers: Optional[List] = None,
    allow_ignored: bool = False,
    parse_pdf: bool = False,
    git_root: Optional[str] = None,
) -> bool:
    """
    Determine if a file should be processed based on its extension and exclusion rules.

    Args:
        file_path (str): Absolute path to the file.
        base_dir (str): The starting directory for the script, to create relative paths.
        extensions (List[str]): List of allowed extensions (None means all).
        exclude_patterns (List[str]): List of patterns to exclude.
        include_patterns (List[str]): List of patterns to include.
        gitignore_matchers (List): List of matcher functions from gitignore_parser.
        allow_ignored (bool): Whether to process files ignored by .gitignore.
        parse_pdf (bool): Whether to parse PDF files.
        git_root (str): Path to git root directory for relative path calculation.

    Returns:
        bool: True if the file should be processed, False otherwise.
    """
    try:
        # Check for inclusion/exclusion based on provided patterns
        if include_patterns:
            # Include mode: file must match one of the include patterns
            if not is_included(file_path, include_patterns, base_dir):
                return False
        else:
            # Exclude mode: file must not match any of the exclude patterns
            if is_excluded(file_path, exclude_patterns):
                return False

        # Check gitignore patterns unless allow_ignored is True
        if not allow_ignored and gitignore_matchers:
            # Ensure we're using an absolute path for comparisons
            abs_file_path = os.path.abspath(file_path)
            # Unpack the tuple here
            for matcher_base_dir, matcher in gitignore_matchers:
                # Only apply a matcher if the file is within its directory scope.
                # os.path.commonpath is a robust way to check this.
                # Ensure the base directory is absolute for comparison
                abs_matcher_base_dir = os.path.abspath(matcher_base_dir)
                if (
                    os.path.commonpath([abs_file_path, abs_matcher_base_dir])
                    == abs_matcher_base_dir
                ):
                    if matcher(abs_file_path):
                        return False

        # Check file extension
        file_ext = os.path.splitext(file_path)[1].lower()

        # If parse_pdf is enabled and this is a PDF file, always process it
        if parse_pdf and file_ext == ".pdf":
            return True

        # If no extensions specified, process all files
        if not extensions:
            return True

        return file_ext in extensions
    except Exception as e:
        logger.warning(
            f"Error checking file processing criteria ({file_path}): {str(e)}"
        )
        return False


def process_file(file_path: str, base_dir: str, parse_pdf: bool = False) -> None:
    """
    Process a single file and print its contents.

    Args:
        file_path (str): Path to the file to process
        base_dir (str): Base directory for creating relative paths
        parse_pdf (bool): Whether to parse PDF files using pdftotext
    """
    try:
        # Check if file exists and is accessible
        if not os.path.exists(file_path):
            print(f"// {file_path}")
            print("<File not found>")
            print()
            return

        if not os.access(file_path, os.R_OK):
            print(f"// {file_path}")
            print("<Permission denied>")
            print()
            return

        # Get relative path
        try:
            rel_path = os.path.relpath(file_path, base_dir)
        except ValueError:
            # Handle case where file_path and base_dir are on different drives
            rel_path = file_path

        print(f"// {rel_path}")

        # Handle PDF files if parse_pdf is enabled
        if parse_pdf and is_pdf_file(file_path):
            pdf_text = extract_pdf_text(file_path)
            print(pdf_text)
            print()
            return

        # Handle binary files
        if is_binary_file(file_path):
            print("<Binary file>")
            print()
            return

        # Print file contents
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                print(f.read())
            print()
        except UnicodeDecodeError:
            print("<File contains invalid Unicode characters>")
            print()
        except PermissionError:
            print("<Permission denied>")
            print()
        except OSError as e:
            print(f"<Error reading file: {str(e)}>")
            print()
    except Exception as e:
        print(f"// {file_path}")
        print(f"<Error processing file: {str(e)}>")
        print()


def safe_walk(
    top: str,
    exclude_patterns: Optional[List[str]],
    include_patterns: Optional[List[str]],
    gitignore_matchers: Optional[List],
    allow_ignored: bool,
    **kwargs,
):
    """
    A safe version of os.walk that handles permission errors and respects exclusion rules.
    """
    try:
        for root, dirs, files in os.walk(top, topdown=True, **kwargs):
            abs_root = os.path.abspath(root)

            # Filter directories in-place to prevent traversal
            original_dirs = dirs[:]
            dirs[:] = []
            for d in original_dirs:
                dir_path = os.path.join(abs_root, d)

                # Handle include/exclude patterns first
                if include_patterns:
                    # Include mode: keep directory if it or a parent path matches an include pattern
                    keep_dir = False
                    # Get relative path of the directory being considered
                    rel_dir_path = os.path.relpath(dir_path, top).replace(os.sep, "/")

                    for pattern in include_patterns:
                        norm_pattern = pattern.replace(os.sep, "/").rstrip("/")
                        # Keep the directory if its path is a subpath of the pattern
                        # or if the pattern is a subpath of its path.
                        # This ensures we traverse into parent dirs of an included target.
                        if rel_dir_path.startswith(
                            norm_pattern
                        ) or norm_pattern.startswith(rel_dir_path):
                            keep_dir = True
                            break
                    if not keep_dir:
                        continue  # Prune this directory
                else:
                    # Exclude mode (original logic)
                    if is_excluded(dir_path, exclude_patterns):
                        continue

                # Then, handle gitignore logic for remaining directories
                is_dir_ignored = False
                if not allow_ignored and gitignore_matchers:
                    # Unpack the tuple here
                    for matcher_base_dir, matcher in gitignore_matchers:
                        # Only apply a matcher if the directory is within its scope.
                        abs_matcher_base_dir = os.path.abspath(matcher_base_dir)
                        if (
                            os.path.commonpath([dir_path, abs_matcher_base_dir])
                            == abs_matcher_base_dir
                        ):
                            if matcher(dir_path):
                                is_dir_ignored = True
                                break
                if not is_dir_ignored:
                    dirs.append(d)

            yield root, dirs, files
    except Exception as e:
        logger.warning(f"Error walking directory {top}: {str(e)}")
        yield top, [], []


def main():
    parser = argparse.ArgumentParser(description="Print contents of files in directory")
    parser.add_argument(
        "--dir",
        "-d",
        default=os.getcwd(),
        help="Starting directory (default: current directory)",
    )
    parser.add_argument(
        "--extensions",
        "-x",
        nargs="+",
        help="List of file extensions to include (e.g., .py .txt)",
    )
    parser.add_argument(
        "--max-depth", "-m", type=int, help="Maximum directory depth to traverse"
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--exclude",
        "-e",
        nargs="+",
        help="Patterns to exclude (e.g., node_modules/ vendor/). Cannot be used with --include.",
    )
    group.add_argument(
        "--include",
        "-i",
        nargs="+",
        help="Patterns to include (e.g., src/*.py). Only specified files/dirs are processed. Cannot be used with --exclude.",
    )

    parser.add_argument(
        "--include-all",
        "-a",
        action="store_true",
        help="Include all files, disabling default excludes (like node_modules/). No effect if --include is used.",
    )
    parser.add_argument("--skip-binary", action="store_true", help="Skip binary files")
    parser.add_argument(
        "--follow-links", action="store_true", help="Follow symbolic links"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--allow-ignored",
        action="store_true",
        help="Process files that are ignored by .gitignore",
    )
    parser.add_argument(
        "--parse-pdf",
        action="store_true",
        help="Parse PDF files using pdftotext utility (requires pdftotext to be installed)",
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.INFO)

    # Check if pdftotext is available when parse_pdf is requested
    if args.parse_pdf and not check_pdftotext_available():
        logger.error("pdftotext utility is not installed or not available in PATH")
        logger.error(
            "Please install poppler-utils package (or equivalent) to use --parse-pdf"
        )
        return 1

    # Handle default excludes.
    # The mutually exclusive group ensures only one of args.include or args.exclude is not None.
    default_excludes = [
        "node_modules/",
        "yarn.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
    ]

    if args.include_all and not args.include:
        # --include-all is used to override default excludes
        args.exclude = []
    elif not args.include:
        # If we are in exclude mode (default or explicit)
        if args.exclude is None:
            args.exclude = []

        # ALWAYS add defaults to the exclude list, even if user provided their own
        args.exclude.extend(default_excludes)

    # Convert extensions to lowercase and ensure they start with dot
    extensions = None
    if args.extensions:
        extensions = [
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            for ext in args.extensions
        ]

    # Load .gitignore matchers if .gitignore exists and not allowing ignored files
    gitignore_matchers = []
    git_root = find_git_root(args.dir)
    if not args.allow_ignored:
        gitignore_files = find_all_gitignore_files(args.dir)
        if gitignore_files:
            gitignore_matchers = create_gitignore_matchers(gitignore_files)
            if args.verbose and gitignore_matchers:
                if git_root:
                    logger.info(f"Found git repository at {git_root}")
                    logger.info(f"Loaded {len(gitignore_files)} gitignore file(s):")
                    for gf in gitignore_files:
                        logger.info(f"  - {gf}")
                else:
                    logger.info(f"Loaded gitignore patterns from {gitignore_files}")
        elif args.verbose:
            if git_root:
                logger.info("Inside git repository but no .gitignore files found")
            else:
                logger.info(
                    "Not inside a git repository and no local .gitignore files found"
                )

    try:
        # Walk through directory
        for root, dirs, files in safe_walk(
            args.dir,
            exclude_patterns=args.exclude,
            include_patterns=args.include,
            gitignore_matchers=gitignore_matchers,
            allow_ignored=args.allow_ignored,
            followlinks=args.follow_links,
        ):
            try:
                # Skip hidden directories
                dirs[:] = [d for d in dirs if not d.startswith(".")]

                # Check depth
                if args.max_depth is not None:
                    try:
                        current_depth = root[len(args.dir) :].count(os.sep)
                        if current_depth >= args.max_depth:
                            dirs[:] = []  # Don't go deeper
                            continue
                    except Exception as e:
                        logger.warning(f"Error checking directory depth: {str(e)}")
                        continue

                # Process files
                for file in sorted(files):
                    try:
                        if file.startswith("."):  # Skip hidden files
                            continue

                        file_path = os.path.join(root, file)

                        if should_process_file(
                            file_path,
                            args.dir,
                            extensions,
                            args.exclude,
                            args.include,
                            gitignore_matchers,
                            args.allow_ignored,
                            args.parse_pdf,
                            git_root,
                        ):
                            if args.skip_binary and is_binary_file(file_path):
                                continue
                            process_file(file_path, args.dir, args.parse_pdf)
                    except Exception as e:
                        logger.warning(f"Error processing file {file}: {str(e)}")
                        continue

            except Exception as e:
                logger.warning(f"Error processing directory {root}: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
