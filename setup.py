"""
 Copyright (c) 2024 Yihuai Gao
 
 This software is released under the MIT License.
 https://opensource.org/licenses/MIT
"""

from setuptools import setup, Extension, find_packages
from setuptools.command.build_ext import build_ext
import sys
import os
import subprocess


class CMakeExtension(Extension):
    def __init__(self, name, sourcedir=""):
        Extension.__init__(self, name, sources=[])
        self.sourcedir = os.path.abspath(sourcedir)


class CMakeBuild(build_ext):
    def run(self):
        try:
            subprocess.check_output(["cmake", "--version"])
        except OSError:
            raise RuntimeError("CMake must be installed to build the extension")

        for ext in self.extensions:
            self.build_extension(ext)

    def build_extension(self, ext):
        extdir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))

        cmake_args = [
            f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={extdir}",
            f"-DPYTHON_EXECUTABLE={sys.executable}",
            "-DCMAKE_POSITION_INDEPENDENT_CODE=ON",
        ]

        # # Detect platform-specific settings
        # if platform.system() == "Windows":
        #     cmake_args += ['-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_{}={}'.format(
        #         cfg.upper(), extdir)]
        #     if sys.maxsize > 2**32:
        #         cmake_args += ["-A", "x64"]

        cfg = "Debug" if self.debug else "Release"
        build_args = ["--config", cfg]

        cmake_args += [f"-DCMAKE_BUILD_TYPE={cfg}"]
        # if platform.system() == "Windows":
        #     build_args += ["--", "/m"]
        # else:
        build_args += ["--", "-j"]

        env = os.environ.copy()
        env["CXXFLAGS"] = (
            f'{env.get("CXXFLAGS", "")} -DVERSION_INFO=\\"{self.distribution.get_version()}\\"'
        )

        if not os.path.exists(self.build_temp):
            os.makedirs(self.build_temp)

        # Find dependencies from pip-installed packages
        import sysconfig
        python_include = sysconfig.get_path('include')
        site_packages = sysconfig.get_path('purelib')

        # Add pip-installed include directories
        cmake_args += [
            f"-DCMAKE_PREFIX_PATH={site_packages}",
            f"-DPYTHON_INCLUDE_DIR={python_include}",
        ]

        subprocess.check_call(
            ["cmake", ext.sourcedir] + cmake_args, cwd=self.build_temp, env=env
        )
        subprocess.check_call(
            ["cmake", "--build", "."] + build_args, cwd=self.build_temp
        )

setup(
    ext_modules=[CMakeExtension("robotmq.core.robotmq")],
    cmdclass={"build_ext": CMakeBuild},
    zip_safe=False,
)