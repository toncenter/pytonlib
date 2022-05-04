from setuptools import setup, find_packages
from os.path import dirname, join


with open(join(dirname(__file__), "README.md"), "r") as f:
    long_description = f.read()


setup(
    author='K-Dimentional Tree',
    author_email='kdimentionaltree@gmail.com',
    name='pytonlib',
    version='0.0.2',
    packages=find_packages('.', exclude=['tests']),
    install_requires=[
        'crc16==0.1.1',
        'tvm_valuetypes==0.0.8',
        'requests==2.27.1',
    ],
    package_data={
        'pytonlib': ['distlib/linux/*',
                     'distlib/darwin/*'],
        'pytonlib.utils': []
    },
    zip_safe=True,
    python_requires='>=3.7',
    classifiers=[
         "Development Status :: 3 - Alpha",
         "Intended Audience :: Developers",
         "Programming Language :: Python :: 3.7",
         "Programming Language :: Python :: 3.8",
         "Programming Language :: Python :: 3.9",
         "License :: Other/Proprietary License",
         "Topic :: Software Development :: Libraries"
    ],
    url="https://github.com/toncenter/pytonlib",
    description="Python API for TON (Telegram Open Network)",
    long_description_content_type="text/markdown",
    long_description=long_description,
)
