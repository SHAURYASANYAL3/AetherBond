from setuptools import setup, find_packages

setup(
    name="aetherbond",
    version="2.0.0",
    packages=find_packages(),
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
