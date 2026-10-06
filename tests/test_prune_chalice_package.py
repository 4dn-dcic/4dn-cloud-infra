import subprocess
import zipfile


SCRIPT = "scripts/prune_chalice_package.sh"


def make_archive(path):
    entries = {
        "app.py": b"app\n",
        ".chalice/config.json": b"{}\n",
        "boto3/__init__.py": b"# protected\n",
        "boto3-1.0.dist-info/METADATA": b"Name: boto3\n",
        "awacs/__init__.py": b"# deployment only\n",
        "awacs-1.0.dist-info/METADATA": b"Name: awacs\n",
        "troposphere/__init__.py": b"# deployment only\n",
        "awscli/__init__.py": b"# foursight-smaht runtime\n",
        "awscli_customizations/__init__.py": b"# foursight-smaht runtime\n",
        "awscli-1.0.dist-info/METADATA": b"Name: awscli\n",
        "chalice/__init__.py": b"# chalice runtime\n",
        "chalice/app.py": b"# chalice runtime\n",
        "tibanna/__init__.py": b"# foursight runtime\n",
        "tibanna_ff/__init__.py": b"# foursight runtime\n",
        "tibanna_ff-1.0.dist-info/METADATA": b"Name: tibanna-ff\n",
        "chalicelib_smaht/app_utils.py": b"# selected\n",
        "chalicelib_fourfront/app_utils.py": b"# unselected\n",
        "library/tests/test_example.py": b"# test\n",
        "library/examples/example.py": b"# example\n",
        "keep.py": b"keep\n",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, contents in entries.items():
            archive.writestr(name, contents)


def names(path):
    with zipfile.ZipFile(path) as archive:
        return set(archive.namelist())


def run_script(*args):
    return subprocess.run(
        [SCRIPT, *args],
        check=False,
        text=True,
        capture_output=True,
    )


def test_default_pruning_keeps_runtime_and_variant_packages(tmp_path):
    archive = tmp_path / "package.zip"
    make_archive(archive)

    result = run_script(str(archive))

    assert result.returncode == 0, result.stderr
    archive_names = names(archive)
    assert "awacs/__init__.py" not in archive_names
    assert "awacs-1.0.dist-info/METADATA" not in archive_names
    assert "troposphere/__init__.py" not in archive_names
    assert "awscli/__init__.py" in archive_names
    assert "awscli_customizations/__init__.py" in archive_names
    assert "awscli-1.0.dist-info/METADATA" in archive_names
    assert "chalice/__init__.py" in archive_names
    assert "chalice/app.py" in archive_names
    assert "tibanna/__init__.py" in archive_names
    assert "tibanna_ff/__init__.py" in archive_names
    assert "tibanna_ff-1.0.dist-info/METADATA" in archive_names
    assert "boto3/__init__.py" in archive_names
    assert ".chalice/config.json" in archive_names
    assert "chalicelib_fourfront/app_utils.py" in archive_names
    assert "library/tests/test_example.py" not in archive_names
    assert "library/examples/example.py" not in archive_names
    assert "keep.py" in archive_names
    assert "Archive:" in result.stdout


def test_dry_run_reports_removals_without_changing_archive(tmp_path):
    archive = tmp_path / "package.zip"
    make_archive(archive)
    before = archive.read_bytes()

    result = run_script("--dry-run", "--report", "--variant", "smaht", str(archive))

    assert result.returncode == 0, result.stderr
    assert archive.read_bytes() == before
    assert "Dry run: archive unchanged." in result.stdout
    assert "awacs" in result.stdout
    assert "chalicelib_fourfront" in result.stdout
    assert "chalicelib_smaht/app_utils.py" in names(archive)


def test_variant_requires_selected_application_package(tmp_path):
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("app.py", b"app\n")

    result = run_script("--variant", "cgap", str(archive))

    assert result.returncode != 0
    assert "selected variant package is missing: chalicelib_cgap" in result.stderr


def test_rejects_parent_traversal_archive_entry(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../outside.txt", b"must not extract\n")

    result = run_script(str(archive))

    assert result.returncode != 0
    assert "unsafe path in zip archive" in result.stderr
    assert not (tmp_path.parent / "outside.txt").exists()
