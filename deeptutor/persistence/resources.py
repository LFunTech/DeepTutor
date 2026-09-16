"""显式 owner 文件资源：无身份发现、无全局 admin 根、无构造期写入。

头像对象不可变。先写对象再提交 PG 引用，失败移除新对象；旧对象只有在
元数据成功替换后清理。删除失败向调用者报告，未引用对象可按 owner 重试清理。
"""

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid

_OBJECT = re.compile(r"^[a-f0-9]{32}\.(png|jpg|webp)$")


class OwnerResourceProvider:
    def __init__(self, root):
        self.root = Path(root)
        if not self.root.is_absolute() or ".." in self.root.parts:
            raise ValueError("resource root must be an explicit absolute path")

    def _segments(self, tenant_id, owner_id, kind):
        tenant = str(uuid.UUID(tenant_id))
        if not isinstance(owner_id, str) or not owner_id or len(owner_id.encode()) > 1024:
            raise ValueError("invalid resource owner")
        if kind not in ("avatars", "secrets", "models", "attachments", "reading"):
            raise ValueError("invalid resource category")
        return (*self.root.parts[1:], tenant, hashlib.sha256(owner_id.encode()).hexdigest(), kind)

    @contextmanager
    def _directory(self, tenant_id, owner_id, kind, *, create=False):
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for segment in self._segments(tenant_id, owner_id, kind):
                if create:
                    try:
                        os.mkdir(segment, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                child = os.open(segment, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            yield fd
        finally:
            os.close(fd)

    def write_avatar(self, tenant_id, owner_id, data, extension):
        if extension not in ("png", "jpg", "webp") or len(data) > 1024 * 1024:
            raise ValueError("invalid avatar object")
        name = uuid.uuid4().hex + "." + extension
        with self._directory(tenant_id, owner_id, "avatars", create=True) as directory:
            fd = os.open(
                name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory
            )
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                    out.flush()
                    os.fsync(out.fileno())
                os.fsync(directory)
            except BaseException:
                os.unlink(name, dir_fd=directory)
                raise
        return name

    def read_avatar(self, tenant_id, owner_id, name):
        if not _OBJECT.fullmatch(name):
            raise FileNotFoundError("avatar not found")
        with self._directory(tenant_id, owner_id, "avatars") as directory:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_size > 1024 * 1024
                    or info.st_nlink != 1
                ):
                    raise PermissionError("unsafe avatar object")
                return source.read(1024 * 1024 + 1)

    def delete_avatar(self, tenant_id, owner_id, name):
        if not name:
            return
        if not _OBJECT.fullmatch(name):
            raise ValueError("invalid avatar object")
        try:
            with self._directory(tenant_id, owner_id, "avatars") as directory:
                os.unlink(name, dir_fd=directory)
                os.fsync(directory)
        except FileNotFoundError:
            return

    def owner_root(self, tenant_id, owner_id, kind):
        """仅供路径标识/兼容展示；PG adapter 实际 I/O 必须使用 bind_directory。"""
        with self._directory(tenant_id, owner_id, kind, create=True):
            return Path("/").joinpath(*self._segments(tenant_id, owner_id, kind))

    def bind_directory(self, tenant_id, owner_id, kind, *, codex=False):
        """绑定 owner 能力，不把普通 Path 当作安全读写授权。"""
        if codex and kind != "secrets":
            raise ValueError("invalid Codex resource category")
        return OwnerDirectory(self, tenant_id, owner_id, kind, codex=codex)


class OwnerDirectory:
    """可缓存的 owner 绑定；每次打开从 / 重新检查完整祖先，FD 不跨操作缓存。"""

    def __init__(self, provider, tenant_id, owner_id, kind, *, codex=False):
        self.provider = provider
        self.tenant_id, self.owner_id, self.kind = tenant_id, owner_id, kind
        self.subdirs = ("private", "openai-codex") if codex else ()
        self.path = Path("/").joinpath(
            *provider._segments(tenant_id, owner_id, kind), *self.subdirs
        )

    @contextmanager
    def open(self, *, create=False):
        with self.provider._directory(
            self.tenant_id, self.owner_id, self.kind, create=create
        ) as root:
            fd = os.dup(root)
            try:
                for part in self.subdirs:
                    if create:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=fd)
                        except FileExistsError:
                            pass
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = child
                yield OwnerDirectoryFiles(fd)
            finally:
                os.close(fd)


class OwnerDirectoryFiles:
    """仅在绑定的目录 FD 生命周期内使用；最终对象也不跟随链接。"""

    def __init__(self, fd):
        self.fd = fd

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or name in ("", ".", "..") or "/" in name or "\\" in name:
            raise ValueError("invalid owner file name")
        return name

    @staticmethod
    def _regular(info):
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PermissionError("unsafe owner file")

    def exists(self, name):
        try:
            self._regular(os.stat(self._name(name), dir_fd=self.fd, follow_symlinks=False))
            return True
        except FileNotFoundError:
            return False

    def read(self, name, *, max_bytes=None):
        fd = os.open(self._name(name), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            self._regular(info)
            if max_bytes is not None and info.st_size > max_bytes:
                raise OSError("owner file size limit exceeded")
            data = source.read() if max_bytes is None else source.read(max_bytes + 1)
            if max_bytes is not None and len(data) > max_bytes:
                raise OSError("owner file size limit exceeded")
            return data

    def write(self, name, data):
        self.exists(name)  # 已有最终对象必须为单链接普通文件。
        temp = "." + uuid.uuid4().hex + ".tmp"
        fd = os.open(
            temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd
        )
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            self.exists(name)
            os.replace(temp, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.fsync(self.fd)
        finally:
            try:
                os.unlink(temp, dir_fd=self.fd)
            except FileNotFoundError:
                pass

    def delete(self, name):
        if self.exists(name):
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)

    @contextmanager
    def lock(self, name):
        import fcntl

        fd = os.open(
            self._name(name),
            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
            dir_fd=self.fd,
        )
        try:
            self._regular(os.fstat(fd))
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
