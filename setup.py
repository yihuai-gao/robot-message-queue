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
        
        # Get the directory containing setup.py
        source_dir = os.path.dirname(os.path.abspath(__file__))
        
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
        
        build_temp = os.path.join(self.build_temp, ext.name)
        if not os.path.exists(build_temp):
            os.makedirs(build_temp)
        # Define env before subprocess calls
        env = os.environ.copy()

        # Use source_dir instead of ext.sourcedir
        subprocess.check_call(
            ["cmake", source_dir] + cmake_args, cwd=build_temp, env=env
        )
        subprocess.check_call(
            ["cmake", "--build", "."] + build_args, cwd=build_temp
        )

setup(
    ext_modules=[CMakeExtension("robotmq.core.robotmq")],
    cmdclass={"build_ext": CMakeBuild},
    zip_safe=False,
)