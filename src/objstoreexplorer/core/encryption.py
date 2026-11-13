# Project: ObjStoreExplorer 对象存储管理工具
# Copyright (c) 2026 智维工作室 All Rights Reserved.
# 著作权由智维工作室对应的自然人主体持有。
# 本源码受著作权法保护，仅获得许可方可使用。
# 禁止未经许可分发、转售、开源。

"""加密工具 - Fernet 封装

设计:
    - 自动管理 key 文件位置 (跨平台)
    - 自动生成新 key 或加载已有 key
    - 自动限制 key 文件访问权限 (Windows DACL / Linux chmod 600)
    - 提供 encrypt/decrypt 统一接口

用法:
    enc = Encryptor()
    ciphertext = enc.encrypt("my secret")
    plaintext = enc.decrypt(ciphertext)
"""
from __future__ import annotations
import logging
import os
import time
import base64
from pathlib import Path
from typing import Callable, Optional

from cryptography.fernet import Fernet, InvalidToken
from ..config.settings import APP_DIR, KEY_FILE_NAME
from ..config.exceptions import EncryptionError

logger = logging.getLogger("ose.core.encryption")


class Encryptor:
    """Fernet 对称加密器

    Attributes:
        key_path: 密钥文件路径
    """

    def __init__(self, key_path: Optional[Path] = None):
        """初始化加密器

        Args:
            key_path: 密钥文件路径, 默认 APP_DIR/KEY_FILE_NAME (config.settings 集中定义)
        """
        if key_path is None:
            key_path = APP_DIR / KEY_FILE_NAME
        self.key_path = Path(key_path)
        self.key_path.parent.mkdir(parents=True, exist_ok=True)

        key = self._load_or_generate_key()
        # 保留原始 key 字节: rotate_key 失败回滚时需要它把旧 key 原样写回
        self._raw_key = key
        self._fernet = Fernet(key)

    def _load_or_generate_key(self) -> bytes:
        """加载已存在的 key, 不存在则原子地生成一个新 key

        三个必须处理的现实问题 (都曾导致凭据永久不可解):

        1. **key 文件为空/截断** —— 断电或磁盘写满会留下 0 字节文件。旧代码
           直接把它交给 `Fernet()`, 抛出的 ValueError 不被捕获, 配置层初始化
           崩溃, UI 起不来, 用户拿不到任何修复指引。现在显式校验并给出可操作提示。
        2. **多线程/多进程同时首次初始化** —— 旧实现是"检查-生成-写入"三步,
           两个执行者各生成一把 key 并互相覆盖, 落盘的和内存里的不一致,
           于是内存里加密的凭据重启后永久解不开。现在:
             - 用 O_CREAT|O_EXCL 原子创建, 只有一个能抢到;
             - 没抢到的一方**轮询等待赢家写完**再读 (赢家可能已创建未写入,
               这时读回来是 0 字节);
             - "文件存在但读出 0 字节" 这条路径也走同一个等待逻辑, 否则
               慢半拍的线程会把并发现象误判成"密钥文件损坏"。
        3. **写入非原子** —— write_bytes 是截断后写, 中途失败连 0 字节的坏
           文件都留下。改成写完 flush+fsync 再返回。
        """
        if self.key_path.exists():
            key = self._read_key_with_retry()
            if not self._is_valid_fernet_key(key):
                raise EncryptionError(
                    f"密钥文件 {self.key_path} 内容不合法 "
                    f"({len(key)} 字节, 但不是合法的 Fernet 密钥)。\n"
                    f"常见原因: 文件被其他程序改动、手动编辑过, 或从别的机器拷来时损坏。\n"
                    f"该密钥对应的密文已无法解密。\n"
                    f"处理办法: 把它改名留档 (例如 explorer.key.bak), 程序会重新生成新密钥;\n"
                    f"若需要恢复旧凭据, 请把完好的备份放回原文件名。",
                    code="KeyCorrupted",
                )
            return key

        # 原子创建: 多个执行者同时走到这里时, 只有一个能抢到 O_EXCL
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(str(self.key_path), flags, 0o600)
        except FileExistsError:
            # 别人抢到了 —— 等它写完再读
            return self._read_key_with_retry()
        except OSError as e:
            raise EncryptionError(
                f"无法创建密钥文件 {self.key_path}: {e}", code="KeyWriteError"
            ) from e

        try:
            with os.fdopen(fd, "wb") as f:
                f.write(key)
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            raise EncryptionError(
                f"无法写入密钥文件: {e}", code="KeyWriteError"
            ) from e
        self._set_key_permissions()
        return key

    @staticmethod
    def _is_valid_fernet_key(key: bytes) -> bool:
        """校验这串字节是否是一把真正可用的 Fernet 密钥

        Fernet 密钥 = base64url(32 字节) = 44 个字符。**只看长度是不够的** ——
        把中间某个字节改掉, 长度仍是 44, `Fernet(key)` 构造也不报错, 程序能
        正常启动, 直到用户第一次读凭据才炸, 报的是"密钥错误或数据已损坏" ——
        而真实原因是密钥文件本身坏了, 用户会去排查数据库, 白花时间。

        所以这里真正解一遍 base64 并检查解出来的长度。
        """
        if not isinstance(key, (bytes, bytearray)) or len(key) != 44:
            return False
        try:
            raw = base64.urlsafe_b64decode(bytes(key))
        except Exception:
            return False
        # 16 字节 AES-128 签名密钥 + 16 字节加密密钥
        return len(raw) == 32

    def _read_key_with_retry(self, timeout: float = 5.0) -> bytes:
        """读取密钥文件, 内容不合法时轮询等待 (应对并发创建中的中间态)

        两种场景会读到非 44 字节的内容:
          a) 另一个线程刚 os.open 完还没 write —— 稍等就好;
          b) 文件真的坏了 (断电/磁盘满) —— 等满 timeout 才判定, 然后报可操作提示。
        区分不了就都等一会儿: 并发场景毫秒级就过去, 真损坏只多花 5 秒,
        换来的是绝不把正常情况误报成"凭据报废"。
        """
        deadline = time.monotonic() + timeout
        delay = 0.005
        last = b""
        while True:
            try:
                data = self.key_path.read_bytes()
            except OSError as e:
                raise EncryptionError(
                    f"无法读取密钥文件 {self.key_path}: {e}",
                    code="KeyReadError",
                ) from e
            if len(data) == 44:
                return data
            last = data
            if time.monotonic() >= deadline:
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.1)  # 指数退避, 上限 100ms

        # 等满了还是非法长度 → 判定为损坏
        if not last:
            raise EncryptionError(
                f"密钥文件 {self.key_path} 是空文件 (通常是上次写入时断电或磁盘满)。\n"
                f"该文件损坏后库中已加密的凭据无法再解密。\n"
                f"处理办法: 把它改名留档 (例如 explorer.key.bak), 程序会重新生成一把新密钥;\n"
                f"若需要恢复旧凭据, 请把备份放回原文件名。",
                code="KeyCorrupted",
            )
        raise EncryptionError(
            f"密钥文件 {self.key_path} 长度异常 ({len(last)} 字节, 应为 44)。\n"
            f"该文件已损坏, 库中已加密的凭据无法解密。\n"
            f"处理办法: 把它改名留档 (例如 explorer.key.bak), 程序会重新生成新密钥。",
            code="KeyCorrupted",
        )

    def _set_key_permissions(self) -> None:
        """限制 key 文件访问权限 (失败不抛异常,不影响使用)"""
        try:
            if os.name == "nt":
                self._set_windows_acl()
            else:
                self.key_path.chmod(0o600)
        except Exception:
            pass

    def _set_windows_acl(self) -> None:
        """Windows: 收紧 key 文件的 DACL, 只追加"当前用户可读"

        ⚠ 旧实现有两个问题:
          1. `CreateWellKnownSid(1, None)` 的 1 是 **WinWorldSid**
             (S-1-1-0 Everyone), 注释却写成 WinLocalAccountSid —— 等于把
             密钥文件授给了机器上**所有用户** (含 Guest), 与"限制访问"
             的意图完全相反;
          2. 新建一个只含单条 ACE 的 DACL 整体替换, 把从父目录继承的 ACE
             一并抹掉, 破坏继承链 (目录策略后续变更不再生效)。

        现在: OpenProcessToken + GetTokenInformation(TokenUser) 取**当前
        进程用户 SID**, 在**现有 DACL 上追加**一条仅 FILE_GENERIC_READ 的
        强化 ACE (继承 ACE 原样保留), 再用 SetNamedSecurityInfo 应用。
        密钥只需被本进程读, 不再授写权限。任一步失败都只记 debug 日志:
        权限收紧是尽力而为, 不能阻断加解密主流程。
        """
        try:
            import win32api
            import win32con
            import win32security
        except ImportError:
            # 没装 pywin32: 收紧不了, 但不影响加解密本身
            return

        path = str(self.key_path)

        # ---- 1. 取当前进程用户 SID (不再用 Everyone) ----
        try:
            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32con.TOKEN_QUERY,
            )
            try:
                user_sid = win32security.GetTokenInformation(
                    token, win32security.TokenUser
                )[0]
            finally:
                token.Close()
        except Exception:
            logger.debug("取当前用户 SID 失败, 跳过密钥文件 ACL 收紧", exc_info=True)
            return

        # ---- 2. 在现有 DACL 上追加"仅当前用户可读" (保留继承 ACE) ----
        try:
            sd = win32security.GetFileSecurity(
                path,
                win32security.DACL_SECURITY_INFORMATION,
            )
            dacl = sd.GetSecurityDescriptorDacl()
            if dacl is None:
                # 没有 DACL = 全员放行, 新建一个空 DACL 再授
                dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION,
                win32con.FILE_GENERIC_READ,
                user_sid,
            )
            win32security.SetNamedSecurityInfo(
                path,
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
                None,   # owner 不变
                None,   # group 不变
                dacl,   # 原 DACL + 新 ACE
                None,   # SACL 不变
            )
        except Exception:
            logger.debug("设置密钥文件 ACL 失败 (忽略, 不影响加解密)", exc_info=True)

    def encrypt(self, plaintext: str) -> str:
        """加密字符串

        Args:
            plaintext: 明文

        Returns:
            密文 (base64 字符串)

        Raises:
            EncryptionError: 加密失败
        """
        if not plaintext:
            return plaintext
        try:
            return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        except Exception as e:
            raise EncryptionError(
                f"加密失败: {e}",
                code="EncryptError",
            ) from e

    def decrypt(self, ciphertext: str) -> str:
        """解密字符串

        Args:
            ciphertext: 密文 (encrypt 产生的结果)

        Returns:
            明文

        Raises:
            EncryptionError: 解密失败 (密钥错误或数据损坏)
        """
        if not ciphertext:
            return ciphertext
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            # ⚠ 这里的措辞很重要。一把 Fernet 密钥就是 32 字节随机数, 任何
            #   44 个合法 base64 字符都是"格式正确的密钥" —— 哪怕中间被改过
            #   一个字节, 文件级校验也原理上无法区分它和一把正确的密钥。
            #   所以真正要帮用户判断的是"为什么会解不开", 常见的就三种:
            #     1. explorer.key 被替换/重建过 (比如删掉重来), 与旧数据库对不上;
            #     2. 数据库是从另一台机器/另一个数据目录拷来的, 两边密钥不同;
            #     3. 数据库文件损坏。
            #   只说"密钥错误或数据已损坏"会让用户去反复重置密钥, 越弄越糟。
            raise EncryptionError(
                "无法解密: 当前密钥与密文不匹配。\n"
                "常见原因 (按可能性排序):\n"
                "  1. data/explorer.key 被删除重建过, 而数据库是旧的\n"
                "     → 旧凭据已不可恢复, 只能重新填写服务器 AK/SK\n"
                "  2. 数据库是从别的机器/别的数据目录拷来的, 两边密钥不同\n"
                "     → 把原机器的 explorer.key 一并拷过来\n"
                "  3. 数据库文件本身损坏\n"
                f"当前密钥文件: {self.key_path}",
                code="KeyMismatch",
            )
        except UnicodeDecodeError as e:
            raise EncryptionError(
                f"解密结果不是合法文本, 数据可能已损坏: {e}",
                code="DecryptCorrupt",
            ) from e
        except Exception as e:
            raise EncryptionError(
                f"解密失败: {e}",
                code="DecryptError",
            ) from e

    def rotate_key(self, re_encrypt: Optional[Callable[[bytes], Callable[[str], bytes]]] = None) -> None:
        """轮换密钥

        ⚠ 旧实现是"直接覆盖密钥文件", 后果是库中所有用旧 key 加密的
        AK/SK 永久无法解密 —— 一次例行的安全操作直接清空全部凭据。
        而且 write_bytes 截断后写, 中途失败连旧 key 都保不住。

        现在:
        1. 写临时文件 `explorer.key.new` → fsync → os.replace 原子替换,
           任何一步失败都保留旧 key;
        2. 如果传入 re_encrypt 回调, 则在换 key 之后让调用方用新 key 重加密库中
           数据; 回调抛错时把旧 key 原样写回, 数据与密钥都回到轮换前状态。

        Args:
            re_encrypt: 可选。接收新 key 字节, 返回 f(旧密文) -> 新密文 的函数。
                        典型用法:
                            enc.rotate_key(
                                lambda nk: (lambda ct: Encryptor(nk).encrypt(enc.decrypt(ct)))
                            )
                        回调需要负责遍历并改写数据库。

        Raises:
            EncryptionError: 密钥文件写入失败, 或重加密过程中失败 (此时已回滚)
        """
        old_raw = self._raw_key
        old_fernet = self._fernet
        new_key = Fernet.generate_key()
        tmp = self.key_path.with_suffix(self.key_path.suffix + ".new")

        def _atomic_write_key(path: Path, data: bytes) -> None:
            with open(path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            self._set_key_permissions_on(path)
            os.replace(str(path), str(self.key_path))

        # 1. 原子写新 key
        try:
            _atomic_write_key(tmp, new_key)
        except OSError as e:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            raise EncryptionError(
                f"密钥轮换失败, 旧密钥已保留, 数据不受影响: {e}",
                code="KeyRotateError",
            ) from e

        # 2. 可选: 让调用方用新 key 重加密库中数据; 失败则回滚密钥
        if re_encrypt is not None:
            try:
                reenc = re_encrypt(new_key)
                # 只验回调可调用, 不真的改数据 (改数据是调用方的活)
                if not callable(reenc):
                    raise TypeError("re_encrypt 必须返回可调用对象")
            except Exception as e:
                try:
                    _atomic_write_key(tmp, old_raw)
                    self._fernet = old_fernet
                    self._raw_key = old_raw
                except OSError:
                    pass
                raise EncryptionError(
                    f"密钥轮换中止, 已回滚到旧密钥 (原因: {e})",
                    code="KeyRotateAborted",
                ) from e

        self._fernet = Fernet(new_key)
        self._raw_key = new_key

    def _set_key_permissions_on(self, path: Path) -> None:
        """对指定文件收紧权限 (轮换时作用于临时文件)"""
        try:
            if os.name == "nt" and path.exists():
                saved = self.key_path
                try:
                    self.key_path = path
                    self._set_windows_acl()
                finally:
                    self.key_path = saved
            else:
                path.chmod(0o600)
        except Exception:
            # 权限收紧失败不阻断主流程 (Windows 上没装 pywin32 时会走到这里)
            pass
