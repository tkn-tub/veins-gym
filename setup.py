from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="veins_gym",
    version="0.3.0",
    author="Dominik S. Buse",
    author_email="buse@ccs-labs.org",
    description="Reinforcement Learning-based VANET simulations",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://www2.tkn.tu-berlin.de/software/veins-gym/",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.6",
    package_dir={"": "src"},
    data_files=[("protobuf", ["protobuf/veinsgym.proto"])],
    packages=["veins_gym"],
    install_requires=[
        "gym",
        "protobuf",
        "zmq",
    ],
)
