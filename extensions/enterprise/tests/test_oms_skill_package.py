"""云端 Skill 完整 ZIP 内容只能由服务端 SKILL.md 导出元数据。"""

from io import BytesIO
import stat
import zipfile

import pytest


def _zip(files: dict[str, bytes | str]) -> bytes:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return stream.getvalue()


def _skill(name="socratic", description="引导式提问", body="用问题引导学习。") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"


def test_complete_skill_zip_reads_metadata_and_content_from_skill_md():
    from deeptutor_enterprise.oms.skill_package import validate_skill_archive

    payload = _zip(
        {
            "socratic/SKILL.md": _skill(),
            "socratic/references/examples.md": "# Example\n",
        }
    )
    package = validate_skill_archive(payload)
    assert package.name == "socratic"
    assert package.description == "引导式提问"
    assert package.body == "用问题引导学习。"
    assert package.files == (
        ("SKILL.md", _skill().encode()),
        ("references/examples.md", b"# Example\n"),
    )
    assert len(package.sha256) == 64


@pytest.mark.parametrize(
    "files",
    [
        {"socratic/README.md": "No skill"},
        {"socratic/SKILL.md": "# no frontmatter"},
        {"socratic/SKILL.md": _skill(name="")},
        {"socratic/SKILL.md": _skill(description="")},
        {"socratic/SKILL.md": _skill(body="  ")},
        {"wrong/SKILL.md": _skill()},
        {"socratic/SKILL.md": _skill(), "other/README.md": "other root"},
        {"socratic/SKILL.md": _skill(), "socratic/../evil.txt": "bad"},
        {"socratic/SKILL.md": _skill(), "socratic/data.bin": b"\0\1"},
        {"socratic/SKILL.md": _skill(), "socratic/.hidden": "bad"},
        {"socratic/SKILL.md": _skill(), "socratic/other.zip": "nested"},
        {"socratic/SKILL.md": _skill(), "socratic/refs.txt": "a" * 1_000_001},
        {"socratic/SKILL.md": _skill().replace("description:", "owner: tenant\ndescription:")},
    ],
)
def test_rejects_invalid_or_unsafe_skill_packages(files):
    from deeptutor_enterprise.oms.skill_package import SkillPackageRejected, validate_skill_archive

    with pytest.raises(SkillPackageRejected):
        validate_skill_archive(_zip(files))


def test_rejects_duplicate_normalized_path_and_corrupt_zip():
    from deeptutor_enterprise.oms.skill_package import SkillPackageRejected, validate_skill_archive

    payload = _zip({"socratic/SKILL.md": _skill(), "socratic\\SKILL.md": _skill()})
    with pytest.raises(SkillPackageRejected):
        validate_skill_archive(payload)
    with pytest.raises(SkillPackageRejected):
        validate_skill_archive(b"not a zip")


def test_rejects_duplicate_yaml_keys_and_symlink_members():
    from deeptutor_enterprise.oms.skill_package import SkillPackageRejected, validate_skill_archive

    duplicate_name = _skill().replace("description:", "name: other\ndescription:")
    with pytest.raises(SkillPackageRejected, match="unique"):
        validate_skill_archive(_zip({"socratic/SKILL.md": duplicate_name}))

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("socratic/SKILL.md", _skill())
        link = zipfile.ZipInfo("socratic/references/linked.md")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../../outside")
    with pytest.raises(SkillPackageRejected, match="symbolic"):
        validate_skill_archive(stream.getvalue())


def test_rejects_traversal_even_in_directory_entry():
    from deeptutor_enterprise.oms.skill_package import SkillPackageRejected, validate_skill_archive

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../outside/", b"")
        archive.writestr("socratic/SKILL.md", _skill())
    with pytest.raises(SkillPackageRejected, match="path"):
        validate_skill_archive(stream.getvalue())


def test_rejects_symlink_even_when_named_as_directory():
    from deeptutor_enterprise.oms.skill_package import SkillPackageRejected, validate_skill_archive

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("socratic/SKILL.md", _skill())
        link = zipfile.ZipInfo("socratic/references/")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "")
    with pytest.raises(SkillPackageRejected, match="symbolic"):
        validate_skill_archive(stream.getvalue())
