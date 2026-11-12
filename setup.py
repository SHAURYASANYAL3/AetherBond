from setuptools import setup, find_packages

setup(
    name="aetherbond",
    version="2.1.0",
    packages=find_packages(),
    install_requires=[
        "customtkinter>=6.0.0",
    ],
    entry_points={
        "console_scripts": [
            "aetherbond = aetherbond.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "aetherbond.web": ["static/*"],
    },
)
