"""
setup.py — 仅用于支持 bdist_wheel --plat-name 构建平台差异化 wheel。

正常安装/开发仍使用 pyproject.toml，无需直接调用此文件。
构建平台 wheel 的正确姿势：

    python setup.py bdist_wheel --plat-name win_amd64
    python setup.py bdist_wheel --plat-name manylinux_2_17_x86_64.manylinux2014_x86_64
    python setup.py bdist_wheel --plat-name macosx_11_0_arm64

或直接使用封装脚本（推荐）：

    python tools/build_platform_wheel.py --platform win32-x64
"""

from setuptools import setup

try:
    from wheel.bdist_wheel import bdist_wheel

    class PlatformBdistWheel(bdist_wheel):
        """
        生成 py3-none-<plat>.whl 格式的平台差异化 wheel。

        wheel 文件名由三段 tag 组成：<python>-<abi>-<platform>
        默认行为：
          - 纯 Python 包 → py3-none-any
          - 含 C 扩展     → cp312-cp312-win_amd64（绑定 CPython 版本）

        本项目只有 Python 代码 + 平台相关的 Node 二进制（数据文件），
        不依赖任何 CPython ABI，因此需要：
          python = "py3"    任意 Python 3 均可安装
          abi    = "none"   无 C 扩展 ABI 依赖
          plat   = 由 --plat-name 指定，如 win_amd64
        """

        def finalize_options(self) -> None:
            super().finalize_options()
            # 声明为非纯 Python，让 --plat-name 生效
            self.root_is_pure = False

        def get_tag(self):
            # 覆盖 ABI tag：不绑定 CPython 版本，保留平台 tag
            _python, _abi, plat = super().get_tag()
            return "py3", "none", plat

    cmdclass = {"bdist_wheel": PlatformBdistWheel}

except ImportError:
    cmdclass = {}


setup(cmdclass=cmdclass)
